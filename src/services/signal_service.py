"""学习信号（四失）→ 动作。

对应 OpenSpec change ``training-execution-feedback`` 与 ADR-0015。三条硬约束：
LLM 只把自由文本分类成信号、动作由规则层决定；主观与客观冲突时以客观为主；
结构性调整每日最多一次且必须留痕。

说明：客观表现目前用**训练项状态**（passed / failed）作为代理；
等作答记录表建好后应换成准确率（已记入 `workspace/BACKLOG.md`）。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.models import AdjustmentLog, LearningSignal
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.signal_service")

#: 四类信号 → 动作方向（《学记》四失：多 / 寡 / 易 / 止）
SIGNAL_ACTIONS: dict[str, dict[str, str]] = {
    "too_much": {
        "label": "太多了",
        "diagnosis": "贪多嚼不烂",
        "direction": "收敛",
        "action": "reduce_load",
        "hint": "已降低单次训练量，知识点覆盖不变。",
    },
    "too_narrow": {
        "label": "太窄了",
        "diagnosis": "所知狭窄",
        "direction": "拓展",
        "action": "expand_scope",
        "hint": "已记下：后续会补充相邻知识点与更多角度。",
    },
    "too_easy": {
        "label": "太简单了",
        "diagnosis": "轻视以为易",
        "direction": "深挖",
        "action": "raise_difficulty",
        "hint": "已提高难度并加入变式。",
    },
    "too_hard": {
        "label": "太难了",
        "diagnosis": "畏难而止",
        "direction": "鼓励",
        "action": "lower_difficulty",
        "hint": "已降低难度、拆小步并给提示。",
    },
}

#: 触发结构性调整需要的同类信号次数；以及每日结构性调整上限
STRUCTURAL_THRESHOLD: int = 2
DAILY_STRUCTURAL_LIMIT: int = 1


@dataclass
class AdjustmentDecision:
    """一次信号处理的结果。"""

    signal_type: str
    direction: str
    action: str
    applied: bool
    blocked_reason: str = ""
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_prefix() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def objective_state(item_status: str | None) -> str:
    """客观表现的代理口径：已达标 = 表现好；未通过 = 表现差；其余 = 数据不足。"""
    if item_status == "passed":
        return "high"
    if item_status == "failed":
        return "low"
    return "unknown"


def decide(
    signal_type: str,
    *,
    objective: str,
    same_signal_today: int,
    structural_today: int,
) -> AdjustmentDecision:
    """冲突裁决 + 限频（纯函数，便于单测）。"""
    meta = SIGNAL_ACTIONS.get(signal_type)
    if meta is None:
        raise ValueError(f"unknown signal: {signal_type}")

    direction = meta["direction"]
    action = meta["action"]
    detail = {"objective": objective, "same_signal_today": same_signal_today}

    if signal_type == "too_easy" and objective == "low":
        return AdjustmentDecision(
            signal_type=signal_type,
            direction=direction,
            action="none",
            applied=False,
            blocked_reason="objective_conflict",
            message="你自评偏容易，但这个训练项还没通过。先巩固，暂时不提高难度。",
            detail=detail,
        )
    if signal_type == "too_hard" and objective == "high":
        return AdjustmentDecision(
            signal_type=signal_type,
            direction="减负",
            action="reduce_load",
            applied=True,
            message="这个训练项你已经通过了，难度不是问题——我先减少单次训练量。",
            detail=detail,
        )
    if objective == "unknown":
        return AdjustmentDecision(
            signal_type=signal_type,
            direction=direction,
            action="light_hint",
            applied=True,
            message=f"{meta['hint']}（还没有足够作答数据，先只做轻微调整）",
            detail=detail,
        )
    if same_signal_today + 1 < STRUCTURAL_THRESHOLD:
        return AdjustmentDecision(
            signal_type=signal_type,
            direction=direction,
            action="light_hint",
            applied=True,
            message=f"{meta['hint']}（同类信号当天再出现一次就会做结构性调整）",
            detail=detail,
        )
    if structural_today >= DAILY_STRUCTURAL_LIMIT:
        return AdjustmentDecision(
            signal_type=signal_type,
            direction=direction,
            action="none",
            applied=False,
            blocked_reason="daily_limit",
            message="今天已经调整过一次了，这条先记下来，明天生效。",
            detail=detail,
        )
    return AdjustmentDecision(
        signal_type=signal_type,
        direction=direction,
        action=action,
        applied=True,
        message=meta["hint"],
        detail=detail,
    )


def record_signal(
    training_id: int,
    signal_type: str,
    *,
    item_id: int | None = None,
    raw_text: str = "",
    confidence: float | None = None,
    conn: sqlite3.Connection | None = None,
) -> LearningSignal:
    """记录一条信号。"""
    if signal_type not in SIGNAL_ACTIONS:
        raise ValueError(f"unknown signal: {signal_type}")
    active = _connect(conn)
    own = conn is None
    try:
        cursor = active.execute(
            "INSERT INTO learning_signals (training_id, item_id, signal_type, raw_text, confidence, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (training_id, item_id, signal_type, raw_text or None, confidence, _now()),
        )
        if own:
            active.commit()
        row = active.execute(
            "SELECT * FROM learning_signals WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    finally:
        if own:
            active.close()
    return LearningSignal.from_row(row)


def _count_today(
    active: sqlite3.Connection, table: str, training_id: int, where: str = ""
) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table} WHERE training_id = ? AND created_at LIKE ?"
    params: list[Any] = [training_id, f"{_today_prefix()}%"]
    if where:
        sql += f" AND {where}"
    return int(active.execute(sql, params).fetchone()["n"])


def process_signal(
    training_id: int,
    signal_type: str,
    *,
    item_id: int | None = None,
    item_status: str | None = None,
    raw_text: str = "",
    conn: sqlite3.Connection | None = None,
) -> AdjustmentDecision:
    """记录信号 → 裁决 → 写调整日志（含被拦截的情形）。"""
    record_signal(training_id, signal_type, item_id=item_id, raw_text=raw_text, conn=conn)
    active = _connect(conn)
    own = conn is None
    try:
        same_today = (
            _count_today(
                active, "learning_signals", training_id, f"signal_type = '{signal_type}'"
            )
            - 1
        )
        structural_today = _count_today(
            active,
            "adjustment_log",
            training_id,
            "blocked = 0 AND action NOT IN ('light_hint', 'none')",
        )
    finally:
        if own:
            active.close()

    decision = decide(
        signal_type,
        objective=objective_state(item_status),
        same_signal_today=max(same_today, 0),
        structural_today=structural_today,
    )

    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "INSERT INTO adjustment_log (training_id, item_id, signal_type, action, reason, detail, "
            "blocked, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                training_id,
                item_id,
                signal_type,
                decision.action,
                decision.blocked_reason or "applied",
                json.dumps(decision.detail, ensure_ascii=False),
                0 if decision.applied else 1,
                _now(),
            ),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return decision


def list_signals(
    training_id: int, conn: sqlite3.Connection | None = None
) -> list[LearningSignal]:
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM learning_signals WHERE training_id = ? ORDER BY id DESC",
            (training_id,),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [LearningSignal.from_row(row) for row in rows]


def list_adjustments(
    training_id: int, conn: sqlite3.Connection | None = None
) -> list[AdjustmentLog]:
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM adjustment_log WHERE training_id = ? ORDER BY id DESC", (training_id,)
        ).fetchall()
    finally:
        if own:
            active.close()
    return [AdjustmentLog.from_row(row) for row in rows]


def signal_counts(training_id: int, conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """信号分布（周复盘用）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT signal_type, COUNT(*) AS n FROM learning_signals WHERE training_id = ? "
            "GROUP BY signal_type",
            (training_id,),
        ).fetchall()
    finally:
        if own:
            active.close()
    counts = {key: 0 for key in SIGNAL_ACTIONS}
    for row in rows:
        counts[str(row["signal_type"])] = int(row["n"])
    return counts


__all__ = [
    "DAILY_STRUCTURAL_LIMIT",
    "SIGNAL_ACTIONS",
    "STRUCTURAL_THRESHOLD",
    "AdjustmentDecision",
    "decide",
    "list_adjustments",
    "list_signals",
    "objective_state",
    "process_signal",
    "record_signal",
    "signal_counts",
]
