"""企业版权限模型（纯函数）：角色 → 动作 + 可见范围判定。

对应 ADR-0014（第一版只做 `admin` / `employee` 两种角色）、ADR-0013（内容层与进度层分离）、
change `org-and-roles`。**权限判定不走 LLM**（ADR-0001：规则管状态）。

个人版约定：`viewer is None` 表示"没有启用鉴权"（个人版 profile），此时一切放行——
企业版启用后才注入 `Viewer`，差异由 profile 开关承载而不是代码分支（ADR-0020）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class Role(str, Enum):
    """第一版三种角色（ADR-0022）：组织管理员 / 部门主管 / 员工。

    ``ADMIN`` 是 ``ORG_ADMIN`` 的别名，兼容企业版第一刀写下的代码与数据。
    """

    ORG_ADMIN = "org_admin"
    DEPT_MANAGER = "dept_manager"
    EMPLOYEE = "employee"
    ADMIN = "org_admin"


class SourceScope(str, Enum):
    """资料来源的可见范围（change content-visibility 三档）。"""

    PRIVATE = "private"
    SPECIFIC = "specific"
    PUBLIC = "public"


class Action(str, Enum):
    """需要鉴权的动作（按"最小可讲清"的原则列，不做细粒度授权）。"""

    TRAIN_SELF = "train_self"
    VIEW_OWN_PROGRESS = "view_own_progress"
    UPLOAD_PERSONAL_SOURCE = "upload_personal_source"
    SUBMIT_SIGNAL = "submit_signal"
    MANAGE_ORG_SOURCES = "manage_org_sources"
    MANAGE_DEPARTMENT = "manage_department"
    MANAGE_DEPARTMENT_SOURCES = "manage_department_sources"
    PUBLISH_ASSIGNMENT = "publish_assignment"
    MANAGE_MEMBERS = "manage_members"
    VIEW_DEPT_REPORT = "view_dept_report"
    VIEW_ORG_REPORT = "view_org_report"


_EMPLOYEE_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.TRAIN_SELF,
        Action.VIEW_OWN_PROGRESS,
        Action.UPLOAD_PERSONAL_SOURCE,
        Action.SUBMIT_SIGNAL,
    }
)

_DEPT_MANAGER_ACTIONS: frozenset[Action] = _EMPLOYEE_ACTIONS | frozenset(
    {
        Action.MANAGE_DEPARTMENT,
        Action.MANAGE_DEPARTMENT_SOURCES,
        Action.VIEW_DEPT_REPORT,
    }
)

#: 权限矩阵：主管是员工的超集 + 本部门管理；组织管理员是主管的超集 + 全组织管理
PERMISSIONS: dict[Role, frozenset[Action]] = {
    Role.EMPLOYEE: _EMPLOYEE_ACTIONS,
    Role.DEPT_MANAGER: _DEPT_MANAGER_ACTIONS,
    Role.ORG_ADMIN: _DEPT_MANAGER_ACTIONS
    | frozenset(
        {
            Action.MANAGE_ORG_SOURCES,
            Action.PUBLISH_ASSIGNMENT,
            Action.MANAGE_MEMBERS,
            Action.VIEW_ORG_REPORT,
        }
    ),
}

#: 角色值的兼容映射（企业版第一刀写的 'admin' → 'org_admin'）
_ROLE_MIGRATION: dict[str, str] = {"admin": "org_admin"}


class PermissionDenied(PermissionError):
    """越权时抛出的统一异常。"""


@dataclass(frozen=True)
class Viewer:
    """当前请求的身份上下文（登录后注入）。"""

    user_id: int
    org_id: int
    role: Role
    department_ids: frozenset[int] = frozenset()


def coerce_role(value: Role | str | None) -> Role:
    if isinstance(value, Role):
        return value
    raw = _ROLE_MIGRATION.get(str(value), str(value))
    try:
        return Role(raw)
    except ValueError as exc:
        raise ValueError(f"unknown role: {value!r}") from exc


def coerce_action(value: Action | str) -> Action:
    """把动作归一成 ``Action``（注意：``str(Action.X)`` 会得到 "Action.X"，所以要先判实例）。"""
    if isinstance(value, Action):
        return value
    try:
        return Action(str(value))
    except ValueError as exc:
        raise ValueError(f"unknown action: {value!r}") from exc


def can(role: Role | str, action: Action | str) -> bool:
    """角色是否有权执行某动作。"""
    normalized_role = coerce_role(role)
    normalized_action = coerce_action(action)
    return normalized_action in PERMISSIONS.get(normalized_role, frozenset())


def assert_can(viewer: Viewer | None, action: Action | str) -> None:
    """统一的鉴权入口：个人版（``viewer is None``）放行，企业版按矩阵校验。"""
    if viewer is None:
        return
    if not can(viewer.role, action):
        raise PermissionDenied(f"role {viewer.role.value!r} may not perform {str(action)!r}")


def can_view_training(
    viewer: Viewer | None,
    training: dict[str, Any],
    shared_user_ids: list[int] | None = None,
) -> bool:
    """训练可见性三档（change content-visibility）：

    * owner 恒可见；
    * ``public`` → 同组织成员全部可见；
    * ``specific`` → owner + 指定成员（training_shares，调用方 join 提供）；
    * ``private``（默认）→ 仅 owner；
    * 组织不同一律不可见。owner 缺失的历史数据沿用旧口径（同组织可见）。
    """
    if viewer is None:
        return True
    if int(training.get("org_id") or 1) != int(viewer.org_id):
        return False
    uid = int(viewer.user_id)
    owner = training.get("owner_user_id")
    if owner in (None, ""):
        return True
    if int(owner) == uid:
        return True
    scope = str(training.get("visibility") or "private")
    if scope == "public":
        return True
    if scope == "specific":
        return uid in {int(x) for x in (shared_user_ids or ())}
    return False


def visible_trainings(
    viewer: Viewer | None, rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [row for row in rows if can_view_training(viewer, row)]


def can_view_source(
    viewer: Viewer | None, source: dict[str, Any], shared_user_ids: list[int] | None = None
) -> bool:
    """资料可见性三档（change content-visibility）：

    * owner（来源所属训练的创建者，调用方 join 提供 owner_user_id）恒可见；
    * ``public`` → 同组织成员全部可见；
    * ``specific`` → owner + 指定成员（source_shares）；
    * ``private`` → 仅 owner；
    * 组织不同一律不可见。资料无独立 owner 列——owner 取所属训练的创建者。
    """
    if viewer is None:
        return True
    if int(source.get("org_id") or 1) != int(viewer.org_id):
        return False
    uid = int(viewer.user_id)
    owner = source.get("owner_user_id")
    if owner not in (None, "") and int(owner) == uid:
        return True
    scope = str(source.get("scope") or SourceScope.PRIVATE.value)
    if scope == "public":
        return True
    if scope == "specific":
        return uid in {int(x) for x in (shared_user_ids or ())}
    return False


def can_manage_department(viewer: Viewer | None, department_id: int) -> bool:
    """主管只能管自己的部门；组织管理员可管本组织任意部门（ADR-0022 配套硬规则）。"""
    if viewer is None:
        return True
    if viewer.role is Role.ORG_ADMIN:
        return True
    if viewer.role is Role.DEPT_MANAGER:
        return int(department_id) in viewer.department_ids
    return False


def visible_sources(
    viewer: Viewer | None, rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [row for row in rows if can_view_source(viewer, row)]


__all__ = [
    "Action",
    "PERMISSIONS",
    "PermissionDenied",
    "Role",
    "SourceScope",
    "Viewer",
    "assert_can",
    "can",
    "can_manage_department",
    "can_view_source",
    "can_view_training",
    "coerce_role",
    "visible_sources",
    "visible_trainings",
]
