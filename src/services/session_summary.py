"""训练日会话小结（change ``coach-memory-three-layers`` 任务 1.3 / D3）。

**三层记忆之一：当次会话小结**。按 (training_id, attempt 当地日期) 读时聚合当天
判分作答——题数 / 通过率 / 错要点频次 / 最弱知识点 / 各题连败状态。**零新表**：
事实源仍是 practice_attempts，任何视图可重放。

"判分作答" 口径与连败一致（source ∈ llm/quiz/rule）：自评与 practice-only
无客观信号不计。人话叙述默认规则模板拼接；LLM 叙述为开关预留
（app_settings ``session_llm_narrative``，默认关，本模块只读不实现）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date as _date
from typing import Any

from src.core.plan import local_today
from src.db.sqlite import get_connection
from src.services.answer_service import GRADED_STREAK_SOURCES, COACH_HINT_STREAK_THRESHOLD, failure_streak

#: LLM 叙述开关的键名（预留，默认关；叙述本体未实现）
SESSION_LLM_NARRATIVE_KEY: str = "session_llm_narrative"


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def _local_day(created_at: str) -> str:
    """attempt.created_at（UTC ISO）→ 当地日期串（与 local_today 同口径）。"""
    return str(created_at or "")[:10]


def _mistake_texts(point_results_json: str | None, points_json: str | None) -> list[str]:
    """从一次判分结果提取「错的要点」文案：detail.text 优先，回落 points 清单。"""
    texts: list[str] = []
    try:
        parsed = json.loads(point_results_json) if point_results_json else None
    except (ValueError, TypeError):
        parsed = None
    fallback_ids: list[str] = []
    if isinstance(parsed, dict):
        for entry in parsed.get("detail") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("verdict") or "") in ("hit", ""):
                continue
            text = str(entry.get("text") or "").strip()
            pid = str(entry.get("point_id") or "")
            if text:
                texts.append(text)
            elif pid:
                fallback_ids.append(pid)
    if fallback_ids:
        try:
            points = json.loads(points_json) if points_json else None
        except (ValueError, TypeError):
            points = None
        by_id = {
            str(p.get("point_id")): str(p.get("text") or "").strip()
            for p in (points or [])
            if isinstance(p, dict)
        }
        texts.extend(by_id.get(pid, pid) for pid in fallback_ids if by_id.get(pid, pid))
    return texts


def summarize_day(
    training_id: int, day: Any = None, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """聚合某训练日的判分作答。空日期返回空小结（题数 0），不报错。

    返回结构（结构化字段恒定输出，纯规则）：
    date / question_count（判分作答次数）/ item_count / pass_rate（None=无数据）/
    mistake_points（[{"point": 文案, "count": n}] 降序）/ weakest_knowledge_point /
    items（[{"item_key", "knowledge_point", "attempts", "fails", "failure_streak",
    "scores"}]）/ narrative（模板拼接）/ llm_narrative_enabled（预留开关，默认 False）。
    """
    active = _connect(conn)
    own = conn is None
    try:
        day_str = str(day) if day is not None else str(local_today())
        placeholders = ", ".join("?" for _ in GRADED_STREAK_SOURCES)
        rows = active.execute(
            f"SELECT id, item_key, plan_id, result, score, point_results, created_at "
            f"FROM practice_attempts "
            f"WHERE training_id = ? AND source IN ({placeholders}) "
            f"AND date(created_at, 'localtime') = ? "
            f"ORDER BY id ASC",
            (int(training_id), *GRADED_STREAK_SOURCES, day_str),
        ).fetchall()

        # 知识点名与出题时要点清单：attempts.plan_id → plan_items
        plan_ids = sorted({int(row["plan_id"]) for row in rows if row["plan_id"]})
        meta_by_plan: dict[int, dict[str, str]] = {}
        if plan_ids:
            id_placeholders = ", ".join("?" for _ in plan_ids)
            meta_rows = active.execute(
                f"SELECT id, knowledge_point, title, points FROM plan_items "
                f"WHERE id IN ({id_placeholders})",
                plan_ids,
            ).fetchall()
            for meta in meta_rows:
                meta_by_plan[int(meta["id"])] = {
                    "knowledge_point": str(meta["knowledge_point"] or meta["title"] or ""),
                    "points": meta["points"],
                }

        llm_flag = active.execute(
            "SELECT value FROM app_settings WHERE key = ?", (SESSION_LLM_NARRATIVE_KEY,)
        ).fetchone()
    finally:
        if own:
            active.close()

    llm_narrative_enabled = bool(llm_flag) and str(llm_flag["value"]).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    question_count = len(rows)
    pass_count = sum(1 for row in rows if str(row["result"]) == "pass")
    pass_rate = round(pass_count / question_count, 4) if question_count else None

    mistake_counter: dict[str, int] = {}
    kp_fail_counter: dict[str, int] = {}
    items_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_key = str(row["item_key"] or "")
        meta = meta_by_plan.get(int(row["plan_id"])) if row["plan_id"] else None
        kp = (meta or {}).get("knowledge_point") or ""
        if str(row["result"]) == "fail":
            for text in _mistake_texts(row["point_results"], (meta or {}).get("points")):
                mistake_counter[text] = mistake_counter.get(text, 0) + 1
            if kp:
                kp_fail_counter[kp] = kp_fail_counter.get(kp, 0) + 1
        bucket = items_by_key.setdefault(
            item_key,
            {
                "item_key": item_key,
                "knowledge_point": kp,
                "attempts": 0,
                "fails": 0,
                "scores": [],
            },
        )
        bucket["attempts"] += 1
        if str(row["result"]) == "fail":
            bucket["fails"] += 1
        bucket["scores"].append(float(row["score"]) if row["score"] is not None else None)

    for bucket in items_by_key.values():
        # own 时 active 已在 finally 关闭 → 让 failure_streak 自开连接；外部连接则复用
        streak, _ = failure_streak(
            int(training_id), str(bucket["item_key"]), conn=None if own else active
        )
        bucket["failure_streak"] = streak

    weakest: dict[str, Any] | None = None
    if kp_fail_counter:
        worst_kp = max(kp_fail_counter.items(), key=lambda kv: (kv[1], kv[0]))
        weakest = {"knowledge_point": worst_kp[0], "fail_count": worst_kp[1]}

    mistake_points = [
        {"point": text, "count": count}
        for text, count in sorted(mistake_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    narrative = _narrative(
        question_count=question_count,
        pass_rate=pass_rate,
        weakest=weakest,
        items=list(items_by_key.values()),
        mistake_points=mistake_points,
    )

    return {
        "training_id": int(training_id),
        "date": day_str,
        "question_count": question_count,
        "item_count": len(items_by_key),
        "pass_rate": pass_rate,
        "mistake_points": mistake_points,
        "weakest_knowledge_point": weakest,
        "items": list(items_by_key.values()),
        "narrative": narrative,
        "llm_narrative_enabled": llm_narrative_enabled,
    }


def _narrative(
    *,
    question_count: int,
    pass_rate: float | None,
    weakest: dict[str, Any] | None,
    items: list[dict[str, Any]],
    mistake_points: list[dict[str, Any]],
) -> str:
    """人话叙述（规则模板拼接；LLM 叙述为开关预留项，默认关）。"""
    if not question_count:
        return "今天还没有判分作答——练完再来回看。"
    parts = [
        f"今天 {question_count} 题判分作答，通过率 {(pass_rate or 0) * 100:.0f}%。"
    ]
    if weakest:
        parts.append(f"最弱的知识点是「{weakest['knowledge_point']}」（错 {weakest['fail_count']} 次）。")
    hot_streak = max(items, key=lambda b: (b["failure_streak"], b["fails"]))
    if hot_streak["failure_streak"] >= COACH_HINT_STREAK_THRESHOLD:
        parts.append(
            f"「{hot_streak['knowledge_point'] or hot_streak['item_key']}」已连败 "
            f"{hot_streak['failure_streak']} 次，建议看深度解析找共同错因。"
        )
    if mistake_points:
        top = mistake_points[0]
        parts.append(f"高频错点：「{top['point']}」×{top['count']}。")
    return "".join(parts)


def summarize_today(training_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """当地今天的会话小结（端点缺省日期入口）。"""
    return summarize_day(training_id, str(local_today()), conn=conn)


def is_valid_summary_date(day: str) -> bool:
    """YYYY-MM-DD 校验（端点入参守卫用）。"""
    try:
        _date.fromisoformat(str(day))
        return True
    except ValueError:
        return False


__all__ = [
    "SESSION_LLM_NARRATIVE_KEY",
    "is_valid_summary_date",
    "summarize_day",
    "summarize_today",
]
