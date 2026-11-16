"""学习者模型服务：随作答增量更新、读时衰减查询、全量重放重建。

对应 change ``layered-learner-memory``。设计约束（见该 change design）：

* 单一事实源是 ``practice_attempts``——本表是派生层，rebuild 必与增量收敛（有守卫测试）；
* 更新挂在 ``record_attempt``（全部作答的唯一入口），随作答事务执行，
  派生层失败只告警、MUST NOT 阻塞事实记录；
* 衰减读时计算（30 天半衰期），不落盘、无定时任务。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from src.core.learner import decay_mastery, misconceptions_from_detail, update_mastery
from src.db.sqlite import get_connection as _connect
from src.services.memory_service import MISTAKE_REASON_LABELS, WEAK_SCORE_THRESHOLD

logger = logging.getLogger("src.services.learner_service")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _resolve_knowledge_point(
    active: sqlite3.Connection, training_id: int, item_key: str
) -> str:
    """知识点名：优先题库（练过的题），退回训练项，最后退回 item_key 本身。"""
    row = active.execute(
        "SELECT knowledge_point FROM question_bank WHERE training_id = ? AND item_key = ?",
        (int(training_id), str(item_key)),
    ).fetchone()
    if row and str(row["knowledge_point"] or "").strip():
        return str(row["knowledge_point"]).strip()
    row = active.execute(
        "SELECT knowledge_point FROM training_items WHERE item_key = ? ORDER BY id DESC LIMIT 1",
        (str(item_key),),
    ).fetchone()
    if row and str(row["knowledge_point"] or "").strip():
        return str(row["knowledge_point"]).strip()
    return str(item_key)


def apply_attempt(
    conn: sqlite3.Connection,
    *,
    training_id: int,
    item_key: str,
    result: str,
    score: float | None,
    point_results: str | None,
    created_at: str,
) -> None:
    """随一次判分作答增量更新该 (training_id, item_key) 的学习者模型。

    由 ``attempt_service.record_attempt`` 在同一事务内调用；调用方负责异常兜底
    （派生层失败不阻塞事实记录）。
    """
    outcome = float(score) if score is not None else (1.0 if result == "pass" else 0.0)
    passed = result == "pass"

    row = conn.execute(
        "SELECT id, mastery, misconceptions, attempts_count, passes_count "
        "FROM learner_knowledge WHERE training_id = ? AND item_key = ?",
        (int(training_id), str(item_key)),
    ).fetchone()

    detail = None
    if point_results:
        try:
            parsed = json.loads(point_results)
            if isinstance(parsed, dict):
                detail = parsed
        except (ValueError, TypeError):
            detail = None
    misconceptions = misconceptions_from_detail(detail) if detail is not None else None

    if row is None:
        conn.execute(
            "INSERT INTO learner_knowledge (training_id, item_key, knowledge_point, mastery, "
            "misconceptions, attempts_count, passes_count, last_seen_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (
                int(training_id),
                str(item_key),
                _resolve_knowledge_point(conn, int(training_id), str(item_key)),
                update_mastery(None, outcome),
                json.dumps(misconceptions or [], ensure_ascii=False) if misconceptions is not None else None,
                1 if passed else 0,
                created_at,
                _now(),
            ),
        )
        return

    prev_mastery = float(row["mastery"])
    if misconceptions is None:
        # 无要点明细（测验二元/历史数据）：误解清单保持不变
        kept = row["misconceptions"]
    else:
        kept = json.dumps(misconceptions, ensure_ascii=False)
    conn.execute(
        "UPDATE learner_knowledge SET mastery = ?, misconceptions = ?, attempts_count = ?, "
        "passes_count = ?, last_seen_at = ?, updated_at = ? WHERE id = ?",
        (
            update_mastery(prev_mastery, outcome),
            kept,
            int(row["attempts_count"]) + 1,
            int(row["passes_count"]) + (1 if passed else 0),
            created_at,
            _now(),
            int(row["id"]),
        ),
    )


def get_learner_model(
    training_id: int,
    *,
    today: datetime | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """读取该训练的学习者模型（读时衰减；按 decayed 升序——最弱的排最前）。"""
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT item_key, knowledge_point, mastery, misconceptions, attempts_count, "
            "passes_count, last_seen_at FROM learner_knowledge WHERE training_id = ?",
            (int(training_id),),
        ).fetchall()
    finally:
        if own:
            active.close()

    now = today or datetime.now()
    model: list[dict[str, Any]] = []
    for row in rows:
        mastery = float(row["mastery"])
        last_seen = _parse(row["last_seen_at"])
        days = (now - last_seen).total_seconds() / 86400.0 if last_seen else 0.0
        decayed = decay_mastery(mastery, days)
        misconceptions = []
        raw = row["misconceptions"]
        if raw:
            try:
                for entry in json.loads(raw):
                    if isinstance(entry, dict):
                        reason = str(entry.get("reason") or "")
                        misconceptions.append(
                            {
                                "point_id": str(entry.get("point_id") or ""),
                                "text": str(entry.get("text") or ""),
                                "reason": reason,
                                "reason_label": MISTAKE_REASON_LABELS.get(reason, reason),
                            }
                        )
            except (ValueError, TypeError):
                misconceptions = []
        model.append(
            {
                "item_key": str(row["item_key"]),
                "knowledge_point": str(row["knowledge_point"] or ""),
                "mastery": round(mastery, 4),
                "decayed_mastery": round(decayed, 4),
                "weak": decayed < WEAK_SCORE_THRESHOLD,
                "misconceptions": misconceptions,
                "attempts": int(row["attempts_count"]),
                "passes": int(row["passes_count"]),
                "last_seen_at": str(row["last_seen_at"] or ""),
            }
        )
    model.sort(key=lambda entry: entry["decayed_mastery"])
    return model


def rebuild(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, int]:
    """从 practice_attempts 全量重放重建该训练的学习者模型（部署后回填存量）。

    重放与增量更新必然收敛（同一递推式按 id 序重算）——守卫测试钉死该性质。
    """
    active = conn or _connect()
    own = conn is None
    try:
        active.execute("DELETE FROM learner_knowledge WHERE training_id = ?", (int(training_id),))
        rows = active.execute(
            "SELECT item_key, result, score, point_results, created_at FROM practice_attempts "
            "WHERE training_id = ? ORDER BY id",
            (int(training_id),),
        ).fetchall()
        for row in rows:
            apply_attempt(
                active,
                training_id=int(training_id),
                item_key=str(row["item_key"]),
                result=str(row["result"]),
                score=row["score"],
                point_results=row["point_results"],
                created_at=str(row["created_at"] or ""),
            )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return {"training_id": int(training_id), "replayed_attempts": len(rows)}


__all__ = ["apply_attempt", "get_learner_model", "rebuild"]
