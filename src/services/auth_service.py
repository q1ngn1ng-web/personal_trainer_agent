"""认证内核：签发一次性登录码 → 校验换服务端会话 → 由会话解析身份。

对应 ADR-0023。三条硬约束（都有单测）：

1. **令牌只存哈希**：库里的 `login_tokens.token_hash` / `sessions.token_hash` 都是 sha256，
   明文只在生成的那一刻返回给调用方，不落库、不打日志；
2. **一次性登录码用完即废**：`used_at` 一写就不能再用；
3. **会话有明确过期与吊销**：`expires_at` / `revoked_at`，支持登出与管理员强制下线。

不引入密码（无密码 → 没有密码泄露、转手、忘记密码三类问题）。
写 Cookie 的三种落地方式（组件 / 外部登录端点 / `st.login()`）见 ADR-0023，
**本模块与它们解耦**：这里只负责"令牌 ↔ 会话 ↔ Viewer"。
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.permissions import Viewer
from src.db.connection import Connection, transaction
from src.services import org_service

logger = logging.getLogger("src.services.auth_service")

#: 一次性登录码有效期（分钟）
LOGIN_CODE_TTL_MINUTES: int = 15

#: 会话有效期（天）：**滑动续期**——每次访问都会顺延，只要还在用就不会掉线
SESSION_TTL_DAYS: int = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)




def issue_login_code(
    email: str,
    *,
    org_id: int = org_service.DEFAULT_ORG_ID,
    ttl_minutes: int = LOGIN_CODE_TTL_MINUTES,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """给名单内的邮箱签发一次性登录码。

    **不在名单里的邮箱一律拒绝**（ADR-0022：不开放自助注册）。
    返回值里的 ``token`` 是明文，只在此刻出现一次：第一版由管理员转交，
    接入邮件服务后改为系统发信（接口不变）。
    """
    entry = org_service.match_roster(email, org_id=org_id, conn=conn)
    if entry is None:
        raise PermissionError("该邮箱不在公司名单里，请联系管理员分配部门")

    token = _new_token()
    expires = _now() + timedelta(minutes=max(1, int(ttl_minutes)))
    with transaction(conn) as active:
        active.execute(
            "INSERT INTO login_tokens (org_id, email, token_hash, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(org_id), str(entry["email"]), _hash(token), _iso(expires), _iso(_now())),
        )
    logger.info("issue_login_code: %s 签发登录码（%d 分钟内有效）", entry["email"], ttl_minutes)
    return {
        "token": token,
        "email": str(entry["email"]),
        "org_id": int(org_id),
        "expires_at": _iso(expires),
        "roster": entry,
    }


def create_session(
    user_id: int,
    org_id: int = org_service.DEFAULT_ORG_ID,
    *,
    ttl_days: int = SESSION_TTL_DAYS,
    user_agent: str | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """建服务端会话，返回明文令牌（只此一次）。"""
    token = _new_token()
    expires = _now() + timedelta(days=max(1, int(ttl_days)))
    with transaction(conn) as active:
        cursor = active.execute(
            "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at, "
            "user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(user_id),
                int(org_id),
                _hash(token),
                _iso(_now()),
                _iso(expires),
                _iso(_now()),
                user_agent,
            ),
        )
        session_id = int(cursor.lastrowid)
    return {"session_id": session_id, "token": token, "expires_at": _iso(expires)}


def verify_login_code(
    token: str,
    *,
    org_id: int = org_service.DEFAULT_ORG_ID,
    user_agent: str | None = None,
    conn: Connection | None = None,
) -> dict[str, Any]:
    """校验登录码 → 开号（若需要）→ 建会话。返回会话令牌与身份上下文。"""
    raw = str(token or "").strip()
    if not raw:
        raise ValueError("登录码不能为空")
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM login_tokens WHERE token_hash = ?", (_hash(raw),)
        ).fetchone()
        if row is None:
            raise ValueError("登录码无效")
        if row["used_at"]:
            raise ValueError("登录码已经用过了，请重新申请")
        expires = _parse(row["expires_at"])
        if expires is not None and expires < _now():
            raise ValueError("登录码已过期，请重新申请")

        active.execute(
            "UPDATE login_tokens SET used_at = ? WHERE id = ?", (_iso(_now()), int(row["id"]))
        )

        provisioned = org_service.provision_user_from_roster(
            str(row["email"]), org_id=int(row["org_id"]), conn=active
        )
        viewer = org_service.resolve_viewer(
            int(provisioned["user"]["id"]), org_id=int(row["org_id"]), conn=active
        )
        session = create_session(
            viewer.user_id, viewer.org_id, user_agent=user_agent, conn=active
        )
    logger.info("verify_login_code: %s 登录成功（会话 #%s）", row["email"], session["session_id"])
    return {"session": session, "viewer": viewer, "user": provisioned["user"]}


def viewer_from_session(
    session_token: str, *, conn: Connection | None = None
) -> Viewer | None:
    """由会话令牌解析身份；无效/过期/已吊销返回 ``None``。

    命中有效会话时**滑动续期**（`expires_at` 顺延 `SESSION_TTL_DAYS`），
    这样开发/自用场景不必反复重新签发登录码；长期不用才会失效。
    """
    raw = str(session_token or "").strip()
    if not raw:
        return None
    with transaction(conn) as active:
        row = active.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (_hash(raw),)
        ).fetchone()
        if row is None or row["revoked_at"]:
            return None
        expires = _parse(row["expires_at"])
        if expires is not None and expires < _now():
            return None
        renewed = _now() + timedelta(days=SESSION_TTL_DAYS)
        active.execute(
            "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
            (_iso(_now()), _iso(renewed), int(row["id"])),
        )
        try:
            return org_service.resolve_viewer(
                int(row["user_id"]), org_id=int(row["org_id"]), conn=active
            )
        except PermissionError:
            # 成员关系被移除（例如员工被调离）→ 会话视为失效
            return None


def revoke_session(
    session_token: str, *, conn: Connection | None = None
) -> bool:
    """登出 / 强制下线。"""
    with transaction(conn) as active:
        cursor = active.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_iso(_now()), _hash(str(session_token or ""))),
        )
        return bool(cursor.rowcount)


def revoke_user_sessions(
    user_id: int, *, conn: Connection | None = None
) -> int:
    """把某个用户的所有会话一次性吊销（管理员操作）。"""
    with transaction(conn) as active:
        cursor = active.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_iso(_now()), int(user_id)),
        )
        return int(cursor.rowcount or 0)


def list_sessions(
    user_id: int, *, conn: Connection | None = None
) -> list[dict[str, Any]]:
    with transaction(conn) as active:
        rows = active.execute(
            "SELECT id, org_id, created_at, expires_at, last_seen_at, revoked_at, user_agent "
            "FROM sessions WHERE user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def purge_expired(*, conn: Connection | None = None) -> dict[str, int]:
    """清理过期数据（登录码与被吊销/过期的会话），返回清理条数。"""
    now = _iso(_now())
    with transaction(conn) as active:
        tokens = active.execute(
            "DELETE FROM login_tokens WHERE expires_at < ? AND used_at IS NULL", (now,)
        ).rowcount
        sessions = active.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR revoked_at IS NOT NULL", (now,)
        ).rowcount
        return {"login_tokens": int(tokens or 0), "sessions": int(sessions or 0)}


# ------------------ 个人版：邮箱 + 密码账户（2026-10-26 用户决策） ------------------
# ADR-0023 的登录码机制保留给企业版；个人版按用户要求提供注册/登录。
# 只存 PBKDF2 哈希（sha256、24 万轮、16 字节盐），格式：pbkdf2$<iters>$<salt>$<hash>。

_PBKDF2_ITERATIONS = 240_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "$".join(["pbkdf2", str(_PBKDF2_ITERATIONS), salt.hex(), digest.hex()])


def _verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iters, salt_hex, hash_hex = str(stored).split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return secrets.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def register_account(
    email: str,
    password: str,
    display_name: str = "",
    *,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """个人版注册：users 行（含密码哈希）+ 名单激活 + 开号 + 建会话。"""
    address = str(email or "").strip().lower()
    if "@" not in address or len(str(password or "")) < 8:
        raise ValueError("邮箱格式不正确，或密码少于 8 位")
    with transaction() as active:
        row = active.execute(
            "SELECT id FROM users WHERE email = ?", (address,)
        ).fetchone()
        if row is not None:
            raise ValueError("该邮箱已注册")
        roster = org_service.upsert_roster_entry(
            address, status="active", conn=active
        )
        provisioned = org_service.provision_user_from_roster(address, conn=active)
        active.execute(
            "UPDATE users SET password_hash = ?, display_name = ?, last_login_at = ? WHERE id = ?",
            (
                _hash_password(password),
                str(display_name).strip() or address.split("@")[0],
                _iso(_now()),
                int(provisioned["user"]["id"]),
            ),
        )
        viewer = org_service.resolve_viewer(
            int(provisioned["user"]["id"]), conn=active
        )
        session = create_session(viewer.user_id, viewer.org_id, user_agent=user_agent, conn=active)
    logger.info("register_account: %s 注册成功（会话 #%s）", address, session["session_id"])
    return {"session": session, "viewer": viewer, "user": provisioned["user"]}


def login_password(
    email: str, password: str, *, user_agent: str | None = None
) -> dict[str, Any]:
    """个人版登录：校验密码 → 建会话。账号未激活或密码错统一报错（不区分暴露原因）。"""
    address = str(email or "").strip().lower()
    with transaction() as active:
        row = active.execute(
            "SELECT id, status FROM users WHERE email = ?", (address,)
        ).fetchone()
        stored = (
            active.execute(
                "SELECT password_hash FROM users WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if row is not None
            else None
        )
        ok = row is not None and row["status"] == "active" and _verify_password(
            str(password or ""), stored["password_hash"] if stored else None
        )
        if not ok:
            raise PermissionError("邮箱或密码不正确")
        active.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(_now()), int(row["id"]))
        )
        viewer = org_service.resolve_viewer(int(row["id"]), conn=active)
        session = create_session(viewer.user_id, viewer.org_id, user_agent=user_agent, conn=active)
    logger.info("login_password: %s 登录成功（会话 #%s）", address, session["session_id"])
    return {"session": session, "viewer": viewer}


__all__ = [
    "LOGIN_CODE_TTL_MINUTES",
    "SESSION_TTL_DAYS",
    "register_account",
    "login_password",
    "create_session",
    "issue_login_code",
    "list_sessions",
    "purge_expired",
    "revoke_session",
    "revoke_user_sessions",
    "verify_login_code",
    "viewer_from_session",
]
