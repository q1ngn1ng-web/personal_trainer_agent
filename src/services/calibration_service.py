"""LLM-driven weekly calibration suggestions.

Wraps the ``weekly_calibration`` LLM call with a schema-enforced contract and a
heuristic fallback when the call exhausts its retries.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.models import Training
from src.db.queries import record_llm_call
from src.llm.client import LLMError, complete
from src.llm.prompts import WEEKLY_CALIBRATION_PROMPT_VERSION
from src.services.metrics_calculator import DEFAULT_TOPIC, WeeklyMetrics

logger = logging.getLogger("src.services.calibration_service")

_PROMPT_NAME: str = "weekly_calibration"
_RECALL_TARGET: float = 0.7
_DELTA_CAP: float = 0.5
_SENTINEL_DATE: str = "1970-01-01"


def _resolve_goal(training: Training) -> str:
    """Pick a reasonable ``goal`` string from the training's available fields."""
    targets = training.targets
    if isinstance(targets, str) and targets.strip():
        return targets
    if isinstance(targets, list) and targets:
        return "; ".join(str(item) for item in targets[:3])
    if isinstance(targets, dict) and targets:
        return json.dumps(targets, ensure_ascii=False)
    return training.topic


def _build_prompt_variables(training: Training, metrics: WeeklyMetrics) -> dict[str, Any]:
    return {
        "topic": training.topic,
        "baseline_score": training.baseline_score,
        "goal": _resolve_goal(training),
        "metrics": metrics.to_plain_dict(),
        "current_baseline_score": training.baseline_score,
        "current_baseline_level": training.baseline_level or "",
        "materials": training.materials,
    }


def _record_call(
    training_id: int | None,
    *,
    success: bool,
    result: dict[str, Any] | None,
    failure_reason: str | None,
    fallback_used: bool,
) -> None:
    persisted_training_id = training_id if training_id and training_id > 0 else None
    if success and result is not None:
        record_llm_call(
            training_id=persisted_training_id,
            call_purpose=_PROMPT_NAME,
            prompt_name=result.get("prompt_name", _PROMPT_NAME),
            prompt_version=result.get("prompt_version", WEEKLY_CALIBRATION_PROMPT_VERSION),
            model=result.get("model", "unknown"),
            input_text=json.dumps(
                {"output_keys": sorted((result.get("output_json") or {}).keys())},
                ensure_ascii=False,
            ),
            output_text=result.get("output_text") or "",
            output_json=result.get("output_json"),
            validation_result="pass",
            retry_count=int(result.get("retry_count", 0) or 0),
            latency_ms=int(result.get("latency_ms", 0) or 0),
            tokens_in=int(result.get("tokens_in", 0) or 0),
            tokens_out=int(result.get("tokens_out", 0) or 0),
            failure_reason=None,
            fallback_used=0,
        )
        return
    record_llm_call(
        training_id=persisted_training_id,
        call_purpose=_PROMPT_NAME,
        prompt_name=_PROMPT_NAME,
        prompt_version=WEEKLY_CALIBRATION_PROMPT_VERSION,
        model="n/a",
        input_text=json.dumps({"phase": "fallback"}, ensure_ascii=False),
        output_text=None,
        output_json=None,
        validation_result="fail",
        retry_count=0,
        latency_ms=0,
        tokens_in=0,
        tokens_out=0,
        failure_reason=failure_reason,
        fallback_used=1 if fallback_used else 0,
    )


def _clamp_delta(value: float) -> float:
    if value > _DELTA_CAP:
        return _DELTA_CAP
    if value < -_DELTA_CAP:
        return -_DELTA_CAP
    return round(value, 1)


def _heuristic_suggestion(
    training: Training,
    metrics: WeeklyMetrics,
    failure_reason: str,
) -> "CalibrationSuggestion":
    delta = _clamp_delta((metrics.avg_recall_success - _RECALL_TARGET) * 0.5)
    low_recall = metrics.avg_recall_success < _RECALL_TARGET
    if low_recall:
        topic_key = metrics.weakest_topic or training.topic or DEFAULT_TOPIC
        schedule = {topic_key: "降低密度"}
    else:
        schedule = {DEFAULT_TOPIC: "维持"}
    raw: dict[str, Any] = {
        "source": "heuristic_fallback",
        "delta_seed": metrics.avg_recall_success,
        "generated_at": _SENTINEL_DATE,
        "reason": failure_reason,
    }
    return CalibrationSuggestion(
        baseline_score_delta=delta,
        schedule_adjustment=schedule,
        material_recommendations=[],
        reward_refresh="保持当前奖励",
        next_week_focus=(
            "巩固薄弱环节"
            if metrics.weakest_topic
            else "保持当前节奏"
        ),
        raw=raw,
        fallback_used=True,
    )


@dataclass
class CalibrationSuggestion:
    """Structured calibration proposal for the upcoming week."""

    baseline_score_delta: float
    schedule_adjustment: dict[str, str] = field(default_factory=dict)
    material_recommendations: list[dict[str, Any]] = field(default_factory=list)
    reward_refresh: str = ""
    next_week_focus: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_output(output: Any) -> dict[str, Any]:
    if output is None:
        return {}
    if not isinstance(output, dict):
        raise LLMError(f"weekly_calibration returned non-object: {type(output).__name__}")
    delta = output.get("baseline_score_delta", 0.0)
    if not isinstance(delta, (int, float)):
        raise LLMError(f"baseline_score_delta not numeric: {delta!r}")
    schedule = output.get("schedule_adjustment") or {}
    if not isinstance(schedule, dict):
        schedule = {}
    materials = output.get("material_recommendations") or []
    if not isinstance(materials, list):
        materials = []
    return {
        "baseline_score_delta": _clamp_delta(float(delta)),
        "schedule_adjustment": {str(k): str(v) for k, v in schedule.items()},
        "material_recommendations": [
            item for item in materials if isinstance(item, dict)
        ],
        "reward_refresh": str(output.get("reward_refresh") or ""),
        "next_week_focus": str(output.get("next_week_focus") or ""),
    }


def generate_calibration(
    training: Training, metrics: WeeklyMetrics
) -> CalibrationSuggestion:
    """Generate a weekly calibration suggestion via LLM (with heuristic fallback)."""
    variables = _build_prompt_variables(training, metrics)
    training_id = training.id if training.id is not None else 0
    try:
        result = complete(_PROMPT_NAME, variables)
    except Exception as exc:
        logger.warning(
            "generate_calibration: LLM call failed for training=%s: %s",
            training_id,
            exc,
        )
        suggestion = _heuristic_suggestion(training, metrics, str(exc))
        raw = dict(suggestion.raw)
        raw["generated_at"] = datetime.now(timezone.utc).isoformat()
        suggestion.raw = raw
        _record_call(
            training_id,
            success=False,
            result=None,
            failure_reason=str(exc),
            fallback_used=True,
        )
        return suggestion

    raw_output = result.get("output_json") or {}
    try:
        normalized = _normalize_output(raw_output)
    except LLMError as exc:
        logger.warning(
            "generate_calibration: LLM output unusable for training=%s: %s",
            training_id,
            exc,
        )
        suggestion = _heuristic_suggestion(training, metrics, str(exc))
        raw = dict(suggestion.raw)
        raw["generated_at"] = datetime.now(timezone.utc).isoformat()
        suggestion.raw = raw
        _record_call(
            training_id,
            success=False,
            result=result,
            failure_reason=str(exc),
            fallback_used=True,
        )
        return suggestion

    raw: dict[str, Any] = {
        "source": "llm",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_output": raw_output,
        "retry_count": result.get("retry_count", 0),
        "latency_ms": result.get("latency_ms", 0),
        "model": result.get("model"),
        "prompt_version": result.get("prompt_version", WEEKLY_CALIBRATION_PROMPT_VERSION),
    }
    _record_call(training_id, success=True, result=result, failure_reason=None, fallback_used=False)
    return CalibrationSuggestion(
        baseline_score_delta=normalized["baseline_score_delta"],
        schedule_adjustment=normalized["schedule_adjustment"],
        material_recommendations=normalized["material_recommendations"],
        reward_refresh=normalized["reward_refresh"],
        next_week_focus=normalized["next_week_focus"],
        raw=raw,
        fallback_used=False,
    )


__all__ = ["CalibrationSuggestion", "generate_calibration"]
