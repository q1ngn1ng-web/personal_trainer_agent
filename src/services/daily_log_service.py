"""Writes for the daily card: task checks, three reflections, recall results."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from src.db.queries import (
    get_or_create_daily_log,
    update_daily_log_progress,
    update_training,
)
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.daily_log_service")


@dataclass
class TaskCheckResult:
    task_id: str
    completed: bool
    completed_at: datetime


@dataclass
class ReflectionResult:
    submitted_at: datetime
    reflections: dict


@dataclass
class DailyProgress:
    log_id: int
    total_tasks: int
    completed_count: int
    recall_questions_total: int
    recall_questions_correct: int
    recall_success_rate: float | None
    reflection_submitted_at: str | None
    is_required_tasks: list[dict[str, Any]] = field(default_factory=list)


def _today_or(value: date | None) -> date:
    return value or date.today()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_type_for(task_id: str) -> str:
    head = task_id[:1].upper() if task_id else "N"
    return {"R": "review", "N": "new"}.get(head, "new")


def _read_tasks(daily_log_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, task_type, task_ref, completed, completed_at, is_required
               FROM daily_log_tasks WHERE daily_log_id = ?""",
            (daily_log_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _upsert_task(
    daily_log_id: int,
    task_id: str,
    completed: bool,
    completed_at_iso: str,
) -> None:
    completed_int = 1 if completed else 0
    completed_at_value: str | None = completed_at_iso if completed else None
    task_type = _task_type_for(task_id)
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM daily_log_tasks WHERE daily_log_id = ? AND task_ref = ?",
            (daily_log_id, task_id),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE daily_log_tasks SET completed = ?, completed_at = ? WHERE id = ?",
                (completed_int, completed_at_value, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO daily_log_tasks
                   (daily_log_id, task_type, task_ref, completed, completed_at, is_required)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (daily_log_id, task_type, task_id, completed_int, completed_at_value),
            )
        conn.commit()


def check_task(
    training_id: int,
    task_id: str,
    completed: bool = True,
    *,
    today: date | None = None,
) -> TaskCheckResult:
    """Toggle a (review/new) task for today and persist progress."""
    log_date = _today_or(today)
    log = get_or_create_daily_log(training_id, log_date)
    completed_at_iso = _now_iso()
    _upsert_task(log.id, task_id, completed, completed_at_iso)

    tasks = _read_tasks(log.id)
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("completed"))
    recall_total = int(log.recall_questions_total or 0)
    recall_correct = int(log.recall_questions_correct or 0)

    update_daily_log_progress(
        log.id,
        completed_count=done,
        total_tasks=total,
        recall_correct=recall_correct,
        recall_total=recall_total,
    )
    update_training(training_id, last_active_at=completed_at_iso)

    return TaskCheckResult(
        task_id=task_id,
        completed=completed,
        completed_at=datetime.fromisoformat(completed_at_iso),
    )


def _bump_last_active(training_id: int, iso_now: str) -> None:
    update_training(training_id, last_active_at=iso_now)


def submit_reflections(
    training_id: int,
    loyal_to_goal: str,
    method_effective: str,
    applied_to_practice: str,
    *,
    today: date | None = None,
) -> ReflectionResult:
    """Persist the three daily reflections for today."""
    from src.db.queries import submit_three_reflections

    log_date = _today_or(today)
    log = get_or_create_daily_log(training_id, log_date)
    reflections = {
        "loyal_to_goal": loyal_to_goal,
        "method_effective": method_effective,
        "applied_to_practice": applied_to_practice,
    }
    updated = submit_three_reflections(log.id, json.dumps(reflections, ensure_ascii=False))
    iso_now = _now_iso()
    _bump_last_active(training_id, iso_now)

    submitted_iso = getattr(updated, "reflection_submitted_at", None) if updated is not None else None
    if submitted_iso:
        submitted_at = datetime.fromisoformat(submitted_iso)
    else:
        submitted_at = datetime.now(timezone.utc)
    return ReflectionResult(submitted_at=submitted_at, reflections=reflections)


def record_recall_results(
    training_id: int,
    results: dict[str, bool],
    *,
    today: date | None = None,
) -> None:
    """Append today's recall grading results to the daily log counters."""
    log_date = _today_or(today)
    log = get_or_create_daily_log(training_id, log_date)
    existing_total = int(log.recall_questions_total or 0)
    existing_correct = int(log.recall_questions_correct or 0)
    added_total = len(results)
    added_correct = sum(1 for value in results.values() if value)
    new_total = existing_total + added_total
    new_correct = existing_correct + added_correct
    completed_count = int(log.completed_count or 0)
    total_tasks = int(log.total_tasks or 0)
    update_daily_log_progress(
        log.id,
        completed_count=completed_count,
        total_tasks=total_tasks,
        recall_correct=new_correct,
        recall_total=new_total,
    )
    _bump_last_active(training_id, _now_iso())


def get_today_progress(
    training_id: int,
    today: date | None = None,
) -> DailyProgress:
    """Return the current daily-log snapshot used by the UI."""
    log_date = _today_or(today)
    log = get_or_create_daily_log(training_id, log_date)
    tasks = _read_tasks(log.id)
    return DailyProgress(
        log_id=log.id,
        total_tasks=len(tasks),
        completed_count=sum(1 for t in tasks if t.get("completed")),
        recall_questions_total=int(log.recall_questions_total or 0),
        recall_questions_correct=int(log.recall_questions_correct or 0),
        recall_success_rate=log.recall_success_rate,
        reflection_submitted_at=getattr(log, "reflection_submitted_at", None),
        is_required_tasks=tasks,
    )


__all__ = [
    "check_task",
    "submit_reflections",
    "record_recall_results",
    "get_today_progress",
    "TaskCheckResult",
    "ReflectionResult",
    "DailyProgress",
]
