"""题目侧服务：生成结果校验 + 要点清单落库。

对应 OpenSpec change ``learner-memory-and-grading`` 的任务 3.1—3.3。

核心约束：**要点清单随题固化**——出题时就生成并落库，判分时只读不生成；
选择题的干扰项 MUST 能在资料片段中找到依据，否则题目可以被排除法做出来。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping, Sequence

from src.db.sqlite import get_connection as _connect
from src.services.grading_service import QUESTION_TYPES, normalize_text

logger = logging.getLogger("src.services.question_service")

#: 主观题至少要有几条要点，否则判分失去区分度
MIN_QA_POINTS: int = 3
#: 选择题至少几个选项
MIN_CHOICE_OPTIONS: int = 3


def validate_generated_question(
    payload: Mapping[str, Any], *, source_text: str | None = None
) -> list[str]:
    """校验出题结果，返回问题列表（空列表 = 通过）。

    ``source_text`` 传入题目所属的资料片段原文时，会额外校验选择题干扰项的可溯源性。
    """
    problems: list[str] = []
    question_type = str(payload.get("question_type") or "")
    if question_type not in QUESTION_TYPES:
        problems.append(f"题型非法：{question_type!r}")

    points = list(payload.get("points") or [])
    ids: set[str] = set()
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            problems.append(f"第 {index + 1} 条要点不是对象")
            continue
        pid = str(point.get("point_id") or "")
        if not pid:
            problems.append(f"第 {index + 1} 条要点缺少 point_id")
        elif pid in ids:
            problems.append(f"要点 id 重复：{pid}")
        ids.add(pid)
        if not str(point.get("text") or "").strip():
            problems.append(f"要点 {pid or index + 1} 缺少正文")
        try:
            if float(point.get("weight")) <= 0:
                problems.append(f"要点 {pid} 的权重必须为正")
        except (TypeError, ValueError):
            problems.append(f"要点 {pid} 缺少合法权重")

    if question_type == "qa" and len(points) < MIN_QA_POINTS:
        problems.append(f"主观题至少需要 {MIN_QA_POINTS} 条要点，当前 {len(points)} 条")
    if question_type in ("choice", "fill") and not points:
        problems.append("客观题也至少需要 1 条要点作为判分锚点")

    if question_type == "choice":
        options = list(payload.get("options") or [])
        if len(options) < MIN_CHOICE_OPTIONS:
            problems.append(f"选择题至少需要 {MIN_CHOICE_OPTIONS} 个选项，当前 {len(options)} 个")
        correct = [opt for opt in options if isinstance(opt, Mapping) and opt.get("is_correct")]
        if len(correct) != 1:
            problems.append(f"选择题必须有且仅有一个正确项，当前 {len(correct)} 个")
        if source_text:
            haystack = normalize_text(source_text)
            for option in options:
                if not isinstance(option, Mapping):
                    continue
                text = normalize_text(option.get("text"))
                if text and text not in haystack:
                    problems.append(
                        f"选项 {option.get('key')} 无法在资料片段中找到依据（疑似编造）"
                    )
    return problems


def save_question_points(
    training_id: int,
    item_key: str,
    points: Sequence[Mapping[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """写入（或覆盖）某道题的要点清单，返回写入条数。**随题固化，判分时只读。**"""
    active = conn or _connect()
    own = conn is None
    try:
        active.execute(
            "DELETE FROM question_points WHERE training_id = ? AND item_key = ?",
            (int(training_id), str(item_key)),
        )
        now = _now()
        for ordinal, point in enumerate(points, start=1):
            active.execute(
                "INSERT INTO question_points "
                "(training_id, item_key, point_id, point_text, weight, is_required, ordinal, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(training_id),
                    str(item_key),
                    str(point.get("point_id")),
                    str(point.get("text") or ""),
                    float(point.get("weight") or 1),
                    1 if point.get("is_required") else 0,
                    ordinal,
                    now,
                ),
            )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return len(points)


def save_generated_question(
    training_id: int,
    item_key: str,
    payload: Mapping[str, Any],
    *,
    source_text: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """校验并保存一道新题的题型、选项与要点清单。返回校验问题（非空则不落库）。"""
    problems = validate_generated_question(payload, source_text=source_text)
    if problems:
        logger.warning("出题校验未通过 item_key=%s：%s", item_key, "；".join(problems))
        return problems

    active = conn or _connect()
    own = conn is None
    try:
        import json

        active.execute(
            "UPDATE question_bank SET question_type = ?, options = ? "
            "WHERE training_id = ? AND item_key = ?",
            (
                str(payload.get("question_type")),
                json.dumps(payload.get("options") or [], ensure_ascii=False),
                int(training_id),
                str(item_key),
            ),
        )
        save_question_points(
            training_id, item_key, list(payload.get("points") or []), conn=active
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return []


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


__all__ = [
    "MIN_CHOICE_OPTIONS",
    "MIN_QA_POINTS",
    "save_generated_question",
    "save_question_points",
    "validate_generated_question",
]
