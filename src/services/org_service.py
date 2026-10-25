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
    role: Role | str = Role.EMPLOYEE,
    status: str = "active",
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
            "INSERT INTO memberships (user_id, org_id, department_id, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, org_id) DO UPDATE SET role = excluded.role, status = excluded.status, "
            "department_id = excluded.department_id",
            (int(user_id), int(org_id), department_id, normalized.value, status, _now()),
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
    rank = {Role.EMPLOYEE: 1, Role.DEPT_MANAGER: 2, Role.ORG_ADMIN: 3}
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
    role: Role | str = Role.EMPLOYEE,
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


__all__ = [
    "DEFAULT_ORG_ID",
    "DEFAULT_ORG_NAME",
    "add_membership",
    "backfill_org_scope",
    "create_department",
    "create_organization",
    "create_user",
    "ensure_default_org",
    "list_departments",
    "list_members",
    "list_roster",
    "match_roster",
    "provision_user_from_roster",
    "resolve_viewer",
    "upsert_roster_entry",
]
