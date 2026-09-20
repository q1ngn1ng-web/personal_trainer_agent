"""Spaced-repetition schedule extractor for the daily card."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.core.content_dim import ContentDimension
from src.db.queries import get_training

logger = logging.getLogger("src.services.schedule_service")

STANDARD_INTERVALS: list[int] = [1, 3, 7, 15, 30]

_MAX_NEW_ITEMS_PER_DAY = 3
_DAY_BUCKETS = {"first_review": 1, "second_review": 3, "third_review": 7, "fourth_review": 15, "fifth_review": 30}


@dataclass
class TaskItem:
    task_id: str
    topic: str
    dimension: ContentDimension | None
    source: str
    is_required: bool


@dataclass
class TodayTasks:
    today: date
    review_items: list[TaskItem] = field(default_factory=list)
    new_items: list[TaskItem] = field(default_factory=list)
    recall_questions: list[Any] = field(default_factory=list)


def interval_for_index(idx: int) -> int:
    """Return the spaced-repetition interval for the given index.

    Indexes beyond the configured schedule fall back to the longest interval
    so units on day 30+ continue to use a 30-day cadence.
    """
    if idx < len(STANDARD_INTERVALS):
        return STANDARD_INTERVALS[idx]
    return STANDARD_INTERVALS[-1]


def next_review_date(last_reviewed: date, interval_index: int) -> date:
    """Return the next review date based on ``last_reviewed`` and index."""
    return last_reviewed + timedelta(days=interval_for_index(interval_index))


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


def _coerce_dimension(value: Any) -> ContentDimension | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    for member in ContentDimension:
        if member.english == raw or member.chinese == str(value).strip():
            return member
    return None


def _read_schedule_units(training: Any) -> list[dict[str, Any]]:
    schedule = training.schedule if isinstance(training.schedule, dict) else {}
    units = schedule.get("units")
    if not isinstance(units, list):
        return []
    return [u for u in units if isinstance(u, dict)]


def _placeholder_tasks(today: date) -> TodayTasks:
    return TodayTasks(
        today=today,
        new_items=[
            TaskItem(
                task_id="N1",
                topic="今日训练 (待初始化)",
                dimension=ContentDimension.CONCEPT,
                source="首次训练",
                is_required=True,
            )
        ],
    )


def extract_today_tasks(
    training_id: int,
    today: date | None = None,
) -> TodayTasks:
    """Return today's review + new tasks for the given training."""
    effective_today = today or date.today()
    training = get_training(training_id)
    if training is None:
        return _placeholder_tasks(effective_today)

    units = _read_schedule_units(training)
    review_items: list[TaskItem] = []
    new_items: list[TaskItem] = []

    for raw in units:
        name = str(raw.get("name") or raw.get("unit") or raw.get("topic") or "未命名单元")
        dimension = _coerce_dimension(raw.get("dimension"))
        review_count = int(raw.get("review_count") or 0)
        learned = _coerce_date(raw.get("learned_date") or raw.get("last_reviewed_date"))

        if review_count <= 0 or learned is None:
            if len(new_items) < _MAX_NEW_ITEMS_PER_DAY:
                index = len(new_items) + 1
                source = str(raw.get("source") or f"03_资料库.md §{index}")
                new_items.append(
                    TaskItem(
                        task_id=f"N{index}",
                        topic=name,
                        dimension=dimension,
                        source=source,
                        is_required=True,
                    )
                )
            continue

        interval_idx = max(review_count - 1, 0)
        due = learned + timedelta(days=interval_for_index(interval_idx))
        if due <= effective_today:
            index = len(review_items) + 1
            source = str(raw.get("source") or f"前次复习（第{review_count}次）")
            review_items.append(
                TaskItem(
                    task_id=f"R{index}",
                    topic=name,
                    dimension=dimension,
                    source=source,
                    is_required=True,
                )
            )

    if not review_items and not new_items:
        # 新流程不生成十份 md，`trainings.schedule` 是空的——退回从数据库里的训练项取今日任务
        from src.services import path_service

        # 训练项题型 → 内容维度（老流程只有 concept/read/write 三个维度）
        type_to_dimension = {
            "memory": "concept",
            "comprehension": "read",
            "practice": "write",
            "prerequisite": "concept",
        }
        db_tasks = path_service.today_tasks(training_id)
        if db_tasks["new"] or db_tasks["review"]:
            return TodayTasks(
                today=effective_today,
                new_items=[
                    TaskItem(
                        task_id=f"T{item.id}",
                        topic=item.title,
                        dimension=_coerce_dimension(type_to_dimension.get(item.item_type or "")),
                        source=item.knowledge_point or "训练路径",
                        is_required=True,
                    )
                    for item in db_tasks["new"]
                ],
                review_items=[
                    TaskItem(
                        task_id=f"T{item.id}",
                        topic=item.title,
                        dimension=_coerce_dimension(type_to_dimension.get(item.item_type or "")),
                        source=item.knowledge_point or "训练路径",
                        is_required=True,
                    )
                    for item in db_tasks["review"]
                ],
            )
        return _placeholder_tasks(effective_today)

    return TodayTasks(
        today=effective_today,
        review_items=review_items,
        new_items=new_items,
    )


__all__ = [
    "STANDARD_INTERVALS",
    "interval_for_index",
    "next_review_date",
    "extract_today_tasks",
    "TaskItem",
    "TodayTasks",
]
