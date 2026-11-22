"""组织与成员服务：组织、用户、成员关系，以及登录后要用的身份上下文。

对应 change `org-and-roles` 的任务 1.1 / 1.3 / 1.4 与 ADR-0019（个人版只有一个默认组织）。
**认证本身不在本模块**：按 ADR-0014 要复用成熟组件，选型待 ADR-0022，这里只负责数据模型与角色解析。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.core.permissions import Role, Viewer, coerce_role
from src.db.connection import Connection, transaction

logger = logging.getLogger("src.services.org_service")

#: 个人版的默认组织（老数据全部归入这里）
DEFAULT_ORG_ID: int = 1
DEFAULT_ORG_NAME: str = "默认组织"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()




def ensure_default_org(*, conn: Connection | None = None) -> int:
    """确保默认组织存在（幂等），返回它的 id。"""
    with transaction(conn) as active:
        active.execute(
            "INSERT OR IGNORE INTO organizations (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
            (DEFAULT_ORG_ID, DEFAULT_ORG_NAME, "default", _now()),
        )
        return DEFAULT_ORG_ID


def create_organization(
    name: str, *, slug: str | None = None, conn: Connection | None = None
) -> dict[str, Any]:
    """建一个组织（企业版入口；个人版不用）。"""
    label = str(name or "").strip()
    if not label:
        raise ValueError("组织名不能为空")
    key = str(slug or "").strip() or label.lower().replace(" ", "-")
    with transaction(conn) as active:
        cursor = active.execute(
            "INSERT INTO organizations (name, slug, created_at) VALUES (?, ?, ?)",
            (label, key, _now()),
        )
        row = active.execute(
            "SELECT * FROM organizations WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def create_user(
    email: str,
    *,
    display_name: str | None = None,
    password_hash: str | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """建用户。``password_hash`` 由认证组件产出（ADR-0014），这里只负责存。"""
    address = str(email or "").strip().lower()
    if "@" not in address:
        raise ValueError("邮箱格式不正确")
    with transaction(conn) as active:
        cursor = active.execute(
            "INSERT INTO users (email, display_name, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (address, display_name or address.split("@")[0], password_hash, _now()),
        )
        row = active.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def add_membership(
    user_id: int,
    org_id: int = DEFAULT_ORG_ID,
    *,
    department_id: int | None = None,
    role: Role | str = Role.MEMBER,
    status: str = "active",
    invited_by: int | None = None,
    admin_quota: int | None = None,
    admin_can_remove: int | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """把用户加入组织并给定角色（同一组织只能有一条成员关系）。"""
    normalized = coerce_role(role)
    if status not in ("active", "invited", "disabled"):
        raise ValueError(f"unknown membership status: {status!r}")
    with transaction(conn) as active:
        if int(org_id) == DEFAULT_ORG_ID:
            # 个人版默认组织必须存在，否则 memberships 的外键会失败
            ensure_default_org(conn=active)
        active.execute(
            "INSERT INTO memberships (user_id, org_id, department_id, role, status, invited_by, "
            "admin_quota, admin_can_remove, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, org_id) DO UPDATE SET role = excluded.role, status = excluded.status, "
            "department_id = excluded.department_id, invited_by = excluded.invited_by, "
            "admin_quota = excluded.admin_quota, admin_can_remove = excluded.admin_can_remove",
            (
                int(user_id), int(org_id), department_id, normalized.value, status, invited_by,
                admin_quota, 0 if admin_can_remove is None else int(admin_can_remove), _now(),
            ),
        )
        row = active.execute(
            "SELECT * FROM memberships WHERE user_id = ? AND org_id = ?",
            (int(user_id), int(org_id)),
        ).fetchone()
    return dict(row)


def resolve_viewer(
    user_id: int, *, org_id: int | None = None, conn: Connection | None = None
) -> Viewer:
    """按用户解析身份上下文（登录后调用）。

    一个人可能有多条成员关系（多部门 / 借调，ADR-0022）：角色取**最高权限**，
    `department_ids` 收集他所属的全部部门。
    """
    with transaction(conn) as active:
        if org_id is None:
            rows = active.execute(
                "SELECT org_id, department_id, role FROM memberships "
                "WHERE user_id = ? AND status = 'active' ORDER BY org_id",
                (int(user_id),),
            ).fetchall()
        else:
            rows = active.execute(
                "SELECT org_id, department_id, role FROM memberships "
                "WHERE user_id = ? AND org_id = ? AND status = 'active'",
                (int(user_id), int(org_id)),
            ).fetchall()
    if not rows:
        raise PermissionError(f"user {user_id} 没有可用的组织成员关系")
    rank = {Role.MEMBER: 1, Role.ADMIN: 2, Role.ORG_ADMIN: 3}
    roles = [coerce_role(row["role"]) for row in rows]
    top_role = max(roles, key=lambda role: rank.get(role, 0))
    departments = frozenset(
        int(row["department_id"]) for row in rows if row["department_id"] is not None
    )
    return Viewer(
        user_id=int(user_id),
        org_id=int(rows[0]["org_id"]),
        role=top_role,
        department_ids=departments,
    )


def resolve_viewer_or_personal(
    user_id: int, *, org_id: int | None = None, conn: Connection | None = None
) -> Viewer:
    """解析身份；无组织成员资格时回落个人模式 viewer（member-invite 拍板 1）。

    新注册用户不再自动进默认组织——登录态仍是有效 Viewer（org_id=None、member 档），
    只看得见自己的训练；组织类端点按无资格处理。
    """
    try:
        return resolve_viewer(user_id, org_id=org_id, conn=conn)
    except PermissionError:
        return resolve_personal_viewer(user_id)


def resolve_personal_viewer(user_id: int) -> Viewer:
    """个人模式 viewer：无组织成员资格（org_id=None、member 档）。"""
    return Viewer(user_id=int(user_id), org_id=None, role=Role.MEMBER, department_ids=frozenset())


def list_members(
    org_id: int = DEFAULT_ORG_ID,
    *,
    department_id: int | None = None,
    conn: Connection | None = None,
) -> list[dict[str, Any]]:
    """列出组织成员（管理端"人员"页用）。"""
    with transaction(conn) as active:
        sql = (
            "SELECT m.id, m.role, m.status, m.department_id, d.name AS department_name, "
            "u.id AS user_id, u.email, u.display_name "
            "FROM memberships m JOIN users u ON u.id = m.user_id "
            "LEFT JOIN departments d ON d.id = m.department_id "
            "WHERE m.org_id = ?"
        )
        params: list[Any] = [int(org_id)]
        if department_id is not None:
            sql += " AND m.department_id = ?"
            params.append(int(department_id))
        sql += " ORDER BY d.name, m.role, u.id"
        rows = active.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def create_department(
    name: str,
    *,
    org_id: int = DEFAULT_ORG_ID,
    parent_id: int | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """建部门。第一版只做一层：`parent_id` 只是预留字段（ADR-0022）。"""
    label = str(name or "").strip()
    if not label:
        raise ValueError("部门名不能为空")
    with transaction(conn) as active:
        ensure_default_org(conn=active) if int(org_id) == DEFAULT_ORG_ID else None
        cursor = active.execute(
            "INSERT INTO departments (org_id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
            (int(org_id), label, parent_id, _now()),
        )
        row = active.execute(
            "SELECT * FROM departments WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def list_departments(
    org_id: int = DEFAULT_ORG_ID, *, conn: Connection | None = None
) -> list[dict[str, Any]]:
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM memberships m WHERE m.department_id = d.id) AS member_count "
            "FROM departments d WHERE d.org_id = ? ORDER BY d.name",
            (int(org_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_roster_entry(
    email: str,
    *,
    org_id: int = DEFAULT_ORG_ID,
    department_id: int | None = None,
    role: Role | str = Role.MEMBER,
    status: str = "invited",
    conn: Connection | None = None,
) -> dict[str, Any]:
    """写一条名单记录：邮箱 → 部门 + 角色（ADR-0022：部门归属由名单决定，不靠邮箱猜）。"""
    address = str(email or "").strip().lower()
    if "@" not in address:
        raise ValueError("邮箱格式不正确")
    normalized = coerce_role(role)
    if normalized is Role.ORG_ADMIN and department_id is None:
        pass  # 组织管理员可以不属于任何部门
    if status not in ("invited", "active", "revoked"):
        raise ValueError(f"unknown roster status: {status!r}")
    with transaction(conn) as active:
        if int(org_id) == DEFAULT_ORG_ID:
            ensure_default_org(conn=active)
        active.execute(
            "INSERT INTO roster_entries (org_id, email, department_id, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(org_id, email) DO UPDATE SET department_id = excluded.department_id, "
            "role = excluded.role, status = excluded.status",
            (int(org_id), address, department_id, normalized.value, status, _now()),
        )
        row = active.execute(
            "SELECT * FROM roster_entries WHERE org_id = ? AND email = ?",
            (int(org_id), address),
        ).fetchone()
    return dict(row)


def list_roster(
    org_id: int = DEFAULT_ORG_ID, *, conn: Connection | None = None
) -> list[dict[str, Any]]:
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT r.*, d.name AS department_name FROM roster_entries r "
            "LEFT JOIN departments d ON d.id = r.department_id "
            "WHERE r.org_id = ? ORDER BY r.status, d.name, r.email",
            (int(org_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def match_roster(
    email: str, *, org_id: int = DEFAULT_ORG_ID, conn: Connection | None = None
) -> dict[str, Any] | None:
    """按邮箱在名单里找人。**不在名单就是不在名单**——不开放自助注册（ADR-0022）。"""
    address = str(email or "").strip().lower()
    if "@" not in address:
        return None
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM roster_entries WHERE org_id = ? AND email = ? AND status != 'revoked'",
            (int(org_id), address),
        ).fetchone()
    return dict(row) if row else None


def provision_user_from_roster(
    email: str, *, org_id: int = DEFAULT_ORG_ID, conn: Connection | None = None
) -> dict[str, Any]:
    """按名单开号：建（或复用）用户 → 建立带部门的成员关系 → 名单标为 active。

    名单里没有这个邮箱时抛 ``PermissionError``（对应"请联系管理员分配部门"）。
    """
    with transaction(conn) as active:
        entry = match_roster(email, org_id=org_id, conn=active)
        if entry is None:
            raise PermissionError("该邮箱不在公司名单里，请联系管理员分配部门")
        address = str(entry["email"])
        existing = active.execute(
            "SELECT * FROM users WHERE email = ?", (address,)
        ).fetchone()
        if existing is None:
            cursor = active.execute(
                "INSERT INTO users (email, display_name, created_at) VALUES (?, ?, ?)",
                (address, address.split("@")[0], _now()),
            )
            user_id = int(cursor.lastrowid)
        else:
            user_id = int(existing["id"])

        membership = add_membership(
            user_id,
            int(entry["org_id"]),
            department_id=entry["department_id"],
            role=str(entry["role"]),
            status="active",
            conn=active,
        )
        active.execute(
            "UPDATE roster_entries SET status = 'active', accepted_at = ? WHERE id = ?",
            (_now(), int(entry["id"])),
        )
        user = active.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"user": dict(user), "membership": membership, "roster": entry}


def backfill_org_scope(*, org_id: int = DEFAULT_ORG_ID, conn: Connection | None = None) -> dict[str, int]:
    """把没有归组织的老数据划到默认组织（幂等）。"""
    touched: dict[str, int] = {}
    with transaction(conn) as active:
        ensure_default_org(conn=active)
        for table in ("trainings", "sources"):
            columns = {
                str(row["name"])
                for row in active.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "org_id" not in columns:
                continue
            cursor = active.execute(
                f"UPDATE {table} SET org_id = ? WHERE org_id IS NULL OR org_id = 0",
                (int(org_id),),
            )
            touched[table] = int(cursor.rowcount or 0)
    return touched



# ---------------------------------------------------------------- 成员邀请（change member-invite）

#: 小组管理员默认配额（org_admin 可逐人调整）
DEFAULT_ADMIN_QUOTA: int = 10


def _membership_row(active: Connection, membership_id: int) -> dict[str, Any] | None:
    row = active.execute(
        "SELECT m.*, u.email, u.display_name FROM memberships m "
        "JOIN users u ON u.id = m.user_id WHERE m.id = ?",
        (int(membership_id),),
    ).fetchone()
    return dict(row) if row else None


def list_candidates(
    org_id: int, *, query: str = "", limit: int = 20, conn: Connection | None = None
) -> list[dict[str, Any]]:
    """候选列表（design：候选 = 已注册用户 ∧ 不是本组织在册/挂起成员），支持邮箱/昵称搜索。"""
    with transaction(conn) as active:
        sql = (
            "SELECT u.id AS user_id, u.email, u.display_name FROM users u "
            "WHERE u.id NOT IN (SELECT user_id FROM memberships WHERE org_id = ?) "
        )
        params: list[Any] = [int(org_id)]
        like = f"%{str(query or '').strip()}%"
        if query:
            sql += " AND (u.email LIKE ? OR u.display_name LIKE ?) "
            params += [like, like]
        sql += "ORDER BY u.id LIMIT ?"
        params.append(int(limit))
        rows = active.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def invite_member(
    org_id: int,
    inviter: Viewer,
    email: str,
    *,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """站内邀请（拍板 3：站外邮箱后置）：目标必须是已注册且非本组织成员。

    admin 受配额（DEFAULT_ADMIN_QUOTA，org_admin 逐人设置）；org_admin 不受限。
    建立 memberships(status='invited', invited_by=邀请人, role='member')。
    """
    address = str(email or "").strip().lower()
    if "@" not in address:
        raise ValueError("邮箱格式不正确")
    if inviter.org_id is None or int(inviter.org_id) != int(org_id):
        raise PermissionError("只能邀请成员加入自己所在的组织")
    with transaction(conn) as active:
        user = active.execute(
            "SELECT id, display_name FROM users WHERE email = ?", (address,)
        ).fetchone()
        if user is None:
            raise ValueError(f"{address} 还没有注册（站外邮箱邀请后置）")
        existing = active.execute(
            "SELECT id, status FROM memberships WHERE user_id = ? AND org_id = ?",
            (int(user["id"]), int(org_id)),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"{address} 已是该组织成员或已在邀请中")
        if inviter.role is Role.ADMIN:
            quota_row = active.execute(
                "SELECT admin_quota FROM memberships WHERE user_id = ? AND org_id = ?",
                (int(inviter.user_id), int(org_id)),
            ).fetchone()
            quota = int(quota_row["admin_quota"]) if quota_row and quota_row["admin_quota"] is not None else DEFAULT_ADMIN_QUOTA
            used = active.execute(
                "SELECT COUNT(*) n FROM memberships WHERE invited_by = ? AND org_id = ? "
                "AND status IN ('invited', 'active')",
                (int(inviter.user_id), int(org_id)),
            ).fetchone()["n"]
            if int(used) >= quota:
                raise ValueError(f"邀请配额已用满（{used}/{quota}）——请联系组织管理员调整")
        membership = add_membership(
            int(user["id"]), int(org_id), role=Role.MEMBER, status="invited",
            invited_by=int(inviter.user_id), conn=active,
        )
    return {"membership": membership, "email": address, "display_name": str(user["display_name"] or "")}


def remove_member(
    org_id: int,
    remover: Viewer,
    target_user_id: int,
    *,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """移除成员（资格置 disabled，数据保留）：admin 受开关且只能移 member；org_admin 总可。"""
    if remover.org_id is None or int(remover.org_id) != int(org_id):
        raise PermissionError("只能管理自己所在的组织")
    with transaction(conn) as active:
        row = active.execute(
            "SELECT role, invited_by FROM memberships WHERE user_id = ? AND org_id = ?",
            (int(target_user_id), int(org_id)),
        ).fetchone()
        if row is None:
            raise ValueError("该用户不是本组织成员")
        if remover.role is Role.ADMIN:
            switch_row = active.execute(
                "SELECT admin_can_remove FROM memberships WHERE user_id = ? AND org_id = ?",
                (int(remover.user_id), int(org_id)),
            ).fetchone()
            if not switch_row or not int(switch_row["admin_can_remove"] or 0):
                raise PermissionError("你还没有被授予移除成员的权限")
            if coerce_role(row["role"]) is not Role.MEMBER:
                raise PermissionError("小组管理员只能移除普通成员")
        active.execute(
            "UPDATE memberships SET status = 'disabled' WHERE user_id = ? AND org_id = ?",
            (int(target_user_id), int(org_id)),
        )
    return {"removed": int(target_user_id), "status": "disabled"}


def set_member_role(
    org_id: int,
    operator: Viewer,
    target_user_id: int,
    *,
    role: str,
    admin_quota: int | None = None,
    admin_can_remove: bool | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """org_admin 专属：升降 admin / 逐人配额与删除开关（design：升 admin 必须同时给配额）。"""
    if operator.org_id is None or int(operator.org_id) != int(org_id):
        raise PermissionError("只能管理自己所在的组织")
    if operator.role is not Role.ORG_ADMIN:
        raise PermissionError("只有组织管理员可以调整成员角色")
    normalized = coerce_role(role)
    if normalized is Role.ORG_ADMIN and int(target_user_id) != int(operator.user_id):
        # 组织管理员档不由本端点直接授予（避免误把别人升成超级管理员）
        raise ValueError("org_admin 档请通过组织管理流程授予")
    with transaction(conn) as active:
        row = active.execute(
            "SELECT role FROM memberships WHERE user_id = ? AND org_id = ?",
            (int(target_user_id), int(org_id)),
        ).fetchone()
        if row is None:
            raise ValueError("该用户不是本组织成员")
        quota = admin_quota
        if normalized is Role.ADMIN and quota is None:
            quota = DEFAULT_ADMIN_QUOTA  # 升 admin 必须同时给配额（对称性）
        if normalized is not Role.ADMIN and quota is None:
            quota = None  # 降回 member：配额清空
        active.execute(
            "UPDATE memberships SET role = ?, admin_quota = ?, admin_can_remove = ? "
            "WHERE user_id = ? AND org_id = ?",
            (
                normalized.value,
                quota,
                (1 if admin_can_remove else 0) if admin_can_remove is not None else 0,
                int(target_user_id),
                int(org_id),
            ),
        )
        updated = active.execute(
            "SELECT m.*, u.email, u.display_name FROM memberships m "
            "JOIN users u ON u.id = m.user_id WHERE m.user_id = ? AND m.org_id = ?",
            (int(target_user_id), int(org_id)),
        ).fetchone()
    return dict(updated)


def list_my_invites(user_id: int, *, conn: Connection | None = None) -> list[dict[str, Any]]:
    """被邀请人侧：我的待接受邀请（invited 成员资格 + 组织名 + 邀请人）。"""
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT m.id AS membership_id, m.org_id, o.name AS org_name, m.created_at, "
            "u.email AS inviter_email, u.display_name AS inviter_name "
            "FROM memberships m "
            "JOIN organizations o ON o.id = m.org_id "
            "LEFT JOIN memberships mi ON mi.user_id = m.invited_by AND mi.org_id = m.org_id "
            "LEFT JOIN users u ON u.id = m.invited_by "
            "WHERE m.user_id = ? AND m.status = 'invited' ORDER BY m.created_at DESC",
            (int(user_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def accept_invite(user_id: int, membership_id: int, *, conn: Connection | None = None) -> dict[str, Any]:
    """接受邀请：invited → active（只能接受自己的邀请）。"""
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM memberships WHERE id = ? AND user_id = ? AND status = 'invited'",
            (int(membership_id), int(user_id)),
        ).fetchone()
        if row is None:
            raise ValueError("邀请不存在或已处理")
        active.execute(
            "UPDATE memberships SET status = 'active', created_at = ? WHERE id = ?",
            (_now(), int(membership_id)),
        )
        viewer = resolve_viewer(int(user_id), org_id=int(row["org_id"]), conn=active)
    return {"org_id": int(row["org_id"]), "role": viewer.role.value, "status": "active"}


def member_progress(
    org_id: int,
    viewer: Viewer,
    target_user_id: int,
    *,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """成员互看进度（拍板 4：完成状态 + 分数聚合）——同组织成员可看，聚合口径不暴露作答明细。"""
    if viewer.org_id is None or int(viewer.org_id) != int(org_id):
        raise PermissionError("只能查看自己所在组织成员的进度")
    with transaction(conn) as active:
        member = active.execute(
            "SELECT m.role, m.status, u.email, u.display_name FROM memberships m "
            "JOIN users u ON u.id = m.user_id WHERE m.user_id = ? AND m.org_id = ? "
            "AND m.status = 'active'",
            (int(target_user_id), int(org_id)),
        ).fetchone()
        if member is None:
            raise ValueError("该用户不是本组织在册成员")
        trainings = active.execute(
            "SELECT t.id, t.topic, t.status, t.baseline_score, t.visibility, "
            "(SELECT COUNT(*) FROM training_items i JOIN path_stages s ON s.id = i.stage_id "
            " JOIN training_paths p ON p.id = s.path_id WHERE p.training_id = t.id) AS item_count, "
            "(SELECT COUNT(*) FROM training_items i JOIN path_stages s ON s.id = i.stage_id "
            " JOIN training_paths p ON p.id = s.path_id WHERE p.training_id = t.id AND i.status = 'passed') AS passed_count "
            "FROM trainings t WHERE t.owner_user_id = ? AND t.visibility = 'public' "
            "ORDER BY t.created_at DESC",
            (int(target_user_id),),
        ).fetchall()
        scores = active.execute(
            "SELECT AVG(score) AS avg_score, COUNT(*) AS quiz_count FROM assessments "
            "WHERE training_id IN (SELECT id FROM trainings WHERE owner_user_id = ?) "
            "AND status = 'completed' AND passed = 1",
            (int(target_user_id),),
        ).fetchone()
    return {
        "user_id": int(target_user_id),
        "email": str(member["email"] or ""),
        "display_name": str(member["display_name"] or ""),
        "role": str(member["role"]),
        "trainings": [
            {
                "training_id": int(t["id"]),
                "topic": str(t["topic"]),
                "status": str(t["status"]),
                "completion": (
                    round(int(t["passed_count"]) / int(t["item_count"]), 4)
                    if int(t["item_count"])
                    else None
                ),
            }
            for t in trainings
        ],
        "avg_quiz_score": float(scores["avg_score"]) if scores["avg_score"] is not None else None,
        "passed_quiz_count": int(scores["quiz_count"] or 0),
    }


__all__ = [
    "DEFAULT_ADMIN_QUOTA",
    "DEFAULT_ORG_ID",
    "DEFAULT_ORG_NAME",
    "accept_invite",
    "add_membership",
    "invite_member",
    "backfill_org_scope",
    "create_department",
    "create_organization",
    "create_user",
    "ensure_default_org",
    "list_candidates",
    "list_departments",
    "list_members",
    "list_my_invites",
    "list_roster",
    "match_roster",
    "member_progress",
    "provision_user_from_roster",
    "remove_member",
    "resolve_personal_viewer",
    "resolve_viewer",
    "resolve_viewer_or_personal",
    "set_member_role",
    "upsert_roster_entry",
]
