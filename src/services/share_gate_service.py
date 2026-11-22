"""分享门禁与开放链接（change ``share-gate``，任务 2.1/2.2）。

建立在已实施的 content-visibility 三档之上（private < specific < public）——
本模块只补"出门前的门禁 + 开放链接"，不重做可见性。

四类出向分享动作（publish / link_org / link_anyone / push）前置统一校验：
计划引用的每份启用文档，其可见级必须 ≥ 分享受众级；不达标文档必须被逐个
确认（全选是纯前端行为）后定向升级，升级与分享动作在同一事务端点完成。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("src.services.share_gate_service")

#: 支持的门禁动作（design D2 受众级表）
GATE_ACTIONS: tuple[str, ...] = ("publish", "link_org", "link_anyone", "push")

#: 文档可见级偏序：private(0) < specific(1) < public(2)
_SCOPE_LEVEL: dict[str, int] = {"private": 0, "specific": 1, "public": 2}

#: 审计账（design D5：MVP 不建新表，record 文件即审计账）
_AUDIT_PATH = Path(__file__).resolve().parents[2] / "workspace" / "record" / "share-gate-confirmations.md"


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    from src.db.sqlite import get_connection

    return conn if conn is not None else get_connection()


def resolve_member_uids(org_id: int | None, emails: list[str]) -> list[int]:
    """把指定成员邮箱解析为本组织在册 user_id；未命中 → ValueError 列出邮箱。

    与 content-visibility 的 VisibilityBody.shared_emails 同款规则（任务 2.2）。
    """
    normalized = [email.strip().lower() for email in emails if email and email.strip()]
    if not normalized:
        return []
    if org_id is None:
        raise ValueError("当前账号没有组织成员资格，无法解析指定成员")
    active = _connect()
    found: dict[str, int] = {}
    try:
        for email in normalized:
            row = active.execute(
                "SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE LOWER(u.email) = ? AND m.org_id = ? AND m.status = 'active'",
                (email, int(org_id)),
            ).fetchone()
            if row is not None:
                found[email] = int(row["id"])
    finally:
        active.close()
    missing = [email for email in normalized if email not in found]
    if missing:
        raise ValueError("以下邮箱不是本组织成员：" + "、".join(missing))
    return list(found.values())


def blocked_sources(
    training_id: int,
    *,
    audience: str,
    target_uids: list[int] | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """门禁清单（design D2）：引用集 = enabled 文档；逐份比较可见级与受众级。

    * audience=``public``（publish / link_org / link_anyone）：文档必须 = public；
    * audience=``specific``（push）：文档 = public，或 specific 且 source_shares
      授权覆盖全部目标成员；private 一律不达标（标注 uncovered_targets）。
    """
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT id, title, scope FROM sources "
            "WHERE training_id = ? AND enabled = 1 ORDER BY id",
            (int(training_id),),
        ).fetchall()
        share_rows = active.execute("SELECT source_id, user_id FROM source_shares").fetchall()
    finally:
        if own:
            active.close()
    grants: dict[int, set[int]] = {}
    for row in share_rows:
        grants.setdefault(int(row["source_id"]), set()).add(int(row["user_id"]))
    targets = set(int(uid) for uid in (target_uids or []))

    blocked: list[dict[str, Any]] = []
    for row in rows:
        scope = str(row["scope"] or "private")
        level = _SCOPE_LEVEL.get(scope, 0)
        if audience == "public":
            if level >= 2:
                continue
            blocked.append(
                {"source_id": int(row["id"]), "title": str(row["title"] or ""), "visibility": scope}
            )
        else:  # specific(U)
            if level >= 2:
                continue
            uncovered = grants.get(int(row["id"]), set()) < targets
            if scope == "specific" and not uncovered:
                continue
            blocked.append(
                {
                    "source_id": int(row["id"]),
                    "title": str(row["title"] or ""),
                    "visibility": scope,
                    "uncovered_targets": uncovered,
                }
            )
    return blocked


def audience_of(action: str) -> str:
    """动作 → 受众级（design D2）：四类动作里仅 push 是 specific 受众。"""
    if action not in GATE_ACTIONS:
        raise ValueError(f"未知分享动作：{action}")
    return "specific" if action == "push" else "public"


def gate_check(
    training_id: int,
    action: str,
    *,
    target_uids: list[int] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """只读门禁查询（design D3 第一步）：返回 blocked 清单与 ready。"""
    audience = audience_of(action)
    blocked = blocked_sources(
        int(training_id), audience=audience, target_uids=target_uids, conn=conn
    )
    return {
        "action": action,
        "audience": audience,
        "blocked": blocked,
        "ready": not blocked,
        "targets_resolved": [
            {"user_id": uid} for uid in sorted(target_uids or [])
        ],
    }


def confirm_and_execute(
    training_id: int,
    action: str,
    owner_user_id: int,
    *,
    target_uids: list[int] | None = None,
    open_level: str | None = None,
    confirm_source_ids: list[int] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """门禁确认 + 分享动作（design D3 第二步）：单事务，无部分生效。

    确认集缺少任一 blocked 文档 → ValueError（端点层转 409 带最新清单），
    文档不升级、分享不执行。确认即定向升级且持久（design D5）。
    """
    from src.services import training_clone_service

    if action not in GATE_ACTIONS:
        raise ValueError(f"未知分享动作：{action}")
    active = _connect(conn)
    own = conn is None
    try:
        audience = audience_of(action)
        blocked = blocked_sources(
            int(training_id), audience=audience, target_uids=target_uids, conn=active
        )
        blocked_ids = {entry["source_id"] for entry in blocked}
        confirmed = {int(sid) for sid in (confirm_source_ids or [])}
        if blocked_ids - confirmed:
            raise GateIncompleteError(blocked)

        # 1) 定向升级（publish/link_* → public；push → specific + 授权目标成员）
        upgraded: list[dict[str, Any]] = []
        for entry in blocked:
            source_id = int(entry["source_id"])
            if action == "push":
                active.execute(
                    "UPDATE sources SET scope = 'specific' WHERE id = ?", (source_id,)
                )
                for uid in target_uids or []:
                    active.execute(
                        "INSERT OR IGNORE INTO source_shares (source_id, user_id, created_by, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (source_id, int(uid), int(owner_user_id), _now_iso()),
                    )
            else:
                active.execute(
                    "UPDATE sources SET scope = 'public' WHERE id = ?", (source_id,)
                )
            upgraded.append(entry)

        # 2) 执行分享动作（同一事务）
        result: dict[str, Any]
        if action == "publish":
            active.execute(
                "UPDATE trainings SET visibility = 'public' WHERE id = ?", (int(training_id),)
            )
            result = {"ok": True, "visibility": "public"}
        elif action in ("link_org", "link_anyone"):
            level = "anyone" if action == "link_anyone" else "org"
            if open_level is not None and open_level != level:
                raise ValueError(f"action 与 open_level 不一致：{open_level}")
            result = training_clone_service.create_share_link(
                int(training_id), int(owner_user_id), open_level=level, conn=active
            )
        else:  # push
            result = training_clone_service.push_to_members(
                int(training_id), int(owner_user_id), list(target_uids or []), conn=active
            )
        if own:
            active.commit()
        _log_confirmation(training_id, action, owner_user_id, upgraded, result)
        return {"upgraded": upgraded, "blocked": blocked, **result}
    except Exception:
        if own:
            active.rollback()
        raise
    finally:
        if own:
            active.close()


class GateIncompleteError(ValueError):
    """确认集不完整（缺任一 blocked 文档）：整体失败，无部分生效。"""

    def __init__(self, blocked: list[dict[str, Any]]):
        super().__init__("存在未确认的文档：请逐件确认后重试")
        self.blocked = blocked


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_confirmation(
    training_id: int,
    action: str,
    owner_user_id: int,
    upgraded: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    """确认审计（design D5）：谁/何时/哪次分享/确认了哪些 source_id——record 文件即审计账。"""
    if not upgraded:
        return
    line = (
        f"- {datetime.now(timezone.utc).isoformat(timespec='seconds')}｜training {training_id}｜"
        f"action={action}｜owner={owner_user_id}｜confirmed={sorted(e['source_id'] for e in upgraded)}｜"
        f"outcome={json.dumps(result, ensure_ascii=False, default=str)[:200]}\n"
    )
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as handle:
            if not _AUDIT_PATH.exists():
                handle.write("# share-gate 确认审计（谁/何时/哪次分享/确认了哪些文档）\n\n")
            handle.write(line)
    except OSError:  # 审计落盘失败不阻塞分享事务（日志兜底）
        logger.warning("share_gate: audit write failed for training %s", training_id, exc_info=True)


__all__ = [
    "GATE_ACTIONS",
    "GateIncompleteError",
    "audience_of",
    "blocked_sources",
    "confirm_and_execute",
    "gate_check",
    "resolve_member_uids",
]
