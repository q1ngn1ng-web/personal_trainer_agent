"""Orchestrator for the weekly review flow.

Ties together metrics calculation, LLM calibration, persistence of new training
state and archive snapshots for downstream analysis.
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from src.core.baseline import compute_level
from src.db.models import Training
from src.db.queries import (
    add_baseline_history,
    create_review_archive,
    get_training,
    update_training,
)
from src.services.calibration_service import (
    CalibrationSuggestion,
    generate_calibration,
)
from src.services.metrics_calculator import WeeklyMetrics, compute_weekly_metrics

logger = logging.getLogger("src.services.review_service")

_BASELINE_MIN: float = 0.0
_BASELINE_MAX: float = 5.0


@dataclass
class ReviewOutcome:
    """Outcome of a weekly review preparation or application."""

    metrics: WeeklyMetrics
    suggestion: CalibrationSuggestion
    applied: bool


def _clamp_score(value: float) -> float:
    if value < _BASELINE_MIN:
        return _BASELINE_MIN
    if value > _BASELINE_MAX:
        return _BASELINE_MAX
    return round(value, 2)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in (None, "", b""):
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value in (None, "", b""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if isinstance(parsed, list):
            return list(parsed)
    return []


def _merge_schedule(
    schedule: Any, adjustment: Mapping[str, str]
) -> dict[str, Any]:
    base = _coerce_mapping(schedule)
    for key, value in adjustment.items():
        if value is None:
            continue
        base[str(key)] = str(value)
    return base


def _apply_material_actions(
    materials: Any, recommendations: list[dict[str, Any]]
) -> dict[str, Any]:
    base = _coerce_mapping(materials)
    references = _coerce_list(base.get("references"))
    kept: list[Any] = []
    refs_to_remove: set[str] = set()
    refs_to_add: list[dict[str, Any]] = []

    for ref in references:
        if isinstance(ref, Mapping):
            ref_key = ref.get("ref")
        else:
            ref_key = ref
        if isinstance(ref_key, str) and ref_key in {
            rec.get("ref") for rec in recommendations if rec.get("action") == "remove"
        }:
            continue
        kept.append(ref)

    for rec in recommendations:
        if not isinstance(rec, Mapping):
            continue
        action = rec.get("action")
        ref = rec.get("ref")
        if not isinstance(ref, str) or not ref:
            continue
        if action == "add" and ref not in {
            (item.get("ref") if isinstance(item, Mapping) else item)
            for item in kept
        }:
            payload: dict[str, Any] = {"ref": ref}
            reason = rec.get("reason")
            if reason:
                payload["reason"] = reason
            refs_to_add.append(payload)
    kept.extend(refs_to_add)

    if kept or recommendations:
        base["references"] = kept
    else:
        base.pop("references", None)
    return base


def _new_baseline_score(training: Training, delta: float) -> float:
    return _clamp_score(float(training.baseline_score or 0.0) + float(delta))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_state_changes(
    training: Training,
    metrics: WeeklyMetrics,
    suggestion: CalibrationSuggestion,
    now_iso: str,
) -> Training:
    new_score = _new_baseline_score(training, suggestion.baseline_score_delta)
    new_level = compute_level(new_score)
    schedule = _merge_schedule(training.schedule, suggestion.schedule_adjustment)
    materials = _apply_material_actions(
        training.materials, suggestion.material_recommendations
    )
    updates: dict[str, Any] = {
        "baseline_score": new_score,
        "baseline_level": new_level.value,
        "schedule": schedule,
        "materials": materials,
        "last_review_at": now_iso,
        "last_active_at": now_iso,
        "current_week": int(training.current_week or 0) + 1,
    }
    updated = update_training(int(training.id or 0), **updates)
    if updated is None:
        raise RuntimeError(
            f"apply_weekly_review: training {training.id} not found after update"
        )
    return updated


def _ensure_training(training_id: int) -> Training:
    training = get_training(training_id)
    if training is None:
        raise ValueError(f"prepare_weekly_review: no training with id={training_id}")
    return training


def prepare_weekly_review(
    training_id: int, *, today: date | None = None
) -> ReviewOutcome:
    """Compute weekly metrics + calibration suggestion without applying them."""
    training = _ensure_training(training_id)
    metrics = compute_weekly_metrics(training_id, today=today)
    suggestion = generate_calibration(training, metrics)
    return ReviewOutcome(metrics=metrics, suggestion=suggestion, applied=False)


def apply_weekly_review(
    training_id: int,
    suggestion: CalibrationSuggestion,
    *,
    today: date | None = None,
) -> ReviewOutcome:
    """Apply a calibration suggestion: persist new baseline/schedule/materials + archive."""
    training = _ensure_training(training_id)
    metrics = compute_weekly_metrics(training_id, today=today)
    now_iso = _now_iso()
    _apply_state_changes(training, metrics, suggestion, now_iso)
    add_baseline_history(
        training_id,
        _new_baseline_score(training, suggestion.baseline_score_delta),
        "{}",
    )
    create_review_archive(
        training_id,
        metrics.week_start,
        metrics.to_json(),
        _coerce_raw(suggestion),
        "confirmed",
    )
    return ReviewOutcome(metrics=metrics, suggestion=suggestion, applied=True)


def skip_weekly_review(
    training_id: int, *, today: date | None = None
) -> ReviewOutcome:
    """Skip a weekly review: archive the prepared snapshot but persist no changes."""
    outcome = prepare_weekly_review(training_id, today=today)
    create_review_archive(
        training_id,
        outcome.metrics.week_start,
        outcome.metrics.to_json(),
        _coerce_raw(outcome.suggestion),
        "skipped",
    )
    return ReviewOutcome(
        metrics=outcome.metrics, suggestion=outcome.suggestion, applied=False
    )


def _coerce_raw(suggestion: CalibrationSuggestion) -> Any:
    raw = suggestion.raw
    if isinstance(raw, str):
        return raw
    return copy.deepcopy(raw)


__all__ = [
    "ReviewOutcome",
    "prepare_weekly_review",
    "apply_weekly_review",
    "skip_weekly_review",
]
