"""训练计划克隆服务（change ``plan-sharing``）。

把一份跑通的训练（目标/资料/切片/题库/要点/路径骨架）复制为指定用户的**独立副本**：

* **内容层随副本复制**：资料、切片、题库（练习计数与冷却期重置）、要点清单、路径骨架；
* **进度层绝不复制**：作答记录、达标状态、错因与记忆画像从零开始（ADR-0013
  内容层/进度层分离——学习是个人行为）；
* 计划按接收日重新锚定生成（五轮从拉取/接收那天开始算）；
* `item_key` 按新 training_id 重新计算——在副本内保持稳定，且与原训练天然隔离；
* 溯源：副本记录 `shared_from_training_id` / `shared_by_user_id`。

所有复制在单事务内完成；判分链路零改动。
"""
from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.core.plan import item_key_for
from src.db.connection import transaction
from src.db.sqlite import get_connection as _connect

logger = logging.getLogger("src.services.training_clone_service")

#: 分享链接 token 长度（secrets.token_urlsafe 字符数）
TOKEN_BYTES: int = 16


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_org_member(user_id: int, org_id: int, conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ? AND status = 'active'",
        (int(user_id), int(org_id)),
    ).fetchone()
    return row is not None


def create_share_link(
    training_id: int, created_by: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """为训练生成/返回分享链接（幂等：同人同训练一条有效链接）。"""
    with transaction(conn) as active:
        training = active.execute(
            "SELECT id, org_id, owner_user_id FROM trainings WHERE id = ?", (int(training_id),)
        ).fetchone()
        if training is None:
            raise ValueError(f"训练不存在: {training_id}")
        existing = active.execute(
            "SELECT token FROM share_links WHERE training_id = ? AND created_by = ? "
            "AND revoked_at IS NULL ORDER BY id DESC LIMIT 1",
            (int(training_id), int(created_by)),
        ).fetchone()
        if existing is not None:
            return {"token": str(existing["token"]), "created": False}
        token = secrets.token_urlsafe(TOKEN_BYTES)
        active.execute(
            "INSERT INTO share_links (training_id, token, created_by, created_at) "
            "VALUES (?, ?, ?, ?)",
            (int(training_id), token, int(created_by), _now()),
        )
    return {"token": token, "created": True}


def get_share_preview(token: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """链接预览：计划结构 + 验收标准。MUST NOT 含题库内容/参考答案/作答数据。"""
    with transaction(conn) as active:
        link = active.execute(
            "SELECT training_id, created_by FROM share_links "
            "WHERE token = ? AND revoked_at IS NULL",
            (str(token),),
        ).fetchone()
        if link is None:
            raise ValueError("分享链接不存在或已撤销")
        training = active.execute(
            "SELECT id, topic, status, goal_json, keywords, org_id FROM trainings WHERE id = ?",
            (int(link["training_id"]),),
        ).fetchone()
        if training is None:
            raise ValueError("分享的训练不存在")
        stages = []
        path = active.execute(
            "SELECT id FROM training_paths WHERE training_id = ? "
            "ORDER BY (status = 'confirmed') DESC, version DESC LIMIT 1",
            (int(training["id"]),),
        ).fetchone()
        if path is not None:
            for stage in active.execute(
                "SELECT id, ordinal, title, goal, estimated_minutes, status FROM path_stages "
                "WHERE path_id = ? ORDER BY ordinal",
                (int(path["id"]),),
            ).fetchall():
                items = [
                    {
                        "title": it["title"],
                        "knowledge_point": it["knowledge_point"],
                        "item_type": it["item_type"],
                    }
                    for it in active.execute(
                        "SELECT title, knowledge_point, item_type FROM training_items "
                        "WHERE stage_id = ? ORDER BY ordinal",
                        (int(stage["id"]),),
                    ).fetchall()
                ]
                stages.append(
                    {
                        "ordinal": int(stage["ordinal"]),
                        "title": stage["title"],
                        "goal": stage["goal"],
                        "estimated_minutes": int(stage["estimated_minutes"] or 0),
                        "status": stage["status"],
                        "items": items,
                    }
                )
        goal = json.loads(training["goal_json"]) if training["goal_json"] else None
        acceptance = None
        if isinstance(goal, dict):
            acceptance = goal.get("acceptance")
        return {
            "training_id": int(training["id"]),
            "topic": str(training["topic"]),
            "org_id": int(training["org_id"] or 1),
            "stages": stages,
            "acceptance": acceptance,
            "keywords": json.loads(training["keywords"] or "[]"),
        }


def pull_by_token(token: str, user_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """组织内成员凭链接拉取独立副本（幂等：同用户同链接返回已有副本）。"""
    with transaction(conn) as active:
        link = active.execute(
            "SELECT training_id, created_by FROM share_links "
            "WHERE token = ? AND revoked_at IS NULL",
            (str(token),),
        ).fetchone()
        if link is None:
            raise ValueError("分享链接不存在或已撤销")
        return clone_for_user(
            int(link["training_id"]), int(user_id),
            shared_by_user_id=int(link["created_by"]), conn=active,
        )


def clone_for_user(
    training_id: int,
    target_user_id: int,
    *,
    shared_by_user_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """把一份训练完整克隆为 ``target_user_id`` 名下的独立副本（change plan-sharing）。

    幂等：该用户已拥有该来源的副本时直接返回，不再创建。
    权限：接收者必须是来源训练所属组织的在册成员（个人版组队的边界）。
    """
    with transaction(conn) as active:
        src = active.execute("SELECT * FROM trainings WHERE id = ?", (int(training_id),)).fetchone()
        if src is None:
            raise ValueError(f"训练不存在: {training_id}")

        # 幂等：同用户同来源只保留一份副本
        existing = active.execute(
            "SELECT id FROM trainings WHERE shared_from_training_id = ? AND owner_user_id = ?",
            (int(training_id), int(target_user_id)),
        ).fetchone()
        if existing is not None:
            return {"training_id": int(existing["id"]), "created": False}

        # 接收者必须是来源训练组织的在册成员（个人版组队边界）
        org_id = int(src["org_id"] or 1)
        if not _is_org_member(target_user_id, org_id, active):
            raise PermissionError("接收者不是该组织的在册成员")

        # 幂等去重哨兵：先插入占位行拿到新 training_id，再逐步填充内容
        active.execute(
            "INSERT INTO trainings (topic, status, created_at, org_id, owner_user_id, "
            "shared_from_training_id, shared_by_user_id) "
            "VALUES (?, 'pending_confirm', ?, ?, ?, ?, ?)",
            (
                f"{src['topic']}（来自分享）",
                _now(),
                org_id,
                int(target_user_id),
                int(training_id),
                int(shared_by_user_id if shared_by_user_id is not None else target_user_id),
            ),
        )
        new_tid = int(active.execute("SELECT last_insert_rowid()").fetchone()[0])

        # 1) 训练主行内容（目标/关键词等照搬；基线与进度归零——进度层分离）
        active.execute(
            """UPDATE trainings SET
                 goal_json = ?, goal_confirmed_at = NULL,
                 clarification_rounds = ?, keywords = ?, must_cover_count = ?,
                 forbidden = ?, targets = ?, review_items = ?, pretrain_checklist = ?,
                 schedule = ?, materials = ?, current_week = 1, last_review_at = NULL,
                 baseline_score = 0, baseline_level = NULL, last_active_at = NULL
               WHERE id = ?""",
            (
                src["goal_json"], src["clarification_rounds"], src["keywords"],
                src["must_cover_count"], src["forbidden"], src["targets"],
                src["review_items"], src["pretrain_checklist"], src["schedule"],
                src["materials"], new_tid,
            ),
        )

        # 2) 资料 + 切片（副本私有）
        source_map: dict[int, int] = {}
        for s in active.execute(
            "SELECT * FROM sources WHERE training_id = ?", (int(training_id),)
        ).fetchall():
            cur = active.execute(
                "INSERT INTO sources (training_id, type, title, origin, origin_url, fetched_at, "
                "snapshot_text, org_id, scope, enabled, checksum, parse_status, parse_error, "
                "imported_at, department_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, NULL)",
                (
                    new_tid, s["type"], s["title"], s["origin"], s["origin_url"], s["fetched_at"],
                    s["snapshot_text"], org_id, s["scope"], s["enabled"], s["checksum"],
                    s["parse_status"], s["parse_error"], s["imported_at"],
                ),
            )
            source_map[int(s["id"])] = int(cur.lastrowid)

        chunk_map: dict[int, int] = {}
        for old_sid, new_sid in source_map.items():
            for c in active.execute(
                "SELECT * FROM source_chunks WHERE source_id = ?", (old_sid,)
            ).fetchall():
                cur = active.execute(
                    "INSERT INTO source_chunks (source_id, ordinal, heading_path, text, char_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_sid, c["ordinal"], c["heading_path"], c["text"], c["char_count"]),
                )
                chunk_map[int(c["id"])] = int(cur.lastrowid)

        def _remap_chunk_ids(raw: Any) -> str | None:
            """把 source_chunk_ids（JSON 数组）按新 chunk id 重映射。"""
            if raw in (None, ""):
                return None
            try:
                ids = json.loads(raw) if isinstance(raw, str) else list(raw)
            except (TypeError, ValueError):
                return None
            mapped = [chunk_map[int(i)] for i in ids if int(i) in chunk_map]
            return json.dumps(mapped, ensure_ascii=False) if mapped else None

        # 3) 路径骨架（结构复制；item_key 按新 training_id 重算；进度归零）
        old_path = active.execute(
            "SELECT * FROM training_paths WHERE training_id = ? "
            "ORDER BY (status = 'confirmed') DESC, version DESC LIMIT 1",
            (int(training_id),),
        ).fetchone()
        item_key_map: dict[str, str] = {}
        if old_path is not None:
            cur = active.execute(
                "INSERT INTO training_paths (training_id, version, status, mode, horizon_weeks, "
                "weekly_frequency, daily_budget_minutes, budget_minutes, planned_minutes, created_at) "
                "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_tid, old_path["status"], old_path["mode"], old_path["horizon_weeks"],
                    old_path["weekly_frequency"], old_path["daily_budget_minutes"],
                    old_path["budget_minutes"], old_path["planned_minutes"], _now(),
                ),
            )
            new_path_id = int(cur.lastrowid)
            for st in active.execute(
                "SELECT * FROM path_stages WHERE path_id = ? ORDER BY ordinal", (int(old_path["id"]),)
            ).fetchall():
                cur = active.execute(
                    "INSERT INTO path_stages (path_id, ordinal, title, goal, estimated_minutes, status) "
                    "VALUES (?, ?, ?, ?, ?, 'locked')",
                    (new_path_id, st["ordinal"], st["title"], st["goal"], st["estimated_minutes"]),
                )
                new_stage_id = int(cur.lastrowid)
                for it in active.execute(
                    "SELECT * FROM training_items WHERE stage_id = ? ORDER BY ordinal",
                    (int(st["id"]),),
                ).fetchall():
                    new_key = item_key_for(
                        new_tid, it["knowledge_point"], it["title"]
                    )
                    item_key_map[str(it["item_key"])] = new_key
                    active.execute(
                        "INSERT INTO training_items (stage_id, ordinal, title, item_key, item_type, "
                        "difficulty_tier, difficulty_basis, knowledge_point, source_chunk_ids, "
                        "status, mastered_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "'pending', NULL, ?)",
                        (
                            new_stage_id, it["ordinal"], it["title"], new_key, it["item_type"],
                            it["difficulty_tier"], it["difficulty_basis"], it["knowledge_point"],
                            _remap_chunk_ids(it["source_chunk_ids"]), _now(),
                        ),
                    )

        # 4) 题库 + 要点清单（练习计数与冷却期重置；chunk 引用重映射）
        for qb in active.execute(
            "SELECT * FROM question_bank WHERE training_id = ?", (int(training_id),)
        ).fetchall():
            old_key = str(qb["item_key"])
            new_key = item_key_map.get(old_key)
            if new_key is None:
                continue  # 原训练里已被路径重生成淘汰的孤儿题，不带入副本
            active.execute(
                "INSERT INTO question_bank (training_id, item_key, source_chunk_ids, "
                "knowledge_point, item_type, question_type, options, difficulty_tier, "
                "question_text, answer_text, practiced_count, last_practiced_at, banked_at, "
                "cooldown_until, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, "
                "NULL, 'active')",
                (
                    new_tid, new_key, _remap_chunk_ids(qb["source_chunk_ids"]),
                    qb["knowledge_point"], qb["item_type"], qb["question_type"],
                    qb["options"], qb["difficulty_tier"], qb["question_text"],
                    qb["answer_text"], _now(),
                ),
            )
        for pt in active.execute(
            "SELECT * FROM question_points WHERE training_id = ?", (int(training_id),)
        ).fetchall():
            new_key = item_key_map.get(str(pt["item_key"]))
            if new_key is None:
                continue
            active.execute(
                "INSERT INTO question_points (training_id, item_key, point_id, point_text, "
                "weight, is_required, ordinal, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_tid, new_key, pt["point_id"], pt["point_text"], pt["weight"],
                    pt["is_required"], pt["ordinal"], _now(),
                ),
            )

        # 5) 计划按接收日重新锚定生成（五轮从今天开始算）
        from src.services.plan_service import generate_plan

        generate_plan(new_tid, conn=active)

    logger.info(
        "training_clone: %s -> new training %s (owner=%s)", training_id, new_tid, target_user_id
    )
    return {"training_id": new_tid, "created": True}


def push_to_members(
    training_id: int, owner_user_id: int, target_user_ids: list[int], *, conn=None
) -> dict[str, Any]:
    """把计划推送给指定成员（分享即复制，含题库）；非组织成员逐个跳过并报告。"""
    delivered: list[int] = []
    skipped: list[dict[str, Any]] = []
    with transaction(conn) as active:
        training = active.execute(
            "SELECT org_id, owner_user_id FROM trainings WHERE id = ?", (int(training_id),)
        ).fetchone()
        if training is None:
            raise ValueError(f"训练不存在: {training_id}")
        if int(training["owner_user_id"] or 0) != int(owner_user_id):
            raise PermissionError("只有训练的 owner 可以推送副本")
    for uid in target_user_ids:
        try:
            result = clone_for_user(
                int(training_id), int(uid), shared_by_user_id=int(owner_user_id)
            )
            delivered.append(result["training_id"])
        except PermissionError as exc:
            skipped.append({"user_id": int(uid), "reason": str(exc)})
    return {"delivered": delivered, "skipped": skipped}


def revoke_share_link(token: str, created_by: int, *, conn=None) -> bool:
    with transaction(conn) as active:
        cur = active.execute(
            "UPDATE share_links SET revoked_at = ? WHERE token = ? AND created_by = ? "
            "AND revoked_at IS NULL",
            (_now(), str(token), int(created_by)),
        )
        return cur.rowcount > 0


__all__ = [
    "clone_for_user",
    "create_share_link",
    "get_share_preview",
    "pull_by_token",
    "push_to_members",
    "revoke_share_link",
]
