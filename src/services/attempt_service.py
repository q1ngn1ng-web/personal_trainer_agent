"""作答记录服务：写入逐次作答、算准确率、判达标、给客观通道供数。

对应 change ``training-execution-feedback`` 的任务 1.3 的"日常作答"部分与 5.1 的达标判定，
以及 ADR-0015 的客观通道。**它是 M1（四失无闭环）的数据前提**：
没有逐次作答，``signal_service`` 的客观一侧永远只能是 "数据不足"。
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from src.core.mastery import MASTERY_STREAK, MasteryState, evaluate, objective_state
from src.core.plan import local_today
from src.db.models import PracticeAttempt
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.attempt_service")

#: 参与客观计算的最近作答条数
ATTEMPT_WINDOW: int = 5

VALID_RESULTS: tuple[str, ...] = ("pass", "fail")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def record_attempt(
    training_id: int,
    item_key: str,
    result: str,
    *,
    plan_id: int | None = None,
    round_index: int | None = None,
    source: str = "self",
    note: str = "",
    conn: sqlite3.Connection | None = None,
) -> PracticeAttempt:
    """记录一次作答。``result`` 只接受 ``pass`` / ``fail``（对 / 错）。"""
    if result not in VALID_RESULTS:
        raise ValueError(f"invalid attempt result: {result!r}")
    if not str(item_key or "").strip():
        raise ValueError("attempt 必须带题目键（item_key）")
    active = _connect(conn)
    own = conn is None
    try:
        cursor = active.execute(
            "INSERT INTO practice_attempts (training_id, item_key, plan_id, round_index, result, "
            "source, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(training_id),
                str(item_key),
                plan_id,
                round_index,
                result,
                source,
                note or None,
                _now(),
            ),
        )
        if own:
            active.commit()
        row = active.execute(
            "SELECT * FROM practice_attempts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    finally:
        if own:
            active.close()
    return PracticeAttempt.from_row(row)


def recent_results(
    training_id: int,
    item_key: str,
    *,
    window: int = ATTEMPT_WINDOW,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """某题目最近 ``window`` 次作答的结果（时间正序）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT result FROM practice_attempts WHERE training_id = ? AND item_key = ? "
            "ORDER BY id DESC LIMIT ?",
            (int(training_id), str(item_key), int(window)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [str(row["result"]) for row in reversed(rows)]


def item_mastery(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> MasteryState:
    """某个题目的客观表现与达标判定（连续 ``MASTERY_STREAK`` 次通过 = 达标）。"""
    return evaluate(recent_results(training_id, item_key, conn=conn))


def training_accuracy(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> tuple[float | None, int]:
    """整个训练的（准确率, 作答次数），用于首页/复盘展示。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT result FROM practice_attempts WHERE training_id = ?", (int(training_id),)
        ).fetchall()
    finally:
        if own:
            active.close()
    values = [str(row["result"]) for row in rows]
    state = evaluate(values)
    return state.accuracy, state.attempts


def objective_for_item(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> str:
    """给 ``signal_service`` 用的客观口径（ADR-0015：<3 次作答算数据不足）。"""
    return objective_state(recent_results(training_id, item_key, conn=conn))


def recent_training_results(
    training_id: int, *, window: int = ATTEMPT_WINDOW, conn: sqlite3.Connection | None = None
) -> list[str]:
    """整个训练最近 ``window`` 次作答（四失是"这次练完"的整体感受，按训练口径更贴切）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT result FROM practice_attempts WHERE training_id = ? ORDER BY id DESC LIMIT ?",
            (int(training_id), int(window)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [str(row["result"]) for row in reversed(rows)]


def objective_for_training(
    training_id: int, *, window: int = ATTEMPT_WINDOW, conn: sqlite3.Connection | None = None
) -> str:
    """训练级的客观口径：近 ``window`` 次作答的准确率 → ``low`` / ``mid`` / ``high`` / ``unknown``。"""
    return objective_state(recent_training_results(training_id, window=window, conn=conn))


def mark_mastered_if_ready(
    training_id: int,
    item_key: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """连续达标 → 把训练项写成 ``passed``（唯一的"达标"写入点）。返回是否刚刚达标。"""
    state = item_mastery(training_id, item_key, conn=conn)
    if not state.mastered:
        return False
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT i.id, i.status FROM training_items i "
            "JOIN path_stages s ON s.id = i.stage_id "
            "JOIN training_paths p ON p.id = s.path_id "
            "WHERE p.training_id = ? AND i.item_key = ? "
            "ORDER BY (p.status = 'confirmed') DESC, p.version DESC LIMIT 1",
            (int(training_id), str(item_key)),
        ).fetchone()
        if row is None or str(row["status"]) == "passed":
            return False
        active.execute(
            "UPDATE training_items SET status = 'passed', mastered_at = ? WHERE id = ?",
            (_now(), int(row["id"])),
        )
        if own:
            active.commit()
        logger.info(
            "mark_mastered_if_ready: training %s item %s 连续 %d 次通过 → 达标",
            training_id,
            item_key,
            state.streak,
        )
        return True
    finally:
        if own:
            active.close()


def record_and_evaluate(
    training_id: int,
    item_key: str,
    result: str,
    *,
    plan_id: int | None = None,
    round_index: int | None = None,
    source: str = "self",
    conn: sqlite3.Connection | None = None,
) -> tuple[PracticeAttempt, bool]:
    """记录作答并顺带做达标判定（返回 记录 + 是否刚刚达标）。"""
    attempt = record_attempt(
        training_id,
        item_key,
        result,
        plan_id=plan_id,
        round_index=round_index,
        source=source,
        conn=conn,
    )
    mastered = mark_mastered_if_ready(training_id, item_key, conn=conn)
    return attempt, mastered


def attempts_for_training(
    training_id: int, *, limit: int = 200, conn: sqlite3.Connection | None = None
) -> list[PracticeAttempt]:
    """列出作答记录（复盘与调试用）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM practice_attempts WHERE training_id = ? ORDER BY id DESC LIMIT ?",
            (int(training_id), int(limit)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [PracticeAttempt.from_row(row) for row in rows]


__all__ = [
    "ATTEMPT_WINDOW",
    "MASTERY_STREAK",
    "VALID_RESULTS",
    "attempts_for_training",
    "item_mastery",
    "mark_mastered_if_ready",
    "objective_for_item",
    "objective_for_training",
    "recent_results",
    "recent_training_results",
    "record_and_evaluate",
    "record_attempt",
    "training_accuracy",
]
