"""Read-only progress metrics powering the trainer dashboard.

All queries are pure-SQLite and never mutate state; the dashboard pages
in ``src/ui/`` read exclusively from the dataclasses exposed here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.core.baseline import compute_level
from src.core.element import BaselineLevel, TrainingStatus
from src.db.queries import get_daily_logs_in_range, get_training, list_trainings
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.progress_service")

_STREAK_WINDOW_DAYS: int = 30
_P1_MIN_DAYS: int = 14
_RECALL_WINDOW_DAYS: int = 7


@dataclass
class TrainingProgress:
    """Real-time P0 snapshot for one training."""

    training_id: int
    topic: str
    status: TrainingStatus
    baseline_score: float
    baseline_level: BaselineLevel
    consecutive_days: int
    days_since_creation: int
    today_completion: float
    today_completed: int
    today_total: int
    last_active_at: datetime | None
    current_week: int


@dataclass
class HomeDashboard:
    """Aggregated home-page snapshot."""

    trainings: list[TrainingProgress] = field(default_factory=list)
    total_active: int = 0
    total_all: int = 0
    avg_baseline: float | None = None


@dataclass
class P1Summary:
    """Secondary metrics, unlocked after two weeks of training."""

    has_enough_data: bool
    baseline_history_points: list[dict[str, Any]] = field(default_factory=list)
    recall_rates: list[dict[str, Any]] = field(default_factory=list)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Could not parse datetime: %r", text)
        return None


def _to_date(value: Any) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt is not None else None


def _coerce_status(value: str | None) -> TrainingStatus:
    if not value:
        return TrainingStatus.CREATED
    try:
        return TrainingStatus(value)
    except ValueError:
        logger.warning("Unknown training status %r, falling back to CREATED", value)
        return TrainingStatus.CREATED


def _coerce_level(value: str | None, score: float) -> BaselineLevel:
    if value:
        try:
            return BaselineLevel(value)
        except ValueError:
            logger.warning("Unknown baseline level %r, recomputing from score", value)
    return compute_level(score)


def _today_progress(training_id: int, today: date) -> tuple[int, int]:
    """Return ``(completed_count, total_tasks)`` for ``today``'s daily log."""
    logs = get_daily_logs_in_range(training_id, today, today)
    if not logs:
        return 0, 0
    log = logs[0]
    return int(log.completed_count or 0), int(log.total_tasks or 0)


def _consecutive_days(training_id: int, today: date) -> int:
    """Longest streak of completed days ending at or before ``today``."""
    window_start = today - timedelta(days=_STREAK_WINDOW_DAYS - 1)
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT log_date FROM daily_logs
               WHERE training_id = ?
                 AND log_date BETWEEN ? AND ?
                 AND completed_count > 0
               ORDER BY log_date DESC""",
            (
                training_id,
                window_start.isoformat(),
                today.isoformat(),
            ),
        ).fetchall()
    finally:
        conn.close()
    completed = sorted(
        {
            date.fromisoformat(row["log_date"])
            for row in rows
            if row["log_date"] <= today.isoformat()
        },
        reverse=True,
    )
    if not completed:
        return 0
    anchor = completed[0]
    streak = 0
    cursor = anchor
    for current in completed:
        if current == cursor:
            streak += 1
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def _empty_progress(training_id: int) -> TrainingProgress:
    return TrainingProgress(
        training_id=training_id,
        topic="",
        status=TrainingStatus.CREATED,
        baseline_score=0.0,
        baseline_level=BaselineLevel.LOW,
        consecutive_days=0,
        days_since_creation=0,
        today_completion=0.0,
        today_completed=0,
        today_total=0,
        last_active_at=None,
        current_week=1,
    )


def compute_training_progress(
    training_id: int,
    *,
    today: date | None = None,
) -> TrainingProgress:
    """Compute the P0 progress snapshot for one training."""
    ref_today = today or date.today()
    training = get_training(training_id)
    if training is None:
        logger.info("compute_training_progress: training %s not found", training_id)
        return _empty_progress(training_id)

    completed, total = _today_progress(training_id, ref_today)
    today_completion = completed / total if total > 0 else 0.0

    created_date = _to_date(training.created_at)
    days_since = max((ref_today - created_date).days, 0) if created_date else 0

    baseline_score = float(training.baseline_score or 0.0)

    return TrainingProgress(
        training_id=int(training.id),
        topic=str(training.topic or ""),
        status=_coerce_status(training.status),
        baseline_score=baseline_score,
        baseline_level=_coerce_level(training.baseline_level, baseline_score),
        consecutive_days=_consecutive_days(training_id, ref_today),
        days_since_creation=days_since,
        today_completion=today_completion,
        today_completed=completed,
        today_total=total,
        last_active_at=_parse_dt(training.last_active_at),
        current_week=int(training.current_week or 1),
    )


def compute_home_dashboard(*, today: date | None = None) -> HomeDashboard:
    """Aggregate the home-page snapshot across all trainings."""
    ref_today = today or date.today()
    trainings = list_trainings()
    if not trainings:
        return HomeDashboard()

    progress_list: list[TrainingProgress] = []
    active_scores: list[float] = []
    for training in trainings:
        progress = compute_training_progress(int(training.id), today=ref_today)
        progress_list.append(progress)
        if progress.status == TrainingStatus.ACTIVE:
            active_scores.append(progress.baseline_score)

    return HomeDashboard(
        trainings=progress_list,
        total_active=sum(1 for p in progress_list if p.status == TrainingStatus.ACTIVE),
        total_all=len(progress_list),
        avg_baseline=(
            sum(active_scores) / len(active_scores) if active_scores else None
        ),
    )


def _baseline_history_points(training_id: int) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT recorded_at, baseline_score
               FROM baseline_history
               WHERE training_id = ?
               ORDER BY recorded_at""",
            (training_id,),
        ).fetchall()
    finally:
        conn.close()
    points: list[dict[str, Any]] = []
    for row in rows:
        recorded = _parse_dt(row["recorded_at"])
        if recorded is None:
            continue
        points.append(
            {
                "date": recorded.date().isoformat(),
                "score": float(row["baseline_score"]),
            }
        )
    return points


def _recent_recall_rates(training_id: int, today: date) -> list[dict[str, Any]]:
    window_start = today - timedelta(days=_RECALL_WINDOW_DAYS - 1)
    logs = get_daily_logs_in_range(training_id, window_start, today)
    rates: list[dict[str, Any]] = []
    for log in logs:
        if log.recall_success_rate is None:
            continue
        rates.append(
            {
                "date": str(log.log_date),
                "rate": float(log.recall_success_rate),
            }
        )
    return rates


def get_p1_summary(training_id: int) -> P1Summary:
    """Return P1 secondary metrics for a training.

    When ``has_enough_data`` is False, the point lists are empty and the
    caller should render a placeholder.
    """
    training = get_training(training_id)
    if training is None:
        return P1Summary(has_enough_data=False)

    created = _to_date(training.created_at)
    if not created:
        return P1Summary(has_enough_data=False)

    days_running = (date.today() - created).days
    if days_running < _P1_MIN_DAYS:
        return P1Summary(has_enough_data=False)

    return P1Summary(
        has_enough_data=True,
        baseline_history_points=_baseline_history_points(training_id),
        recall_rates=_recent_recall_rates(training_id, date.today()),
    )


__all__ = [
    "TrainingProgress",
    "HomeDashboard",
    "P1Summary",
    "compute_training_progress",
    "compute_home_dashboard",
    "get_p1_summary",
]