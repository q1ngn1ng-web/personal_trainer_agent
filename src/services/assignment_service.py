"""培训任务分发：管理层发布任务 → 目标人群展开 → 员工接收并自动生成个人训练。

对应 change `org-and-roles` 的任务 5.x 与 ADR-0011 / 0013 / 0022：

* **四要素缺一不可**：资料范围 / 验收标准 / 目标人群 / 截止日期（规则层校验，ADR-0001）
* **目标人群由规则展开**（`all` / `department` / `user`），不交给 LLM
* **验收标准来自任务**，员工侧字段来源标记 `assigned`，员工不能改（任务 5.4）
* 员工接收 → 创建个人训练 + 复制任务资料 + 生成 5 轮计划（内容层按组织、进度层按人，ADR-0013）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.connection import Connection, transaction
from src.services import edge_service, org_service, path_service, plan_service, source_service

logger = logging.getLogger("src.services.assignment_service")

#: 任务自动生成的兜底路径里最多放几个知识点
_FALLBACK_ITEMS: int = 8
#: 每个训练项的默认时长（分钟）
_ITEM_MINUTES: int = 10


@dataclass
class AssignmentCheck:
    """四要素校验结果。"""

    ok: bool
    missing: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "缺少：" + "、".join(self.missing) if self.missing else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()




def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def check_assignment(
    *,
    source_ids: list[int] | None,
    acceptance: Any,
    target_type: str | None,
    target_value: Any,
    due_date: str | None,
) -> AssignmentCheck:
    """四要素校验：资料范围 / 验收标准 / 目标人群 / 截止日期。"""
    missing: list[str] = []
    if not source_ids:
        missing.append("资料范围")
    if not _json_dict(acceptance):
        missing.append("验收标准")
    if target_type not in ("all", "department", "user"):
        missing.append("目标人群")
    elif target_type in ("department", "user") and target_value in (None, ""):
        missing.append("目标人群")
    if not str(due_date or "").strip():
        missing.append("截止日期")
    return AssignmentCheck(ok=not missing, missing=missing)


def create_assignment(
    org_id: int,
    *,
    title: str,
    source_ids: list[int],
    acceptance: dict[str, Any],
    target_type: str,
    target_value: Any = None,
    due_date: str | None = None,
    description: str = "",
    created_by: int | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """创建任务草案；四要素不全直接拒绝（不落库）。"""
    check = check_assignment(
        source_ids=source_ids,
        acceptance=acceptance,
        target_type=target_type,
        target_value=target_value,
        due_date=due_date,
    )
    if not check.ok:
        raise ValueError(f"任务要素不全：{check.message}")
    label = str(title or "").strip()
    if not label:
        raise ValueError("任务标题不能为空")

    with transaction(conn) as active:
        cursor = active.execute(
            "INSERT INTO assignments (org_id, title, description, source_ids, acceptance, "
            "target_type, target_value, due_date, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (
                int(org_id),
                label,
                description or None,
                json.dumps([int(value) for value in source_ids]),
                json.dumps(acceptance, ensure_ascii=False),
                target_type,
                str(target_value) if target_value not in (None, "") else None,
                str(due_date),
                created_by,
                _now(),
            ),
        )
        row = active.execute(
            "SELECT * FROM assignments WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def expand_targets(
    assignment: dict[str, Any], *, conn: Connection | None = None
) -> list[int]:
    """把目标人群展开成 user_id 列表（规则层）。"""
    target_type = str(assignment.get("target_type") or "")
    raw_value = assignment.get("target_value")
    org_id = int(assignment["org_id"])
    if target_type == "user":
        return [int(raw_value)] if raw_value not in (None, "") else []
    if target_type == "department":
        if raw_value in (None, ""):
            return []
        rows = org_service.list_members(org_id, department_id=int(raw_value), conn=conn)
        return [int(row["user_id"]) for row in rows]
    rows = org_service.list_members(org_id, conn=conn)
    return [int(row["user_id"]) for row in rows]


def publish_assignment(
    assignment_id: int, *, conn: Connection | None = None
) -> dict[str, Any]:
    """发布任务：校验四要素 → 展开目标人群 → 落库（幂等）。"""
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM assignments WHERE id = ?", (int(assignment_id),)
        ).fetchone()
        if row is None:
            raise ValueError(f"assignment not found: {assignment_id}")
        assignment = dict(row)
        check = check_assignment(
            source_ids=_json_list(assignment.get("source_ids")),
            acceptance=assignment.get("acceptance"),
            target_type=assignment.get("target_type"),
            target_value=assignment.get("target_value"),
            due_date=assignment.get("due_date"),
        )
        if not check.ok:
            raise ValueError(f"任务要素不全：{check.message}")
        targets = expand_targets(assignment, conn=active)
        if not targets:
            raise ValueError("目标人群为空：没有命中任何成员")
        active.executemany(
            "INSERT OR IGNORE INTO assignment_targets (assignment_id, user_id) VALUES (?, ?)",
            [(int(assignment_id), user_id) for user_id in targets],
        )
        active.execute(
            "UPDATE assignments SET status = 'published', published_at = ? WHERE id = ?",
            (_now(), int(assignment_id)),
        )
        updated = active.execute(
            "SELECT * FROM assignments WHERE id = ?", (int(assignment_id),)
        ).fetchone()
    logger.info("publish_assignment: #%s → %d 个目标成员", assignment_id, len(targets))
    return dict(updated)


def list_assignments(
    org_id: int, *, status: str | None = None, conn: Connection | None = None
) -> list[dict[str, Any]]:
    with transaction(conn) as active:
        sql = "SELECT * FROM assignments WHERE org_id = ?"
        params: list[Any] = [int(org_id)]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC"
        rows = active.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_targets(
    assignment_id: int, *, conn: Connection | None = None
) -> list[dict[str, Any]]:
    """目标人群 + 是否已接收（管理端看进度用）。"""
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT t.user_id, u.email, u.display_name, r.training_id, r.received_at "
            "FROM assignment_targets t JOIN users u ON u.id = t.user_id "
            "LEFT JOIN assignment_receipts r ON r.assignment_id = t.assignment_id "
            "AND r.user_id = t.user_id WHERE t.assignment_id = ? ORDER BY t.user_id",
            (int(assignment_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def pending_for_user(
    user_id: int, *, conn: Connection | None = None
) -> list[dict[str, Any]]:
    """待接收任务：已发布、命中该用户、且还没接收。"""
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT a.* FROM assignments a "
            "JOIN assignment_targets t ON t.assignment_id = a.id "
            "LEFT JOIN assignment_receipts r ON r.assignment_id = a.id AND r.user_id = t.user_id "
            "WHERE t.user_id = ? AND a.status = 'published' AND r.id IS NULL "
            "ORDER BY a.due_date, a.id",
            (int(user_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _copy_sources(
    active: Connection, *, assignment: dict[str, Any], training_id: int
) -> list[int]:
    """把任务的资料范围复制成该训练自己的资料（ADR-0013：内容按组织、进度按人）。"""
    copied: list[int] = []
    for source_id in _json_list(assignment.get("source_ids")):
        original = source_service.get_source(int(source_id), conn=active)
        if original is None:
            continue
        created = source_service.create_source(
            training_id,
            type=original.type,
            title=f"{original.title}（任务分享）",
            origin=f"assignment#{assignment['id']}",
            origin_url=original.origin_url,
            content=original.snapshot_text,
            scope="org_shared",
            conn=active,
        )
        source_service.parse_source(int(created.id), conn=active)
        copied.append(int(created.id))
    return copied


def _goal_snapshot(assignment: dict[str, Any]) -> dict[str, Any]:
    """任务目的快照：验收标准来自任务，字段来源标记 `assigned`（员工不可改）。"""
    acceptance = _json_dict(assignment.get("acceptance"))
    return {
        "content": str(assignment["title"]),
        "level": "会用",
        "acceptance": acceptance,
        "field_sources": {"content": "assigned", "acceptance": "assigned"},
        "schema_version": "1.0.0",
        "assigned_from": int(assignment["id"]),
    }


def _bootstrap_training(
    active: Connection, *, assignment: dict[str, Any], user_id: int
) -> int:
    """为接收人创建个人训练：写目的 → 复制资料 → 生成 5 轮计划。"""
    from src.db import queries

    training = queries.create_training(
        topic=str(assignment["title"]), status="confirmed", conn=active
    )
    queries.update_training(
        int(training.id),
        org_id=int(assignment["org_id"]),
        owner_user_id=int(user_id),
        goal_json=_goal_snapshot(assignment),
        conn=active,
    )
    _copy_sources(active, assignment=assignment, training_id=int(training.id))

    points = edge_service.build_knowledge_points(int(training.id), conn=active)
    if points:
        items = [
            path_service.PlannedItem(
                title=f"练习：{point.name}",
                item_type="comprehension",
                difficulty=2,
                knowledge_point=point.name,
                minutes=_ITEM_MINUTES,
            )
            for point in points[:_FALLBACK_ITEMS]
        ]
        skeleton = path_service.PathSkeleton(
            training_id=int(training.id),
            horizon_weeks=2,
            weekly_frequency=5,
            daily_budget_minutes=30,
            stages=[
                path_service.PlannedStage(
                    title="任务训练", goal=str(assignment["title"]), items=items
                )
            ],
            fallback_used=True,
        )
        path_service.save_skeleton(skeleton, conn=active)
        path_service.validate_item_chunk_links(int(training.id), conn=active)
        plan_service.generate_plan(int(training.id), conn=active)
    return int(training.id)


def accept_assignment(
    assignment_id: int, user_id: int, *, conn: Connection | None = None
) -> dict[str, Any]:
    """员工接收任务：仅目标人群可接收；重复接收幂等（直接返回已有训练）。"""
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM assignments WHERE id = ?", (int(assignment_id),)
        ).fetchone()
        if row is None:
            raise ValueError(f"assignment not found: {assignment_id}")
        assignment = dict(row)
        if str(assignment.get("status")) != "published":
            raise ValueError("任务尚未发布")
        target = active.execute(
            "SELECT 1 FROM assignment_targets WHERE assignment_id = ? AND user_id = ?",
            (int(assignment_id), int(user_id)),
        ).fetchone()
        if target is None:
            raise PermissionError("这个任务不在你的名下")
        existing = active.execute(
            "SELECT * FROM assignment_receipts WHERE assignment_id = ? AND user_id = ?",
            (int(assignment_id), int(user_id)),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        training_id = _bootstrap_training(active, assignment=assignment, user_id=int(user_id))
        active.execute(
            "INSERT INTO assignment_receipts (assignment_id, user_id, training_id, received_at) "
            "VALUES (?, ?, ?, ?)",
            (int(assignment_id), int(user_id), training_id, _now()),
        )
        receipt = active.execute(
            "SELECT * FROM assignment_receipts WHERE assignment_id = ? AND user_id = ?",
            (int(assignment_id), int(user_id)),
        ).fetchone()
    logger.info(
        "accept_assignment: 用户 %s 接收任务 #%s → 训练 #%s", user_id, assignment_id, training_id
    )
    return dict(receipt)


__all__ = [
    "AssignmentCheck",
    "accept_assignment",
    "check_assignment",
    "create_assignment",
    "expand_targets",
    "list_assignments",
    "list_targets",
    "pending_for_user",
    "publish_assignment",
]
