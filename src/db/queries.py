from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from src.db.models import BaselineHistory, DailyLog, LLMCall, ReviewArchive, Training
from src.db.sqlite import get_connection

logger = logging.getLogger("src.db.queries")
_TRAINING_STATUSES = {
    "created",
    "draft",
    "pending_confirm",
    "confirmed",
    "active",
    "paused",
    "archived",
    "failed",
}
_JSON_TRAINING_FIELDS = {
    "goal_json",
    "keywords",
    "forbidden",
    "targets",
    "review_items",
    "pretrain_checklist",
    "schedule",
    "materials",
}
_TRAINING_FIELDS = {
    "topic",
    "status",
    "goal_json",
    "goal_confirmed_at",
    "clarification_rounds",
    "keywords",
    "must_cover_count",
    "forbidden",
    "directory",
    "baseline_score",
    "baseline_level",
    "targets",
    "review_items",
    "pretrain_checklist",
    "schedule",
    "materials",
    "current_week",
    "last_review_at",
    "created_at",
    "last_active_at",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def _connection(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    owned = conn is None
    active = conn or get_connection()
    try:
        yield active
        active.commit()
    except Exception:
        active.rollback()
        raise
    finally:
        if owned:
            active.close()


def create_training(conn: sqlite3.Connection | None = None, **fields: Any) -> Training:
    """Create and return a training."""
    if "topic" not in fields:
        raise ValueError("topic is required")
    fields.setdefault("created_at", _now())
    unknown = set(fields) - _TRAINING_FIELDS
    if unknown:
        raise ValueError(f"Unsupported training fields: {sorted(unknown)}")
    for name in _JSON_TRAINING_FIELDS & fields.keys():
        fields[name] = _json(fields[name])
    columns = list(fields)
    placeholders = ", ".join("?" for _ in columns)
    with _connection(conn) as active:
        cursor = active.execute(
            f"INSERT INTO trainings ({', '.join(columns)}) VALUES ({placeholders})",
            [fields[column] for column in columns],
        )
        row = active.execute("SELECT * FROM trainings WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return Training.from_row(row)


def get_training(id: int, conn: sqlite3.Connection | None = None) -> Training | None:
    """Return a training by identifier."""
    with _connection(conn) as active:
        row = active.execute("SELECT * FROM trainings WHERE id = ?", (id,)).fetchone()
    return Training.from_row(row) if row else None


def list_trainings(
    status: str | None = None,
    order_by_last_active: bool = True,
    conn: sqlite3.Connection | None = None,
) -> list[Training]:
    """List trainings, optionally filtered by status."""
    sql = "SELECT * FROM trainings"
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY last_active_at DESC, created_at DESC" if order_by_last_active else " ORDER BY id"
    with _connection(conn) as active:
        rows = active.execute(sql, params).fetchall()
    return [Training.from_row(row) for row in rows]


def update_training(id: int, conn: sqlite3.Connection | None = None, **fields: Any) -> Training | None:
    """Update allowed training fields and return the updated training."""
    if not fields:
        return get_training(id, conn)
    unknown = set(fields) - _TRAINING_FIELDS
    if unknown:
        raise ValueError(f"Unsupported training fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in _TRAINING_STATUSES:
        raise ValueError(f"Invalid training status: {fields['status']}")
    for name in _JSON_TRAINING_FIELDS & fields.keys():
        fields[name] = _json(fields[name])
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with _connection(conn) as active:
        active.execute(
            f"UPDATE trainings SET {assignments} WHERE id = ?",
            [*fields.values(), id],
        )
        row = active.execute("SELECT * FROM trainings WHERE id = ?", (id,)).fetchone()
    return Training.from_row(row) if row else None


def set_training_status(id: int, status: str, conn: sqlite3.Connection | None = None) -> Training | None:
    """Set a validated training status."""
    if status not in _TRAINING_STATUSES:
        raise ValueError(f"Invalid training status: {status}")
    return update_training(id, conn=conn, status=status, last_active_at=_now())


#: 删除训练时要一并清理的子表（按外键依赖顺序，先删孙子再删子）
_TRAINING_CASCADE: tuple[str, ...] = (
    "DELETE FROM daily_log_tasks WHERE daily_log_id IN "
    "(SELECT id FROM daily_logs WHERE training_id = ?)",
    "DELETE FROM daily_logs WHERE training_id = ?",
    "DELETE FROM training_items WHERE stage_id IN "
    "(SELECT id FROM path_stages WHERE path_id IN "
    "(SELECT id FROM training_paths WHERE training_id = ?))",
    "DELETE FROM path_stages WHERE path_id IN "
    "(SELECT id FROM training_paths WHERE training_id = ?)",
    "DELETE FROM training_paths WHERE training_id = ?",
    "DELETE FROM edge_assessments WHERE training_id = ?",
    "DELETE FROM source_chunks WHERE source_id IN (SELECT id FROM sources WHERE training_id = ?)",
    "DELETE FROM sources WHERE training_id = ?",
    "DELETE FROM learning_signals WHERE training_id = ?",
    "DELETE FROM adjustment_log WHERE training_id = ?",
    "DELETE FROM plan_items WHERE training_id = ?",
    "DELETE FROM question_bank WHERE training_id = ?",
    "DELETE FROM baseline_history WHERE training_id = ?",
    "DELETE FROM review_archives WHERE training_id = ?",
    "DELETE FROM llm_calls WHERE training_id = ?",
)


def delete_training(id: int, conn: sqlite3.Connection | None = None) -> bool:
    """彻底删除一个训练及其全部关联数据。

    **不可恢复**。调用方必须先做二次确认。
    返回是否真的删掉了训练行。
    """
    with _connection(conn) as active:
        for statement in _TRAINING_CASCADE:
            active.execute(statement, (id,))
        cursor = active.execute("DELETE FROM trainings WHERE id = ?", (id,))
        deleted = cursor.rowcount > 0
    return deleted


def get_or_create_daily_log(
    training_id: int,
    log_date: str | date,
    conn: sqlite3.Connection | None = None,
) -> DailyLog:
    """Return the daily log for a date, creating it when absent."""
    date_value = log_date.isoformat() if isinstance(log_date, date) else log_date
    with _connection(conn) as active:
        active.execute(
            "INSERT OR IGNORE INTO daily_logs (training_id, log_date, created_at) VALUES (?, ?, ?)",
            (training_id, date_value, _now()),
        )
        row = active.execute(
            "SELECT * FROM daily_logs WHERE training_id = ? AND log_date = ?",
            (training_id, date_value),
        ).fetchone()
    return DailyLog.from_row(row)


def update_daily_log_progress(
    log_id: int,
    completed_count: int,
    total_tasks: int,
    recall_correct: int,
    recall_total: int,
    conn: sqlite3.Connection | None = None,
) -> DailyLog | None:
    """Update task and recall progress for a daily log."""
    rate = recall_correct / recall_total if recall_total else None
    with _connection(conn) as active:
        active.execute(
            """UPDATE daily_logs
               SET completed_count = ?, total_tasks = ?, recall_questions_correct = ?,
                   recall_questions_total = ?, recall_success_rate = ?
               WHERE id = ?""",
            (completed_count, total_tasks, recall_correct, recall_total, rate, log_id),
        )
        row = active.execute("SELECT * FROM daily_logs WHERE id = ?", (log_id,)).fetchone()
    return DailyLog.from_row(row) if row else None


def submit_three_reflections(
    log_id: int,
    reflections_json: Any,
    conn: sqlite3.Connection | None = None,
) -> DailyLog | None:
    """Store the structured three-reflections submission."""
    with _connection(conn) as active:
        active.execute(
            "UPDATE daily_logs SET three_reflections = ?, reflection_submitted_at = ? WHERE id = ?",
            (_json(reflections_json), _now(), log_id),
        )
        row = active.execute("SELECT * FROM daily_logs WHERE id = ?", (log_id,)).fetchone()
    return DailyLog.from_row(row) if row else None


def get_daily_logs_in_range(
    training_id: int,
    start_date: str | date,
    end_date: str | date,
    conn: sqlite3.Connection | None = None,
) -> list[DailyLog]:
    """Return daily logs in an inclusive date range."""
    start = start_date.isoformat() if isinstance(start_date, date) else start_date
    end = end_date.isoformat() if isinstance(end_date, date) else end_date
    with _connection(conn) as active:
        rows = active.execute(
            "SELECT * FROM daily_logs WHERE training_id = ? AND log_date BETWEEN ? AND ? ORDER BY log_date",
            (training_id, start, end),
        ).fetchall()
    return [DailyLog.from_row(row) for row in rows]


def add_baseline_history(
    training_id: int,
    score: float,
    dimension_scores_json: Any,
    conn: sqlite3.Connection | None = None,
) -> BaselineHistory:
    """Add a baseline score snapshot."""
    with _connection(conn) as active:
        cursor = active.execute(
            "INSERT INTO baseline_history (training_id, baseline_score, dimension_scores, recorded_at) VALUES (?, ?, ?, ?)",
            (training_id, score, _json(dimension_scores_json), _now()),
        )
        row = active.execute("SELECT * FROM baseline_history WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return BaselineHistory.from_row(row)


def record_llm_call(conn: sqlite3.Connection | None = None, **fields: Any) -> int:
    """Record an LLM invocation and return its inserted identifier."""
    required = {
        "call_purpose",
        "prompt_name",
        "prompt_version",
        "model",
        "input_text",
        "latency_ms",
        "tokens_in",
        "tokens_out",
    }
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"Missing LLM call fields: {sorted(missing)}")
    fields.setdefault("retry_count", 0)
    fields.setdefault("fallback_used", 0)
    fields.setdefault("created_at", _now())
    if "output_json" in fields:
        fields["output_json"] = _json(fields["output_json"])
    allowed = required | {
        "training_id",
        "output_text",
        "output_json",
        "validation_result",
        "retry_count",
        "failure_reason",
        "fallback_used",
        "created_at",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unsupported LLM call fields: {sorted(unknown)}")
    columns = list(fields)
    placeholders = ", ".join("?" for _ in columns)
    with _connection(conn) as active:
        cursor = active.execute(
            f"INSERT INTO llm_calls ({', '.join(columns)}) VALUES ({placeholders})",
            [fields[column] for column in columns],
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an inserted LLM call id")
        call_id = cursor.lastrowid
    return call_id


def get_calls_by_purpose(
    call_purpose: str,
    conn: sqlite3.Connection | None = None,
) -> list[LLMCall]:
    """Return LLM calls with a matching purpose."""
    with _connection(conn) as active:
        rows = active.execute(
            "SELECT * FROM llm_calls WHERE call_purpose = ? ORDER BY created_at DESC, id DESC",
            (call_purpose,),
        ).fetchall()
    return [LLMCall.from_row(row) for row in rows]


def get_calls_by_prompt_version(
    prompt_name: str,
    version: str,
    conn: sqlite3.Connection | None = None,
) -> list[LLMCall]:
    """Return calls for a prompt name and version."""
    with _connection(conn) as active:
        rows = active.execute(
            "SELECT * FROM llm_calls WHERE prompt_name = ? AND prompt_version = ? ORDER BY created_at DESC, id DESC",
            (prompt_name, version),
        ).fetchall()
    return [LLMCall.from_row(row) for row in rows]


def get_success_rate_by_prompt_version(
    conn: sqlite3.Connection | None = None,
) -> dict[str, dict[str, float]]:
    """Return validation pass rates grouped by prompt name and version."""
    with _connection(conn) as active:
        rows = active.execute(
            """SELECT prompt_name, prompt_version,
                      AVG(CASE WHEN validation_result = 'pass' THEN 1.0 ELSE 0.0 END) AS success_rate
               FROM llm_calls GROUP BY prompt_name, prompt_version"""
        ).fetchall()
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        result.setdefault(row["prompt_name"], {})[row["prompt_version"]] = float(row["success_rate"])
    return result


def get_avg_latency_by_model(conn: sqlite3.Connection | None = None) -> dict[str, float]:
    """Return average latency in milliseconds grouped by model."""
    with _connection(conn) as active:
        rows = active.execute("SELECT model, AVG(latency_ms) AS average FROM llm_calls GROUP BY model").fetchall()
    return {row["model"]: float(row["average"]) for row in rows}


def create_review_archive(
    training_id: int,
    week_start: str | date,
    metrics: Any,
    llm_suggestions: Any,
    user_action: str,
    conn: sqlite3.Connection | None = None,
) -> ReviewArchive:
    """Create a weekly review archive."""
    week = week_start.isoformat() if isinstance(week_start, date) else week_start
    with _connection(conn) as active:
        cursor = active.execute(
            """INSERT INTO review_archives
               (training_id, week_start, metrics, llm_suggestions, user_action, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (training_id, week, _json(metrics), _json(llm_suggestions), user_action, _now()),
        )
        row = active.execute("SELECT * FROM review_archives WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return ReviewArchive.from_row(row)


def get_reviews_by_training(
    training_id: int,
    conn: sqlite3.Connection | None = None,
) -> list[ReviewArchive]:
    """Return a training's weekly reviews newest first."""
    with _connection(conn) as active:
        rows = active.execute(
            "SELECT * FROM review_archives WHERE training_id = ? ORDER BY week_start DESC, id DESC",
            (training_id,),
        ).fetchall()
    return [ReviewArchive.from_row(row) for row in rows]
