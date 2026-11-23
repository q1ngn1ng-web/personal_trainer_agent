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
    LOCAL_TZ_NAME,
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
from src.core.session_composition import (
    ItemStat,
    compose_sessions,
)
from zoneinfo import ZoneInfo
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
    """排期生成入口（幂等）：按训练的 schedule_mode 分发。

    * ``session_ratio``（user-defined-training-plan）：按 goal 快照的节奏参数
      生成会话制计划（配比控制器组会话，终测把关）；
    * 其余（默认 ``legacy_v21``）：ADR-0021 固定五轮，存量零迁移。
    """
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT schedule_mode, goal_json FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
    finally:
        if own:
            active.close()
    if row is not None and str(row["schedule_mode"] or "") == "session_ratio":
        horizon_days, session_count = _pace_from_goal(row["goal_json"])
        return generate_plan_v2(
            training_id, horizon_days=horizon_days, session_count=session_count, conn=conn
        )
    return generate_plan_v21(training_id, conn=conn)


def _pace_from_goal(goal_json: Any) -> tuple[int, int]:
    """从 goal 快照读节奏参数（缺失/非法回落默认值）。"""
    from src.core.goal import DEFAULT_HORIZON_DAYS, DEFAULT_SESSION_COUNT

    payload: dict[str, Any] = {}
    if isinstance(goal_json, dict):
        payload = goal_json
    elif isinstance(goal_json, str) and goal_json.strip():
        try:
            loaded = json.loads(goal_json)
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}
    try:
        horizon_days = int(payload.get("horizon_days") or DEFAULT_HORIZON_DAYS)
    except (TypeError, ValueError):
        horizon_days = DEFAULT_HORIZON_DAYS
    try:
        session_count = int(payload.get("session_count") or DEFAULT_SESSION_COUNT)
    except (TypeError, ValueError):
        session_count = DEFAULT_SESSION_COUNT
    horizon_days = max(1, min(56, horizon_days))
    session_count = max(2, min(6, session_count))
    return horizon_days, session_count


def _item_stats(active: sqlite3.Connection, training_id: int) -> list[ItemStat]:
    """训练项的客观表现快照（配比控制器输入）：按当前路径顺序，attempts 聚合。"""
    stats: dict[str, ItemStat] = {}
    for index, item in enumerate(_path_items(active, training_id)):
        key = str(item["item_key"] or "")
        if not key:
            continue
        stats[key] = ItemStat(
            item_key=key,
            knowledge_point=str(item.get("knowledge_point") or ""),
            minutes=_planned_minutes(item.get("item_type")),
            ordinal=index,
        )
    rows = active.execute(
        "SELECT item_key, result, created_at FROM practice_attempts "
        "WHERE training_id = ? AND source IN ('llm', 'quiz', 'rule') ORDER BY id ASC",
        (training_id,),
    ).fetchall()
    for row in rows:
        stat = stats.get(str(row["item_key"]))
        if stat is None:
            continue  # 已从路径移除的项不参与分配
        result = str(row["result"])
        stat.attempts += 1
        stat.ever_passed = stat.ever_passed or result == "pass"
        stat.ever_failed = stat.ever_failed or result == "fail"
        stat.last_result = result
        stat.consecutive_passes = stat.consecutive_passes + 1 if result == "pass" else 0
        stat.last_practiced = str(row["created_at"] or "")
    return list(stats.values())


def _pace_row_values(
    training_id: int,
    item_key: str,
    round_index: int,
    kind: str,
    due: date,
    anchor: date,
    minutes: int,
    now: str,
) -> tuple[Any, ...]:
    return (
        training_id,
        item_key,
        round_index,
        kind,
        due.isoformat(),
        anchor.isoformat(),
        due.isoformat(),
        "planned",
        minutes,
        now,
    )


def generate_plan_v2(
    training_id: int,
    *,
    horizon_days: int,
    session_count: int,
    conn: sqlite3.Connection | None = None,
) -> PlanSummary:
    """会话制排期（user-defined-training-plan 2.3）：N 次会话 + 终测完成门。

    * 分配由配比控制器纯函数给出（并集 100%、占比表、恒稳控制器、五星排序）；
    * 会话日期在 horizon 内近似均匀摊开；允许提前练（任务动作不设到期门）；
    * 周期小测（每 14 天）与终测并存；UNIQUE(training_id, item_key, round_index)
      + INSERT OR IGNORE 保证幂等（重复生成不产生重复项）。
    """
    active = _connect(conn)
    own = conn is None
    try:
        training = active.execute(
            "SELECT * FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
        if training is None:
            raise ValueError(f"training not found: {training_id}")

        anchor = parse_local_date(training["created_at"], local_today())
        stats = _item_stats(active, training_id)
        if not stats:
            return PlanSummary(training_id=training_id, anchor_date=anchor)

        composition = compose_sessions(
            stats, session_count, anchor=anchor, horizon_days=horizon_days
        )
        now = _now()
        rows: list[tuple[Any, ...]] = []
        by_key = {stat.item_key: stat for stat in stats}
        for index, (keys, due) in enumerate(zip(composition.sessions, composition.dates), start=1):
            for key in keys:
                stat = by_key[key]
                rows.append(
                    _pace_row_values(training_id, key, index, "train", due, anchor, stat.minutes, now)
                )

        # 周期小测（每 14 天）保留，与终测并存
        quiz_dates = quiz_due_dates(anchor, max(composition.dates))
        for quiz_date in quiz_dates:
            rows.append(
                _pace_row_values(
                    training_id, f"quiz-{quiz_date.isoformat()}", 0, "assessment",
                    quiz_date, anchor, 0, now,
                )
            )
        # 终测：覆盖全部必修项（design D4），排在最后一个会话日
        final_date = max(composition.dates)
        rows.append(
            _pace_row_values(
                training_id, f"final-{final_date.isoformat()}", len(composition.sessions),
                "assessment", final_date, anchor, 0, now,
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
        active.execute(
            "UPDATE trainings SET schedule_mode = 'session_ratio' WHERE id = ?", (training_id,)
        )
        if own:
            active.commit()

        logger.info(
            "generate_plan_v2: training %s -> %d item(s) x %d session(s), horizon %d day(s)",
            training_id,
            len(stats),
            len(composition.sessions),
            horizon_days,
        )
        return PlanSummary(
            training_id=training_id,
            anchor_date=anchor,
            rounds=len(composition.sessions),
            item_count=len(stats),
            created=int(after) - int(before),
            quiz_dates=quiz_dates,
            last_due_date=final_date,
        )
    finally:
        if own:
            active.close()


def generate_plan_v21(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> PlanSummary:
    """ADR-0021 固定五轮排期（legacy_v21，存量口径零迁移）。"""
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
            "generate_plan_v21: training %s -> %d item(s) x %d round(s), %d quiz day(s)",
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


def find_task_by_plan_id(
    plan_id: int, *, conn: sqlite3.Connection | None = None
) -> PlannedTask | None:
    """按 plan_items 主键直查任务（任务动作端点不设到期门）。

    ``today_tasks`` 只覆盖「到期日 ≤ 今天且未完成」的轮次——提前练（未到期）、
    重新作答（已 practiced）都会落空。动作端点（question/answer/practice-only/
    skip/points/explanation）按主键定位，任何到期日与状态都能找到；
    行不存在（如会话重组后前端拿着旧 plan_id）返回 None，由调用方 404。
    """
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT p.*, t.topic AS training_topic FROM plan_items p "
            "JOIN trainings t ON t.id = p.training_id WHERE p.id = ?",
            (int(plan_id),),
        ).fetchone()
        if row is None:
            return None
        return _row_to_task(
            row,
            metadata=_item_metadata(active, int(row["training_id"])),
            training_topic=str(row["training_topic"] or ""),
        )
    finally:
        if own:
            active.close()


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
        # 同一训练项一天只推一轮：今天已作答过的项，其后续逾期轮次不再顶格出现
        # （否则"做了几题数量不减少"）。次日仍会按顺延规则重新出现。
        practiced_keys = _practiced_today_keys(active, effective_today, training_id)
        slots = [slot for slot in slots if slot.item_key not in practiced_keys]

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


def training_plan_items(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> list[PlannedTask]:
    """完整训练计划视图：该训练全部训练轮次（含未到期与已完成的，按到期日排序）。

    与 ``today_tasks`` 的差别：不过滤到期日、不按"最早未完成轮次"去重——
    用于「完整计划」页（查看全貌 + 支持提前练）。任务动作端点本身不设到期门，
    未来轮次可直接提交作答。
    """
    active = _connect(conn)
    own = conn is None
    try:
        sql = (
            "SELECT p.*, t.topic AS training_topic FROM plan_items p "
            "JOIN trainings t ON t.id = p.training_id "
            "WHERE p.kind = 'train' AND p.training_id = ? "
            "ORDER BY p.due_date, p.round_index, p.id"
        )
        rows = active.execute(sql, (int(training_id),)).fetchall()

        tasks: list[PlannedTask] = []
        cache: dict[int, dict[str, dict[str, Any]]] = {}
        for row in rows:
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
        return tasks
    finally:
        if own:
            active.close()


def questions_overview(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """题库总览：该训练全部题目与状态（不含参考答案——防背题）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT item_key, knowledge_point, question_type, substr(question_text, 1, 200) "
            "AS question_text, practiced_count, status, cooldown_until FROM question_bank "
            "WHERE training_id = ? ORDER BY knowledge_point, item_key",
            (int(training_id),),
        ).fetchall()
        today_iso = local_today().isoformat()
        return [
            {
                "item_key": str(r["item_key"]),
                "knowledge_point": r["knowledge_point"],
                "question_type": r["question_type"] or "qa",
                "question_text": r["question_text"],
                "practiced_count": int(r["practiced_count"] or 0),
                "status": r["status"] or "active",
                "in_cooldown": bool(r["cooldown_until"] and str(r["cooldown_until"]) > today_iso),
            }
            for r in rows
        ]
    finally:
        if own:
            active.close()


def question_meta(plan_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """计划项内联的题型与选项 JSON 原文（随题固化），供前端渲染客观题。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT question_type, options FROM plan_items WHERE id = ?",
            (int(plan_id),),
        ).fetchone()
    finally:
        if own:
            active.close()
    if row is None:
        return {"question_type": None, "options": None}
    return {"question_type": row["question_type"], "options": row["options"]}


def _local_day_start_utc(today: date) -> str:
    """本地今天 0 点对应的 UTC ISO 时刻（用于"今天作答过"的比较）。"""
    tz = ZoneInfo(LOCAL_TZ_NAME)
    local_midnight = datetime(today.year, today.month, today.day, tzinfo=tz)
    return local_midnight.astimezone(timezone.utc).isoformat()


def _practiced_today_keys(
    active: sqlite3.Connection, today: date, training_id: int | None = None
) -> set[str]:
    """今天（本地日）已作答过的训练项 item_key 集合——同一训练项一天只推一轮。

    用 SQLite date(localtime) 判日：与 practiced_at 的存储格式（ISO/老格式）解耦。
    """
    sql = (
        "SELECT DISTINCT item_key FROM plan_items WHERE kind = 'train' "
        "AND status = 'practiced' AND date(practiced_at, 'localtime') = ?"
    )
    params: list[Any] = [today.isoformat()]
    if training_id is not None:
        sql += " AND training_id = ?"
        params.append(int(training_id))
    rows = active.execute(sql, params).fetchall()
    return {str(r["item_key"]) for r in rows}


def pregenerate_questions(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """提前生成该训练全部未生成轮次的题目（"早早生成"，不再临时现出题）。

    幂等：只处理 question 为空的轮次；模型不可用时直接跳过（不产出降级题目）。
    后台任务调用——逐轮 LLM 生成，大训练耗时数分钟属预期。
    """
    from src.llm import client as llm_client
    from src.services.answer_service import ensure_question

    if not llm_client.DEEPSEEK_API_KEY:
        return {"skipped": "llm_unavailable", "generated": 0, "total": 0}

    active = _connect(conn)
    own = conn is None
    try:
        ids = [
            int(r["id"])
            for r in active.execute(
                "SELECT id FROM plan_items WHERE training_id = ? AND kind = 'train' "
                "AND status = 'planned' AND (question IS NULL OR question = '') "
                "ORDER BY due_date, round_index, id",
                (int(training_id),),
            ).fetchall()
        ]
        generated = 0
        for plan_id in ids:
            try:
                ensure_question(plan_id, conn=active)
                active.commit()  # 逐条提交：不持长写事务，交互请求不被锁阻塞
                generated += 1
            except Exception as exc:  # 单题失败不阻塞整批（留下次重试）
                active.rollback()
                logger.warning("pregenerate_questions: plan %s failed: %s", plan_id, exc)
        logger.info("pregenerate_questions: training=%s generated=%s/%s", training_id, generated, len(ids))
        return {"generated": generated, "total": len(ids)}
    finally:
        if own:
            active.close()


def done_today_tasks(
    today: date | None = None, *, conn: sqlite3.Connection | None = None
) -> list[PlannedTask]:
    """今天已作答的轮次（跨训练，按作答时间倒序）——今日页"已作答"分组的数据源。"""
    effective_today = today or local_today()
    start_iso = _local_day_start_utc(effective_today)
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT p.*, t.topic AS training_topic FROM plan_items p "
            "JOIN trainings t ON t.id = p.training_id "
            "WHERE p.kind = 'train' AND p.status = 'practiced' AND p.practiced_at >= ? "
            "ORDER BY p.practiced_at DESC",
            (start_iso,),
        ).fetchall()
        tasks: list[PlannedTask] = []
        cache: dict[int, dict[str, dict[str, Any]]] = {}
        for row in rows:
            tid = int(row["training_id"])
            if tid not in cache:
                cache[tid] = _item_metadata(active, tid)
            tasks.append(
                _row_to_task(row, metadata=cache[tid], training_topic=str(row["training_topic"] or ""))
            )
        return tasks
    finally:
        if own:
            active.close()


def today_summary(
    *,
    training_id: int | None = None,
    today: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """首页「今日训练」用的汇总：条数、合计时长、按训练分组。

    分组统计口径：``total`` = 今日应做轮次（待完成 + 今天已完成）；
    ``practiced`` = 今天已完成——前端完成度随作答递增（修复"百分比不动"）。
    """
    tasks = today_tasks(training_id=training_id, today=today, conn=conn)
    done = done_today_tasks(today=today, conn=conn)
    done_by_training: dict[int, int] = {}
    for task in done:
        done_by_training[task.training_id] = done_by_training.get(task.training_id, 0) + 1
    groups: dict[int, dict[str, Any]] = {}
    for task in tasks:
        group = groups.setdefault(
            task.training_id,
            {
                "training_id": task.training_id,
                "topic": task.training_topic,
                "count": 0,
                "minutes": 0,
                "practiced": done_by_training.get(task.training_id, 0),
                "total": 0,
            },
        )
        group["count"] += 1
        group["minutes"] += int(task.planned_minutes or 0)
    # 今日应做总数 = 待完成 + 今天已完成；只完成过的训练也进分组
    for tid, done_count in done_by_training.items():
        if tid in groups:
            groups[tid]["total"] = groups[tid]["count"] + done_count
    for task in done:
        if task.training_id not in groups:
            groups[task.training_id] = {
                "training_id": task.training_id,
                "topic": task.training_topic,
                "count": 0,
                "minutes": 0,
                "practiced": done_by_training.get(task.training_id, 0),
                "total": done_by_training.get(task.training_id, 0),
            }
    return {
        "count": len(tasks),
        "minutes": total_minutes(tasks),
        "groups": list(groups.values()),
        "tasks": tasks,
        "done": done,
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
    session_done_trigger: tuple[int, int] | None = None
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
                    # 会话制排期：记下本项所属会话，收尾时检查"刚全部练完"→ 重组后续
                    session_done_trigger = (training_id, int(row["round_index"]))
            else:
                # 取消勾选：回到待做，但保留 practiced_at（不抹掉"确实练过"的证据）
                active.execute(
                    "UPDATE plan_items SET status = 'planned' WHERE id = ?", (int(plan_id),)
                )
            updated += 1
        # 会话制排期（user-defined-training-plan D2/D5）：某会话刚全部练完 →
        # 恒稳控制器按最近会话正确率重组后续未开始的会话（只换清单不挪日期）
        if session_done_trigger is not None:
            trigger_training, trigger_session = session_done_trigger
            row = active.execute(
                "SELECT schedule_mode FROM trainings WHERE id = ?", (trigger_training,)
            ).fetchone()
            if row is not None and str(row["schedule_mode"] or "") == "session_ratio" and _session_fully_practiced(
                active, trigger_training, trigger_session
            ):
                recompose_future_sessions(trigger_training, conn=active)
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


def _session_accuracy(
    active: sqlite3.Connection, training_id: int, session_index: int
) -> float | None:
    """最近一次会话的判分正确率（恒稳控制器输入口径）：该会话各训练项最近一次判分结果。"""
    keys = [
        str(r["item_key"])
        for r in active.execute(
            "SELECT DISTINCT item_key FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' AND round_index = ?",
            (training_id, session_index),
        ).fetchall()
    ]
    if not keys:
        return None
    placeholders = ", ".join("?" for _ in keys)
    latest: dict[str, str] = {}
    for row in active.execute(
        f"SELECT item_key, result FROM practice_attempts "
        f"WHERE training_id = ? AND item_key IN ({placeholders}) "
        f"AND source IN ('llm', 'quiz', 'rule') ORDER BY id ASC",
        (training_id, *keys),
    ).fetchall():
        latest[str(row["item_key"])] = str(row["result"])
    if not latest:
        return None
    passes = sum(1 for result in latest.values() if result == "pass")
    return passes / len(latest)


def _session_fully_practiced(
    active: sqlite3.Connection, training_id: int, session_index: int
) -> bool:
    """该会话是否已全部练过（至少 1 项 practiced 且无 planned 余项）。"""
    row = active.execute(
        "SELECT "
        "SUM(CASE WHEN status = 'planned' THEN 1 ELSE 0 END) AS planned, "
        "SUM(CASE WHEN status = 'practiced' THEN 1 ELSE 0 END) AS practiced "
        "FROM plan_items WHERE training_id = ? AND kind = 'train' AND round_index = ?",
        (training_id, session_index),
    ).fetchone()
    return bool(row) and int(row["practiced"] or 0) > 0 and int(row["planned"] or 0) == 0


def recompose_future_sessions(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> bool:
    """按恒稳控制器重组尚未开始（零 practiced）的后续会话（design D2 动态配比）。

    触发：某会话刚全部练完（complete_tasks 钩子）。已练过的会话与覆盖不改动
    （design D5），未来会话只换清单不挪日期（fixed_dates）。
    返回是否发生了重组。
    """
    active = _connect(conn)
    own = conn is None
    try:
        mode = active.execute(
            "SELECT schedule_mode FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
        if mode is None or str(mode["schedule_mode"] or "") != "session_ratio":
            return False

        buckets: dict[int, dict[str, int]] = {}
        for row in active.execute(
            "SELECT round_index, status, COUNT(*) AS n FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' GROUP BY round_index, status",
            (training_id,),
        ).fetchall():
            bucket = buckets.setdefault(int(row["round_index"]), {})
            bucket[str(row["status"])] = int(row["n"])
        fully_done = [
            index
            for index, bucket in buckets.items()
            if bucket.get("planned", 0) == 0 and bucket.get("practiced", 0) > 0
        ]
        if not fully_done:
            return False
        last_done = max(fully_done)
        future = sorted(index for index in buckets if index > last_done)
        if not future:
            return False

        from src.core.mastery import MASTERY_STREAK

        stats = _item_stats(active, training_id)
        by_key = {stat.item_key: stat for stat in stats}
        if not stats:
            return False

        # 已覆盖 = 已完成会话（≤ last_done）里出现过的项；未覆盖项由未来会话补齐
        covered_rows = active.execute(
            "SELECT DISTINCT item_key FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' AND round_index <= ?",
            (training_id, last_done),
        ).fetchall()
        covered = {str(r["item_key"]) for r in covered_rows}
        # 未来会话的既有日期（重组不挪排期）
        dates: dict[int, date] = {}
        for row in active.execute(
            "SELECT DISTINCT round_index, due_date FROM plan_items "
            "WHERE training_id = ? AND kind = 'train' AND round_index > ?",
            (training_id, last_done),
        ).fetchall():
            dates[int(row["round_index"])] = parse_local_date(row["due_date"])
        fixed_dates = [dates[index] for index in future if index in dates]

        accuracy = _session_accuracy(active, training_id, last_done)
        stable = [
            stat.item_key
            for stat in stats
            if stat.consecutive_passes >= MASTERY_STREAK or stat.item_key in covered
        ]
        composition = compose_sessions(
            stats,
            len(future),
            anchor=local_today(),
            horizon_days=max(1, (max(dates.values()) - min(dates.values())).days if dates else 14),
            accuracy=accuracy,
            stable_keys=stable,
            pre_covered=sorted(covered),
            fixed_dates=fixed_dates or None,
        )

        for index in future:
            active.execute(
                "DELETE FROM plan_items WHERE training_id = ? AND kind = 'train' "
                "AND round_index = ? AND status = 'planned'",
                (training_id, index),
            )
        now = _now()
        anchor_row = active.execute(
            "SELECT created_at FROM trainings WHERE id = ?", (training_id,)
        ).fetchone()
        anchor = parse_local_date(anchor_row["created_at"] if anchor_row else None, local_today())
        rows: list[tuple[Any, ...]] = []
        for keys, index in zip(composition.sessions, future):
            due = dates.get(index, local_today())
            for key in keys:
                stat = by_key.get(key)
                minutes = stat.minutes if stat else _planned_minutes(None)
                rows.append(
                    _pace_row_values(training_id, key, index, "train", due, anchor, minutes, now)
                )
        active.executemany(
            "INSERT OR IGNORE INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        if own:
            active.commit()
        logger.info(
            "recompose_future_sessions: training %s sessions %s recomposed (accuracy=%s)",
            training_id,
            future,
            accuracy,
        )
        return True
    finally:
        if own:
            active.close()


def append_session_cycle(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any] | None:
    """终测未通过 → 追加一轮同规格会话周期（design D4，user-defined-training-plan 2.4）。

    N 次会话重新配比：已稳定项（连续达标 streak）进入已知巩固池；周期小测与
    终测随新一轮排期继续。仅对 session_ratio 模式生效；返回轮次信息或 None。
    """
    active = _connect(conn)
    own = conn is None
    try:
        training = active.execute(
            "SELECT schedule_mode, goal_json, created_at FROM trainings WHERE id = ?",
            (training_id,),
        ).fetchone()
        if training is None or str(training["schedule_mode"] or "") != "session_ratio":
            return None

        from src.core.mastery import MASTERY_STREAK

        horizon_days, session_count = _pace_from_goal(training["goal_json"])
        stats = _item_stats(active, training_id)
        if not stats:
            return None
        by_key = {stat.item_key: stat for stat in stats}

        base = active.execute(
            "SELECT COALESCE(MAX(round_index), 0) AS max_index FROM plan_items "
            "WHERE training_id = ? AND kind = 'train'",
            (training_id,),
        ).fetchone()["max_index"]
        last_due = active.execute(
            "SELECT COALESCE(MAX(due_date), ?) AS last_due FROM plan_items "
            "WHERE training_id = ? AND kind = 'train'",
            (local_today().isoformat(), training_id),
        ).fetchone()["last_due"]
        cycle_anchor = parse_local_date(last_due, local_today())

        # 最近一次会话正确率 → 恒稳控制器；已稳定项进已知巩固池
        accuracy = _session_accuracy(active, training_id, int(base))
        stable = [stat.item_key for stat in stats if stat.consecutive_passes >= MASTERY_STREAK]
        composition = compose_sessions(
            stats,
            session_count,
            anchor=cycle_anchor,
            horizon_days=horizon_days,
            accuracy=accuracy,
            stable_keys=stable,
        )

        now = _now()
        rows: list[tuple[Any, ...]] = []
        for position, (keys, due) in enumerate(zip(composition.sessions, composition.dates), start=1):
            index = int(base) + position
            for key in keys:
                stat = by_key.get(key)
                rows.append(
                    _pace_row_values(
                        training_id, key, index, "train", due, cycle_anchor,
                        stat.minutes if stat else _planned_minutes(None), now,
                    )
                )
        quiz_dates = quiz_due_dates(cycle_anchor, max(composition.dates))
        for quiz_date in quiz_dates:
            rows.append(
                _pace_row_values(
                    training_id, f"quiz-{quiz_date.isoformat()}", 0, "assessment",
                    quiz_date, cycle_anchor, 0, now,
                )
            )
        final_date = max(composition.dates)
        rows.append(
            _pace_row_values(
                training_id, f"final-{final_date.isoformat()}", int(base) + session_count,
                "assessment", final_date, cycle_anchor, 0, now,
            )
        )
        active.executemany(
            "INSERT OR IGNORE INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        if own:
            active.commit()
        logger.info(
            "append_session_cycle: training %s +%d session(s) from %s, accuracy=%s",
            training_id,
            session_count,
            cycle_anchor,
            accuracy,
        )
        return {
            "appended_sessions": session_count,
            "first_due": min(composition.dates).isoformat(),
            "last_due": final_date.isoformat(),
            "accuracy": accuracy,
        }
    finally:
        if own:
            active.close()


def drawable_questions(
    training_id: int,
    *,
    today: date | None = None,
    limit: int = 0,
    conn: sqlite3.Connection | None = None,
    include_cooldown: bool = False,
) -> list[dict[str, Any]]:
    """冷却期已过的题目（可供抽取测验题）。不到 14 天的题目 MUST NOT 出现在这里。

    ``include_cooldown=True`` 仅供终测（trigger='final'）绕过冷却期——终测要覆盖
    全部必修项，冷却期不得把近期练过的题挡在门外。
    """
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        sql = (
            "SELECT * FROM question_bank WHERE training_id = ? AND status = 'active' "
        )
        params: list[Any] = [training_id]
        if not include_cooldown:
            sql += "AND (cooldown_until IS NULL OR cooldown_until <= ?) "
            params.append(effective_today.isoformat())
        sql += "ORDER BY practiced_count DESC, last_practiced_at"
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
    "append_session_cycle",
    "complete_tasks",
    "drawable_questions",
    "ensure_plan",
    "generate_plan",
    "generate_plan_v2",
    "generate_plan_v21",
    "has_plan",
    "item_id_for",
    "item_key_for",
    "next_due_date",
    "plan_progress",
    "recompose_future_sessions",
    "register_in_question_bank",
    "skip_task",
    "today_summary",
    "today_tasks",
]
