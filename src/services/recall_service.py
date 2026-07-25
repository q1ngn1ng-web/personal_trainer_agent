"""Recall question extractor for the daily card."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from src.core.content_dim import DEFAULT_DAILY_RATIO, ContentDimension, distribute_by_ratio
from src.db.queries import get_training
from src.services.schedule_service import interval_for_index

logger = logging.getLogger("src.services.recall_service")


@dataclass
class RecallQuestion:
    qid: str
    unit: str
    dimension: ContentDimension
    question: str
    reference: str


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _coerce_dimension(value: Any) -> ContentDimension:
    for member in ContentDimension:
        if member.english == str(value or "").strip().lower():
            return member
        if member.chinese == str(value or "").strip():
            return member
    return ContentDimension.CONCEPT


def _read_recall_units(training: Any) -> list[dict[str, Any]]:
    materials = training.materials if isinstance(training.materials, dict) else {}
    units = materials.get("recall_units")
    if not isinstance(units, list):
        return []
    return [u for u in units if isinstance(u, dict)]


def _unit_due(unit: dict[str, Any], today: date) -> bool:
    review_count = int(unit.get("review_count") or 0)
    last_reviewed = _coerce_date(unit.get("last_reviewed_date"))
    if review_count <= 0 or last_reviewed is None:
        return True
    interval_idx = max(review_count - 1, 0)
    due = last_reviewed + timedelta(days=interval_for_index(interval_idx))
    return due <= today


def _round_robin(
    queues: dict[ContentDimension, list[tuple[str, dict[str, Any]]]],
    quota: dict[ContentDimension, int],
) -> list[RecallQuestion]:
    result: list[RecallQuestion] = []
    while True:
        picked = False
        for dimension in DEFAULT_DAILY_RATIO.keys():
            if quota.get(dimension, 0) <= 0:
                continue
            queue = queues.get(dimension, [])
            if not queue:
                continue
            unit_name, raw = queue.pop(0)
            qid = str(raw.get("qid") or raw.get("id") or f"Q-{len(result) + 1}")
            result.append(
                RecallQuestion(
                    qid=qid,
                    unit=unit_name,
                    dimension=dimension,
                    question=str(raw.get("question") or ""),
                    reference=str(raw.get("reference") or ""),
                )
            )
            quota[dimension] = quota.get(dimension, 0) - 1
            picked = True
        if not picked:
            break
    return result


def get_today_recall_questions(
    training_id: int,
    today: date | None = None,
    *,
    max_questions: int = 5,
) -> list[RecallQuestion]:
    """Return today’s recall questions, distributed by content-dimension ratio."""
    effective_today = today or date.today()
    training = get_training(training_id)
    if training is None:
        return []

    units = _read_recall_units(training)
    if not units:
        return []

    queues: dict[ContentDimension, list[tuple[str, dict[str, Any]]]] = {}
    for unit in units:
        if not _unit_due(unit, effective_today):
            continue
        unit_name = str(unit.get("unit") or unit.get("name") or "未命名单元")
        dimension = _coerce_dimension(unit.get("dimension"))
        questions = unit.get("questions") or []
        if not isinstance(questions, list):
            continue
        for raw in questions:
            if isinstance(raw, dict):
                queues.setdefault(dimension, []).append((unit_name, raw))

    if not queues:
        return []

    quota = distribute_by_ratio(max_questions, DEFAULT_DAILY_RATIO)
    return _round_robin(queues, quota)


__all__ = ["get_today_recall_questions", "RecallQuestion"]
