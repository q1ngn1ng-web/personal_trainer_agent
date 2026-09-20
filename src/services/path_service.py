"""训练路径生成：骨架草案、预算校验、训练项落库、确认与版本。

对应 OpenSpec change ``training-path-generation`` 与 ADR-0006 / 0009 / 0010 / 0011。
核心约束：

* **两层生成**：骨架一次生成并由用户确认（阶段细节滚动生成留待后续迭代）
* **预算由规则算**：`周期 × 每周频次 × 每次时长` 是硬约束，超支直接拒绝
* **不让模型排日期**：路径只表达顺序与阶段
* 已掌握跳过、边缘为重点、未达先铺垫（消费理解边缘定位的结果）
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.models import PathStage, TrainingItem, TrainingPath
from src.db.sqlite import get_connection
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY
from src.services import edge_service, source_service as svc

logger = logging.getLogger("src.services.path_service")

#: 超支时允许的重试次数（让模型压缩一次）
MAX_BUDGET_RETRIES: int = 1

#: 明显过松的提示阈值
UNDERUSE_RATIO: float = 0.5


@dataclass
class PlannedItem:
    """草案里的一个训练项。"""

    title: str
    item_type: str
    difficulty: int
    knowledge_point: str
    minutes: int
    source_chunk_ids: list[int] = field(default_factory=list)
    difficulty_basis: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlannedStage:
    """草案里的一个阶段。"""

    title: str
    goal: str
    items: list[PlannedItem] = field(default_factory=list)

    @property
    def estimated_minutes(self) -> int:
        return sum(item.minutes for item in self.items)

    def type_distribution(self) -> dict[str, int]:
        distribution: dict[str, int] = {}
        for item in self.items:
            distribution[item.item_type] = distribution.get(item.item_type, 0) + 1
        return distribution


@dataclass
class PathSkeleton:
    """路径骨架草案。"""

    training_id: int
    horizon_weeks: int
    weekly_frequency: int
    daily_budget_minutes: int
    stages: list[PlannedStage] = field(default_factory=list)
    mode: str = "mastery"
    fallback_used: bool = False

    @property
    def planned_minutes(self) -> int:
        return sum(stage.estimated_minutes for stage in self.stages)

    @property
    def budget_minutes(self) -> int:
        return self.horizon_weeks * self.weekly_frequency * self.daily_budget_minutes

    def item_count(self) -> int:
        return sum(len(stage.items) for stage in self.stages)


@dataclass
class BudgetReport:
    """预算校验结果。"""

    ok: bool
    budget_minutes: int
    planned_minutes: int
    over_by: int = 0
    too_light: bool = False
    message: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def check_budget(skeleton: PathSkeleton) -> BudgetReport:
    """预算校验（规则层，不由模型估）。"""
    budget = skeleton.budget_minutes
    planned = skeleton.planned_minutes
    if planned > budget:
        return BudgetReport(
            ok=False,
            budget_minutes=budget,
            planned_minutes=planned,
            over_by=planned - budget,
            message=f"路径总时长 {planned} 分钟超出预算 {budget} 分钟，需压缩或调整投入",
        )
    too_light = planned < budget * UNDERUSE_RATIO
    return BudgetReport(
        ok=True,
        budget_minutes=budget,
        planned_minutes=planned,
        too_light=too_light,
        message="路径明显偏松，可考虑增加内容或减少投入" if too_light else "预算校验通过",
    )


def _edge_context(
    training_id: int,
) -> tuple[list[dict[str, Any]], dict[str, list[int]], list[str]]:
    """汇总边缘定位结果、「知识点 → 切片 ID」映射，以及来源里的知识点名单。"""
    probe = edge_service.load_probe(training_id)
    states: list[dict[str, Any]] = []
    if probe is not None:
        for item in probe.items:
            states.append(
                {
                    "knowledge_point": item.knowledge_point,
                    "heading_path": item.heading_path,
                    "state": item.state,
                    "difficulty": item.difficulty,
                    "reason": item.reason,
                }
            )

    mapping: dict[str, list[int]] = {}
    active = _connect()
    try:
        rows = active.execute(
            """
            SELECT c.id AS chunk_id, c.heading_path
            FROM source_chunks c
            JOIN sources s ON s.id = c.source_id
            WHERE s.training_id = ? AND s.enabled = 1
            ORDER BY c.id
            """,
            (training_id,),
        ).fetchall()
    finally:
        active.close()
    for row in rows:
        heading = (row["heading_path"] or "（未分节）").strip()
        leaf = heading.split(" > ")[-1][:60]
        mapping.setdefault(leaf, []).append(int(row["chunk_id"]))
        mapping.setdefault(heading, []).append(int(row["chunk_id"]))
    chunk_points = list(dict.fromkeys(mapping.keys()))
    return states, mapping, chunk_points


def _fallback_skeleton(
    training_id: int,
    states: list[dict[str, Any]],
    chunk_points: list[str] | None = None,
) -> PathSkeleton:
    """模型不可用时的兜底：按边缘定位结果直接排一条最朴素的路径。"""
    edge_points = [s for s in states if s.get("state") == "edge"] or [s for s in states if s.get("state") != "mastered"]
    unreached = [s for s in states if s.get("state") == "unreached"]

    # 没做探测（或探测为空）时，退回用来源知识点名单排一条最朴素的路径
    if not edge_points and not unreached and chunk_points:
        edge_points = [
            {"knowledge_point": name, "difficulty": 2} for name in chunk_points[:8]
        ]

    stages: list[PlannedStage] = []
    if unreached:
        stages.append(
            PlannedStage(
                title="前置铺垫",
                goal="把还没入门的知识点补到能听懂的程度",
                items=[
                    PlannedItem(
                        title=f"基础：{state['knowledge_point']}",
                        item_type="prerequisite",
                        difficulty=1,
                        knowledge_point=state["knowledge_point"],
                        minutes=20,
                        difficulty_basis={"type": "prerequisite", "points": 1, "steps": 1, "hint": True},
                    )
                    for state in unreached
                ],
            )
        )
    if not edge_points and not stages:
        return PathSkeleton(
            training_id=training_id,
            horizon_weeks=1,
            weekly_frequency=3,
            daily_budget_minutes=15,
            stages=[],
            fallback_used=True,
        )
    if edge_points:
        stages.append(
            PlannedStage(
                title="边缘强化",
                goal="在理解边缘上反复练，直到能独立讲清楚",
                items=[
                    PlannedItem(
                        title=f"练习：{state['knowledge_point']}",
                        item_type="comprehension",
                        difficulty=max(2, min(4, int(state.get("difficulty") or 2))),
                        knowledge_point=state["knowledge_point"],
                        minutes=20,
                        difficulty_basis={"type": "comprehension", "points": 1, "steps": 2, "hint": False},
                    )
                    for state in edge_points
                ],
            )
        )
    return PathSkeleton(
        training_id=training_id,
        horizon_weeks=2,
        weekly_frequency=5,
        daily_budget_minutes=30,
        stages=stages,
        fallback_used=True,
    )


def generate_skeleton(
    training_id: int, *, topic: str, goal: Any = None, conn: sqlite3.Connection | None = None
) -> tuple[PathSkeleton, BudgetReport]:
    """生成路径骨架并做预算校验。超支时拒绝并按规则压缩重试一次。"""
    states, chunk_map, chunk_points = _edge_context(training_id)
    knowledge_points = sorted({state["knowledge_point"] for state in states})

    variables = {
        "goal": json.dumps(
            {
                "topic": topic,
                "goal": goal or {},
            },
            ensure_ascii=False,
        ),
        "edge_states": json.dumps(states, ensure_ascii=False),
        "knowledge_points": json.dumps(knowledge_points, ensure_ascii=False),
    }

    skeleton: PathSkeleton | None = None
    for attempt in range(MAX_BUDGET_RETRIES + 1):
        try:
            result = complete("path_skeleton", variables, schema=SCHEMA_REGISTRY["path_skeleton"])
            output = result.get("output_json") or {}
        except Exception as exc:
            logger.warning("generate_skeleton: LLM unavailable (%s), using fallback", exc)
            from src.llm.client import log_llm_failure

            log_llm_failure("path_skeleton", json.dumps(variables, ensure_ascii=False), exc)
            output = {}

        if not output:
            skeleton = _fallback_skeleton(training_id, states, chunk_points)
            break

        skeleton = _skeleton_from_output(training_id, output)
        report = check_budget(skeleton)
        if report.ok:
            break
        logger.warning("generate_skeleton: over budget (attempt %d), retrying", attempt + 1)
        variables["goal"] = variables["goal"] + "\n\n上一次方案超出时间预算，请压缩：" + report.message

    if skeleton is None:  # pragma: no cover - 循环必然赋值
        skeleton = _fallback_skeleton(training_id, states, chunk_points)

    _attach_sources(skeleton, chunk_map)
    return skeleton, check_budget(skeleton)


def _skeleton_from_output(training_id: int, output: dict[str, Any]) -> PathSkeleton:
    stages: list[PlannedStage] = []
    for raw_stage in output.get("stages") or []:
        items = [
            PlannedItem(
                title=str(raw.get("title", "")).strip(),
                item_type=str(raw.get("item_type", "memory")),
                difficulty=int(raw.get("difficulty", 2) or 2),
                knowledge_point=str(raw.get("knowledge_point", "")).strip(),
                minutes=int(raw.get("minutes", 15) or 15),
                difficulty_basis={
                    "type": str(raw.get("item_type", "memory")),
                    "points": 1,
                    "steps": 1,
                    "hint": False,
                },
            )
            for raw in (raw_stage.get("items") or [])
        ]
        stages.append(
            PlannedStage(
                title=str(raw_stage.get("title", "")).strip() or "阶段",
                goal=str(raw_stage.get("goal", "")).strip(),
                items=items,
            )
        )
    return PathSkeleton(
        training_id=training_id,
        horizon_weeks=int(output.get("horizon_weeks", 2) or 2),
        weekly_frequency=int(output.get("weekly_frequency", 5) or 5),
        daily_budget_minutes=int(output.get("daily_budget_minutes", 30) or 30),
        stages=stages,
    )


def _attach_sources(skeleton: PathSkeleton, chunk_map: dict[str, list[int]]) -> None:
    """把训练项回指到来源切片（A4.1）。找不到就留空，不编造。"""
    for stage in skeleton.stages:
        for item in stage.items:
            item.source_chunk_ids = list(chunk_map.get(item.knowledge_point, []))[:5]


def save_skeleton(
    skeleton: PathSkeleton, *, conn: sqlite3.Connection | None = None
) -> TrainingPath:
    """把骨架落库。同训练已有 draft 路径时替换；已 confirmed 的不动。"""
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "DELETE FROM training_items WHERE stage_id IN "
            "(SELECT id FROM path_stages WHERE path_id IN "
            "(SELECT id FROM training_paths WHERE training_id = ? AND status = 'draft'))",
            (skeleton.training_id,),
        )
        active.execute(
            "DELETE FROM path_stages WHERE path_id IN "
            "(SELECT id FROM training_paths WHERE training_id = ? AND status = 'draft')",
            (skeleton.training_id,),
        )
        active.execute(
            "DELETE FROM training_paths WHERE training_id = ? AND status = 'draft'",
            (skeleton.training_id,),
        )
        row = active.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM training_paths WHERE training_id = ?",
            (skeleton.training_id,),
        ).fetchone()
        version = int(row["v"] or 0) + 1
        cursor = active.execute(
            "INSERT INTO training_paths (training_id, version, status, mode, horizon_weeks, "
            "weekly_frequency, daily_budget_minutes, budget_minutes, planned_minutes, created_at) "
            "VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)",
            (
                skeleton.training_id,
                version,
                skeleton.mode,
                skeleton.horizon_weeks,
                skeleton.weekly_frequency,
                skeleton.daily_budget_minutes,
                skeleton.budget_minutes,
                skeleton.planned_minutes,
                _now(),
            ),
        )
        path_id = int(cursor.lastrowid)
        for stage_index, stage in enumerate(skeleton.stages, start=1):
            stage_cursor = active.execute(
                "INSERT INTO path_stages (path_id, ordinal, title, goal, estimated_minutes) "
                "VALUES (?, ?, ?, ?, ?)",
                (path_id, stage_index, stage.title, stage.goal, stage.estimated_minutes),
            )
            stage_id = int(stage_cursor.lastrowid)
            for item_index, item in enumerate(stage.items, start=1):
                active.execute(
                    "INSERT INTO training_items (stage_id, ordinal, title, item_type, difficulty_tier, "
                    "difficulty_basis, knowledge_point, source_chunk_ids, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (
                        stage_id,
                        item_index,
                        item.title,
                        item.item_type,
                        item.difficulty,
                        json.dumps(item.difficulty_basis, ensure_ascii=False),
                        item.knowledge_point,
                        json.dumps(item.source_chunk_ids),
                        _now(),
                    ),
                )
        if own:
            active.commit()
        saved = active.execute("SELECT * FROM training_paths WHERE id = ?", (path_id,)).fetchone()
    finally:
        if own:
            active.close()
    return TrainingPath.from_row(saved)


def load_path(training_id: int, conn: sqlite3.Connection | None = None) -> TrainingPath | None:
    """取该训练最新的路径（优先 confirmed，其次 draft）。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT * FROM training_paths WHERE training_id = ? "
            "ORDER BY (status = 'confirmed') DESC, version DESC LIMIT 1",
            (training_id,),
        ).fetchone()
    finally:
        if own:
            active.close()
    return TrainingPath.from_row(row) if row else None


def load_stages(path_id: int, conn: sqlite3.Connection | None = None) -> list[PathStage]:
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM path_stages WHERE path_id = ? ORDER BY ordinal", (path_id,)
        ).fetchall()
    finally:
        if own:
            active.close()
    return [PathStage.from_row(row) for row in rows]


def load_items(stage_id: int, conn: sqlite3.Connection | None = None) -> list[TrainingItem]:
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM training_items WHERE stage_id = ? ORDER BY ordinal", (stage_id,)
        ).fetchall()
    finally:
        if own:
            active.close()
    return [TrainingItem.from_row(row) for row in rows]


def confirm_path(training_id: int, conn: sqlite3.Connection | None = None) -> TrainingPath | None:
    """用户确认路径：写确认时间，并把同训练的其他版本标为 superseded。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT * FROM training_paths WHERE training_id = ? AND status = 'draft' "
            "ORDER BY version DESC LIMIT 1",
            (training_id,),
        ).fetchone()
        if row is None:
            return None
        active.execute(
            "UPDATE training_paths SET status = 'superseded' WHERE training_id = ? AND status = 'confirmed'",
            (training_id,),
        )
        active.execute(
            "UPDATE training_paths SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        if own:
            active.commit()
        saved = active.execute("SELECT * FROM training_paths WHERE id = ?", (row["id"],)).fetchone()
    finally:
        if own:
            active.close()
    return TrainingPath.from_row(saved)


def adjust_budget(
    training_id: int,
    *,
    horizon_weeks: int | None = None,
    weekly_frequency: int | None = None,
    daily_budget_minutes: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> TrainingPath | None:
    """用户微调投入参数（ADR-0006：参数由用户定，不由模型定）。"""
    path = load_path(training_id, conn=conn)
    if path is None:
        return None
    horizon = horizon_weeks or path.horizon_weeks or 1
    frequency = weekly_frequency or path.weekly_frequency or 1
    budget = daily_budget_minutes or path.daily_budget_minutes or 1
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE training_paths SET horizon_weeks = ?, weekly_frequency = ?, "
            "daily_budget_minutes = ?, budget_minutes = ? WHERE id = ?",
            (horizon, frequency, budget, horizon * frequency * budget, path.id),
        )
        if own:
            active.commit()
        saved = active.execute("SELECT * FROM training_paths WHERE id = ?", (path.id,)).fetchone()
    finally:
        if own:
            active.close()
    return TrainingPath.from_row(saved)


def validate_item_chunk_links(training_id: int, conn: sqlite3.Connection | None = None) -> int:
    """校验所有训练项的切片回指是否真实存在，返回被清理掉的条数（A4.1）。"""
    path = load_path(training_id, conn=conn)
    if path is None:
        return 0
    active = _connect(conn)
    own = conn is None
    dropped_total = 0
    try:
        valid_ids = svc.existing_chunk_ids_for_training(training_id, conn=active)
        for stage in load_stages(path.id, conn=active):
            for item in load_items(stage.id, conn=active):
                raw = item.source_chunk_ids or []
                kept = [int(x) for x in raw if isinstance(x, (int, str)) and str(x).isdigit() and int(x) in valid_ids]
                if len(kept) != len(raw):
                    dropped_total += len(raw) - len(kept)
                    active.execute(
                        "UPDATE training_items SET source_chunk_ids = ? WHERE id = ?",
                        (json.dumps(kept), item.id),
                    )
        if dropped_total:
            logger.warning("validate_item_chunk_links: dropped %d stale chunk links", dropped_total)
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return dropped_total


def current_stage(training_id: int, conn: sqlite3.Connection | None = None) -> tuple[PathStage | None, list[TrainingItem]]:
    """取当前该练的阶段与其训练项：优先第一个未完成的阶段，其次最后一个阶段。"""
    path = load_path(training_id, conn=conn)
    if path is None:
        return None, []
    stages = load_stages(path.id, conn=conn)
    if not stages:
        return None, []

    for stage in stages:
        items = load_items(stage.id, conn=conn)
        if any(item.status in ("pending", "in_progress") for item in items):
            return stage, items
    last = stages[-1]
    return last, load_items(last.id, conn=conn)


def today_tasks(
    training_id: int, *, limit: int = 5, conn: sqlite3.Connection | None = None
) -> dict[str, list[TrainingItem]]:
    """今日任务：当前阶段待练的训练项 + 之前阶段已完成但仍需复习的项。

    这是新流程的数据源——老流程读文件系统里的 `04_复习日历.md`，
    新流程没有那十份文件，所以必须从 `training_items` 取。
    """
    stage, items = current_stage(training_id, conn=conn)
    if stage is None:
        return {"new": [], "review": []}

    pending = [item for item in items if item.status in ("pending", "in_progress")]
    passed = [item for item in items if item.status == "passed"]
    new_items = pending[:limit]
    review_items = passed[: max(0, min(2, limit - len(new_items)))]
    return {"new": new_items, "review": review_items}


def mark_item(
    item_id: int, status: str, conn: sqlite3.Connection | None = None
) -> TrainingItem | None:
    """更新训练项状态（勾选任务卡时调用）。"""
    if status not in ("pending", "in_progress", "passed", "failed"):
        raise ValueError(f"invalid item status: {status}")
    active = _connect(conn)
    own = conn is None
    try:
        active.execute("UPDATE training_items SET status = ? WHERE id = ?", (status, item_id))
        if own:
            active.commit()
        row = active.execute("SELECT * FROM training_items WHERE id = ?", (item_id,)).fetchone()
    finally:
        if own:
            active.close()
    return TrainingItem.from_row(row) if row else None


__all__ = [
    "MAX_BUDGET_RETRIES",
    "UNDERUSE_RATIO",
    "BudgetReport",
    "PathSkeleton",
    "PlannedItem",
    "PlannedStage",
    "adjust_budget",
    "check_budget",
    "confirm_path",
    "current_stage",
    "generate_skeleton",
    "load_items",
    "load_path",
    "load_stages",
    "mark_item",
    "save_skeleton",
    "today_tasks",
    "validate_item_chunk_links",
]
