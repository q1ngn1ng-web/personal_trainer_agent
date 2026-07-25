"""Pure-Python weekly metrics aggregated from ``daily_logs``.

No LLM calls live here — mechanical numbers only.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from src.db.queries import get_daily_logs_in_range
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.metrics_calculator")

DEFAULT_TOPIC: str = "(general)"

_MAX_MISSED_TASKS: int = 10
_WINDOW_DAYS: int = 7


@dataclass
class WeeklyMetrics:
    """Aggregated metrics for one training over the past 7 days."""

    training_id: int
    week_start: date
    week_end: date
    avg_completion: float = 0.0
    avg_recall_success: float = 0.0
    three_reflection_coverage: float = 0.0
    consecutive_days: int = 0
    weakest_topic: str | None = None
    strongest_topic: str | None = None
    missed_tasks: list[str] = field(default_factory=list)
    days_logged: int = 0

    def to_plain_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable plain dict."""
        payload = asdict(self)
        payload["week_start"] = self.week_start.isoformat()
        payload["week_end"] = self.week_end.isoformat()
        return payload

    def to_json(self) -> str:
        """Return a JSON-encoded string for archival."""
        return json.dumps(self.to_plain_dict(), ensure_ascii=False)


def _safe_mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _unit_rates_from_materials(materials: Any) -> dict[str, float] | None:
    """Return ``{unit_name: recall_rate}`` if ``materials.units[]`` has rates."""
    if not isinstance(materials, Mapping):
        return None
    units = materials.get("units")
    if not isinstance(units, list) or not units:
        return None
    rates: dict[str, float] = {}
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        name = unit.get("name") or unit.get("title")
        rate = unit.get("recall_rate")
        if name and isinstance(rate, (int, float)):
            rates[str(name)] = float(rate)
    return rates or None


def _unit_completion_from_daily_tasks(
    daily_log_ids: Iterable[int],
) -> dict[str, list[int]]:
    """Compute ``{task_ref: [completed_per_row,...]}`` from ``daily_log_tasks``."""
    conn = get_connection()
    try:
        ids = [int(i) for i in daily_log_ids]
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT task_ref, completed
                FROM daily_log_tasks
                WHERE daily_log_id IN ({placeholders})
                  AND task_ref IS NOT NULL""",
            ids,
        ).fetchall()
    finally:
        conn.close()
    bucket: dict[str, list[int]] = {}
    for row in rows:
        key = row["task_ref"]
        completed = 1 if int(row["completed"] or 0) > 0 else 0
        bucket.setdefault(key, []).append(completed)
    return bucket


def _min_max_topics(rates: dict[str, float]) -> tuple[str | None, str | None]:
    if not rates:
        return None, None
    weakest = min(rates, key=lambda k: rates[k])
    strongest = max(rates, key=lambda k: rates[k])
    if weakest == strongest:
        return weakest, None
    return weakest, strongest


def _consecutive_completed(
    training_id: int,
    today: date,
    week_start: date,
    week_end: date,
) -> int:
    """Longest streak ending at or before ``today`` with ``completed_count > 0``."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT log_date, completed_count
               FROM daily_logs
               WHERE training_id = ?
                 AND log_date <= ?
                 AND log_date >= ?
                 AND completed_count > 0
               ORDER BY log_date DESC""",
            (training_id, today.isoformat(), week_start.isoformat()),
        ).fetchall()
        raw_dates = [date.fromisoformat(row["log_date"]) for row in rows]
    finally:
        conn.close()
    if not raw_dates:
        return 0

    anchored = any(d == today for d in raw_dates)
    candidate = sorted({raw_dates[0]} | {today} if anchored else {today}, reverse=True)
    sequence = sorted(set(raw_dates), reverse=True)
    streak = 0
    cursor = today
    if cursor not in sequence:
        return 0
    for day in sequence:
        if day == cursor:
            streak += 1
            cursor = cursor - timedelta(days=1)
        else:
            break
    return streak


def _missed_task_ids(training_id: int, start: date, end: date) -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT t.id
               FROM daily_log_tasks t
               JOIN daily_logs d ON d.id = t.daily_log_id
               WHERE d.training_id = ?
                 AND d.log_date BETWEEN ? AND ?
                 AND t.is_required = 1
                 AND t.completed = 0
               ORDER BY d.log_date, t.id""",
            (training_id, start.isoformat(), end.isoformat()),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["id"]) for row in rows[:_MAX_MISSED_TASKS]]


def _resolve_training_id_and_window(
    training_id: int,
    today: date | None,
    week_start: date | None,
) -> tuple[int, date, date]:
    ref_today = today or date.today()
    if week_start is None:
        start = ref_today - timedelta(days=_WINDOW_DAYS - 1)
    else:
        start = week_start
    if start > ref_today:
        start = ref_today
    return training_id, start, ref_today


def compute_weekly_metrics(
    training_id: int,
    *,
    today: date | None = None,
    week_start: date | None = None,
) -> WeeklyMetrics:
    """Compute weekly metrics for ``training_id`` over the last 7 days.

    ``week_end`` defaults to ``today``; ``week_start`` defaults to ``today - 6``
    so the window is inclusive of 7 calendar days.
    """
    training_id, start, end = _resolve_training_id_and_window(
        training_id, today, week_start
    )
    logs = get_daily_logs_in_range(training_id, start, end)

    completion_rates: list[float] = []
    recall_rates: list[float] = []
    days_logged = 0
    reflected = 0
    for log in logs:
        days_logged += 1
        total = int(log.total_tasks or 0)
        completed = int(log.completed_count or 0)
        if total > 0:
            completion_rates.append(completed / total)
        rate = log.recall_success_rate
        if rate is not None:
            recall_rates.append(float(rate))
        if log.reflection_submitted_at:
            reflected += 1

    metrics = WeeklyMetrics(
        training_id=training_id,
        week_start=start,
        week_end=end,
        avg_completion=_safe_mean(completion_rates),
        avg_recall_success=_safe_mean(recall_rates),
        three_reflection_coverage=reflected / _WINDOW_DAYS,
        consecutive_days=_consecutive_completed(training_id, end, start, end),
        weakest_topic=None,
        strongest_topic=None,
        missed_tasks=_missed_task_ids(training_id, start, end),
        days_logged=days_logged,
    )

    material_rates = None
    training_row = _load_training_materials(training_id)
    if training_row is not None:
        material_rates = _unit_rates_from_materials(training_row)

    if material_rates is not None:
        weakest, strongest = _min_max_topics(material_rates)
        metrics.weakest_topic = weakest or DEFAULT_TOPIC
        if strongest:
            metrics.strongest_topic = strongest
    else:
        log_ids = [int(log.id) for log in logs if log.id is not None]
        if log_ids:
            completion_map = _unit_completion_from_daily_tasks(log_ids)
            if completion_map:
                rates = {
                    name: (sum(values) / len(values)) for name, values in completion_map.items()
                }
                weakest, strongest = _min_max_topics(rates)
                metrics.weakest_topic = weakest
                if strongest:
                    metrics.strongest_topic = strongest

    return metrics


def _load_training_materials(training_id: int) -> Any:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT materials FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    raw = row["materials"]
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.warning(
            "compute_weekly_metrics: could not parse materials for training=%s",
            training_id,
        )
        return None


__all__ = [
    "DEFAULT_TOPIC",
    "WeeklyMetrics",
    "compute_weekly_metrics",
]
