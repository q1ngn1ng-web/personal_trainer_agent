"""训练计划服务：5 轮排期生成、当日任务、累计顺延、题库登记。

对应 OpenSpec change ``training-plan-and-daily-view`` 与 ADR-0021：

* 整条路径固定 5 轮，锚点是训练创建日，到期日 +1 / +3 / +7 / +15 / +30 天
* 每轮覆盖全部训练项；第 5 轮之后不再产生计划项
* "今天该练什么" = 到期日 ≤ 今天且未完成，**每个题目只取最早未完成的那一轮**
* 勾选 = 练过（写 ``practiced``），同时把题目登记进题库并设置冷却期
* 每 14 天排一次测验任务（``kind='assessment'``）；测验取题属 ``periodic-assessment``
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from src.core.plan import (
    ROUND_OFFSETS,
    PlanSlot,
    PlannedTask,
    cooldown_until,
    item_key_for,
    local_today,
    parse_local_date,
    quiz_due_dates,
    round_due_dates,
    select_today_slots,
    total_minutes,
)
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.plan_service")

#: 题型默认时长（与 path_service.check_budget 的口径一致）
TYPE_MINUTES: dict[str, int] = {
    "memory": 10,
    "comprehension": 15,
    "practice": 20,
    "prerequisite": 15,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


@dataclass
class PlanSummary:
    """一次排期生成的结果，用于页面提示与测试。"""

    training_id: int
    anchor_date: date | None = None
    rounds: int = 0
    item_count: int = 0
    created: int = 0
    quiz_dates: list[date] = field(default_factory=list)
    last_due_date: date | None = None

    @property
    def is_empty(self) -> bool:
        return self.created == 0 and self.item_count == 0


def _current_path_id(active: sqlite3.Connection, training_id: int) -> int | None:
    row = active.execute(
        "SELECT id FROM training_paths WHERE training_id = ? "
        "ORDER BY (status = 'confirmed') DESC, version DESC LIMIT 1",
        (training_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def _path_items(active: sqlite3.Connection, training_id: int) -> list[dict[str, Any]]:
    """当前路径下的训练项（按阶段顺序 → 阶段内顺序）。"""
    path_id = _current_path_id(active, training_id)
    if path_id is None:
        return []
    rows = active.execute(
        """
        SELECT i.id, i.item_key, i.title, i.knowledge_point, i.item_type, i.difficulty_tier,
               i.source_chunk_ids, i.ordinal, s.ordinal AS stage_ordinal
        FROM training_items i
        JOIN path_stages s ON s.id = i.stage_id
        WHERE s.path_id = ?
        ORDER BY s.ordinal, i.ordinal, i.id
        """,
        (path_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _item_metadata(active: sqlite3.Connection, training_id: int) -> dict[str, dict[str, Any]]:
    """item_key → 训练项元数据（当前路径）。"""
    return {
        str(item["item_key"]): item
        for item in _path_items(active, training_id)
        if item.get("item_key")
    }


def _planned_minutes(item_type: str | None) -> int:
    return int(TYPE_MINUTES.get(str(item_type or ""), 15))


def generate_plan(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> PlanSummary:
    """为训练生成 5 轮训练计划与两周一次的测验任务（幂等）。"""
    active = _connect(conn)
    own = conn is None
    try:
        training = active.execute(
            "SELECT * FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
        if training is None:
            raise ValueError(f"training not found: {training_id}")

        anchor = parse_local_date(training["created_at"], local_today())
        items = _path_items(active, training_id)
        if not items:
            return PlanSummary(training_id=training_id, anchor_date=anchor)

        due_dates = round_due_dates(anchor)
        last_due = max(due_dates.values())
        now = _now()
        rows: list[tuple[Any, ...]] = []
        for item in items:
            key = str(item["item_key"] or "")
            if not key:
                continue
            minutes = _planned_minutes(item["item_type"])
            for round_index, due in due_dates.items():
                rows.append(
                    (
                        training_id,
                        key,
                        round_index,
                        "train",
                        due.isoformat(),
                        anchor.isoformat(),
                        due.isoformat(),
                        "planned",
                        minutes,
                        now,
                    )
                )

        quiz_dates = quiz_due_dates(anchor, last_due)
        for quiz_date in quiz_dates:
            rows.append(
                (
                    training_id,
                    f"quiz-{quiz_date.isoformat()}",
                    0,
                    "assessment",
                    quiz_date.isoformat(),
                    anchor.isoformat(),
                    quiz_date.isoformat(),
                    "planned",
                    0,
                    now,
                )
            )

        before = active.execute(
            "SELECT COUNT(*) AS n FROM plan_items WHERE training_id = ?", (training_id,)
        ).fetchone()["n"]
        active.executemany(
            "INSERT OR IGNORE INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        after = active.execute(
            "SELECT COUNT(*) AS n FROM plan_items WHERE training_id = ?", (training_id,)
        ).fetchone()["n"]
        if own:
            active.commit()

        logger.info(
            "generate_plan: training %s -> %d item(s) x %d round(s), %d quiz day(s)",
            training_id,
            len(items),
            len(due_dates),
            len(quiz_dates),
        )
        return PlanSummary(
            training_id=training_id,
            anchor_date=anchor,
            rounds=len(due_dates),
            item_count=len(items),
            created=int(after) - int(before),
            quiz_dates=quiz_dates,
            last_due_date=last_due,
        )
    finally:
        if own:
            active.close()


def item_id_for(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> int | None:
    """按稳定题目键取当前路径里的训练项主键（信号归因用：`learning_signals.item_id`）。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT i.id FROM training_items i "
            "JOIN path_stages s ON s.id = i.stage_id "
            "JOIN training_paths p ON p.id = s.path_id "
            "WHERE p.training_id = ? AND i.item_key = ? "
            "ORDER BY (p.status = 'confirmed') DESC, p.version DESC LIMIT 1",
            (int(training_id), str(item_key)),
        ).fetchone()
        return int(row["id"]) if row else None
    finally:
        if own:
            active.close()


def has_plan(training_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT 1 FROM plan_items WHERE training_id = ? LIMIT 1", (training_id,)
        ).fetchone()
        return row is not None
    finally:
        if own:
            active.close()


def ensure_plan(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> PlanSummary:
    """老训练（有路径但没计划）首次进入时补生成一次。"""
    if has_plan(training_id, conn=conn):
        active = _connect(conn)
        own = conn is None
        try:
            row = active.execute(
                "SELECT MIN(due_date) AS first_due, MAX(due_date) AS last_due "
                "FROM plan_items WHERE training_id = ?",
                (training_id,),
            ).fetchone()
            return PlanSummary(
                training_id=training_id,
                last_due_date=parse_local_date(row["last_due"]) if row["last_due"] else None,
            )
        finally:
            if own:
                active.close()
    return generate_plan(training_id, conn=conn)


def _row_to_task(
    row: sqlite3.Row | dict[str, Any],
    *,
    metadata: dict[str, dict[str, Any]],
    training_topic: str,
) -> PlannedTask:
    data = dict(row)
    item = metadata.get(str(data.get("item_key")), {})
    return PlannedTask(
        plan_id=int(data["id"]),
        training_id=int(data["training_id"]),
        item_key=str(data["item_key"]),
        round_index=int(data["round_index"]),
        kind=str(data.get("kind") or "train"),
        due_date=parse_local_date(data["due_date"]),
        original_date=parse_local_date(data.get("original_date") or data["due_date"]),
        status=str(data.get("status") or "planned"),
        planned_minutes=int(data.get("planned_minutes") or 0),
        title=str(item.get("title") or "（该训练项已变更）"),
        knowledge_point=str(item.get("knowledge_point") or ""),
        item_type=str(item.get("item_type") or ""),
        difficulty_tier=item.get("difficulty_tier"),
        training_topic=training_topic,
        ordinal=int(item.get("ordinal") or 0),
        question=str(data.get("question") or ""),
        reference_answer=str(data.get("reference_answer") or ""),
        answer_text=str(data.get("answer_text") or ""),
        verdict=data.get("verdict"),
        graded_by=data.get("graded_by"),
    )


def today_tasks(
    *,
    training_id: int | None = None,
    today: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[PlannedTask]:
    """今天该练什么：到期日 ≤ 今天且未完成，每个题目只取最早未完成的那一轮。

    ``training_id`` 省略时做**跨训练聚合**（首页「今日训练」的取数口径）。
    """
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        sql = (
            "SELECT p.*, t.topic AS training_topic FROM plan_items p "
            "JOIN trainings t ON t.id = p.training_id "
            "WHERE p.kind = 'train' AND p.status = 'planned' AND p.due_date <= ?"
        )
        params: list[Any] = [effective_today.isoformat()]
        if training_id is not None:
            sql += " AND p.training_id = ?"
            params.append(training_id)
        sql += " ORDER BY p.training_id, p.due_date, p.round_index, p.id"
        rows = active.execute(sql, params).fetchall()

        slots = [
            PlanSlot(
                item_key=str(row["item_key"]),
                round_index=int(row["round_index"]),
                due_date=parse_local_date(row["due_date"]),
                status=str(row["status"]),
            )
            for row in rows
        ]
        keep = {
            (slot.item_key, slot.round_index) for slot in select_today_slots(slots, effective_today)
        }

        tasks: list[PlannedTask] = []
        cache: dict[int, dict[str, dict[str, Any]]] = {}
        for row in rows:
            key = (str(row["item_key"]), int(row["round_index"]))
            if key not in keep:
                continue
            tid = int(row["training_id"])
            if tid not in cache:
                cache[tid] = _item_metadata(active, tid)
            tasks.append(
                _row_to_task(
                    row,
                    metadata=cache[tid],
                    training_topic=str(row["training_topic"] or ""),
                )
            )
    finally:
        if own:
            active.close()

    tasks.sort(key=lambda task: (task.training_id, task.ordinal, task.round_index, task.plan_id))
    return tasks


def today_summary(
    *,
    training_id: int | None = None,
    today: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """首页「今日训练」用的汇总：条数、合计时长、按训练分组。"""
    tasks = today_tasks(training_id=training_id, today=today, conn=conn)
    groups: dict[int, dict[str, Any]] = {}
    for task in tasks:
        group = groups.setdefault(
            task.training_id,
            {"training_id": task.training_id, "topic": task.training_topic, "count": 0, "minutes": 0},
        )
        group["count"] += 1
        group["minutes"] += int(task.planned_minutes or 0)
    return {
        "count": len(tasks),
        "minutes": total_minutes(tasks),
        "groups": list(groups.values()),
        "tasks": tasks,
    }


def next_due_date(
    training_id: int, *, today: date | None = None, conn: sqlite3.Connection | None = None
) -> date | None:
    """下一次有任务的日期（今天无任务时的空态提示）。"""
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT MIN(due_date) AS next_due FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' AND status = 'planned' AND due_date > ?",
            (training_id, effective_today.isoformat()),
        ).fetchone()
    finally:
        if own:
            active.close()
    return parse_local_date(row["next_due"]) if row and row["next_due"] else None


def _mark_item_practiced(
    active: sqlite3.Connection, training_id: int, item_key: str
) -> None:
    """把训练项标为「练过」（不覆盖已达标状态）。"""
    path_id = _current_path_id(active, training_id)
    if path_id is None:
        return
    active.execute(
        "UPDATE training_items SET status = 'practiced' "
        "WHERE item_key = ? AND status IN ('pending', 'in_progress', 'failed') "
        "AND stage_id IN (SELECT id FROM path_stages WHERE path_id = ?)",
        (item_key, path_id),
    )


def _probe_text(
    active: sqlite3.Connection, training_id: int, knowledge_point: str
) -> tuple[str | None, str | None]:
    """理解边缘探测阶段留下的题目文本（八股资料里往往是现成的问答题）。"""
    if not knowledge_point:
        return None, None
    row = active.execute(
        "SELECT question, reference_answer FROM edge_assessments "
        "WHERE training_id = ? AND knowledge_point = ? ORDER BY id DESC LIMIT 1",
        (training_id, knowledge_point),
    ).fetchone()
    if row is None:
        return None, None
    return row["question"], row["reference_answer"]


def register_in_question_bank(
    active: sqlite3.Connection,
    training_id: int,
    item_key: str,
    *,
    practiced_on: date,
    practiced_at: str | None = None,
) -> None:
    """练过即入题库，并把冷却期推到"练过日 + 14 天"（ADR-0016）。"""
    metadata = _item_metadata(active, training_id)
    item = metadata.get(item_key, {})
    knowledge_point = str(item.get("knowledge_point") or "")
    question_text, answer_text = _probe_text(active, training_id, knowledge_point)
    if not question_text:
        question_text = str(item.get("title") or "")
    chunk_ids = item.get("source_chunk_ids")
    if isinstance(chunk_ids, str) and chunk_ids:
        pass
    elif chunk_ids:
        chunk_ids = json.dumps(chunk_ids)

    active.execute(
        """
        INSERT INTO question_bank (training_id, item_key, source_chunk_ids, knowledge_point,
                                   item_type, difficulty_tier, question_text, answer_text,
                                   practiced_count, last_practiced_at, banked_at, cooldown_until, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')
        ON CONFLICT(training_id, item_key) DO UPDATE SET
            practiced_count = question_bank.practiced_count + 1,
            last_practiced_at = excluded.last_practiced_at,
            cooldown_until = excluded.cooldown_until,
            question_text = COALESCE(excluded.question_text, question_bank.question_text),
            answer_text = COALESCE(excluded.answer_text, question_bank.answer_text),
            source_chunk_ids = COALESCE(excluded.source_chunk_ids, question_bank.source_chunk_ids)
        """,
        (
            training_id,
            item_key,
            chunk_ids,
            knowledge_point or None,
            item.get("item_type"),
            item.get("difficulty_tier"),
            question_text or None,
            answer_text,
            practiced_at or _now(),
            _now(),
            cooldown_until(practiced_on).isoformat(),
        ),
    )


def complete_tasks(
    plan_ids: list[int],
    *,
    completed: bool = True,
    today: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """勾选 / 取消勾选计划项。勾选 = 练过（并登记题库），不产生"达标"。"""
    if not plan_ids:
        return 0
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    updated = 0
    try:
        for plan_id in plan_ids:
            row = active.execute(
                "SELECT * FROM plan_items WHERE id = ?", (int(plan_id),)
            ).fetchone()
            if row is None:
                continue
            training_id = int(row["training_id"])
            item_key = str(row["item_key"])
            if completed:
                active.execute(
                    "UPDATE plan_items SET status = 'practiced', practiced_at = ? WHERE id = ?",
                    (_now(), int(plan_id)),
                )
                if str(row["kind"]) == "train":
                    _mark_item_practiced(active, training_id, item_key)
                    register_in_question_bank(
                        active,
                        training_id,
                        item_key,
                        practiced_on=effective_today,
                    )
            else:
                # 取消勾选：回到待做，但保留 practiced_at（不抹掉"确实练过"的证据）
                active.execute(
                    "UPDATE plan_items SET status = 'planned' WHERE id = ?", (int(plan_id),)
                )
            updated += 1
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return updated


def skip_task(
    plan_id: int, reason: str, *, conn: sqlite3.Connection | None = None
) -> None:
    """跳过一项：必须记原因，且不计入完成。"""
    if not str(reason or "").strip():
        raise ValueError("跳过必须填写原因")
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE plan_items SET status = 'skipped', reason = ? WHERE id = ?",
            (str(reason).strip(), int(plan_id)),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


def drawable_questions(
    training_id: int,
    *,
    today: date | None = None,
    limit: int = 0,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """冷却期已过的题目（可供抽取测验题）。不到 14 天的题目 MUST NOT 出现在这里。"""
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        sql = (
            "SELECT * FROM question_bank WHERE training_id = ? AND status = 'active' "
            "AND (cooldown_until IS NULL OR cooldown_until <= ?) "
            "ORDER BY practiced_count DESC, last_practiced_at"
        )
        params: list[Any] = [training_id, effective_today.isoformat()]
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = active.execute(sql, params).fetchall()
    finally:
        if own:
            active.close()
    return [dict(row) for row in rows]


def plan_progress(
    training_id: int, *, today: date | None = None, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """训练计划进度：总数、已练、待做、当前轮次、下一次到期日。"""
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT round_index, status, COUNT(*) AS n FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' GROUP BY round_index, status",
            (training_id,),
        ).fetchall()
        total = sum(int(row["n"]) for row in rows)
        practiced = sum(int(row["n"]) for row in rows if row["status"] == "practiced")
        by_round: dict[int, dict[str, int]] = {}
        for row in rows:
            bucket = by_round.setdefault(int(row["round_index"]), {})
            bucket[str(row["status"])] = int(row["n"])
    finally:
        if own:
            active.close()
    return {
        "total": total,
        "practiced": practiced,
        "pending": total - practiced,
        "by_round": by_round,
        "next_due": next_due_date(training_id, today=effective_today, conn=conn),
    }


__all__ = [
    "ROUND_OFFSETS",
    "TYPE_MINUTES",
    "PlanSummary",
    "complete_tasks",
    "drawable_questions",
    "ensure_plan",
    "generate_plan",
    "has_plan",
    "item_id_for",
    "item_key_for",
    "next_due_date",
    "plan_progress",
    "register_in_question_bank",
    "skip_task",
    "today_summary",
    "today_tasks",
]
