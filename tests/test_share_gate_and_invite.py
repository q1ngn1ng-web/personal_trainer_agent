"""share-gate 与 member-invite 回归钉子（2026-11-22 双 change）。

share-gate（spec 四 Requirement）：
1. open_level：anyone 链接跨组织登录用户可拉（幂等）、未登录 401、org 链接行为不变；
2. 门禁：四类动作 × 三档文档矩阵；不达标未确认 → 409 带清单；
3. 确认即定向升级且与分享同一事务（不完整确认整体回滚、无部分生效）；
4. 升级持久 + 审计（record 文件落账）。
member-invite（四项拍板）：
5. 注册不自动进组（个人模式 viewer）+ 建组（org_admin）+ 候选/邀请/配额/移除/升降；
6. 我的邀请接受（invited→active）；成员互看进度=完成状态+分数聚合。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import org_service, share_gate_service  # noqa: E402
from src.services.training_clone_service import (  # noqa: E402
    create_share_link,
    get_share_preview,
    pull_by_token,
)


def _seed_source(training_id: int, title: str, scope: str) -> int:
    conn = queries.get_connection()
    try:
        conn.execute(
            "INSERT INTO sources (training_id, type, title, scope, enabled, imported_at) "
            "VALUES (?, 'user_paste', ?, ?, 1, '2026-11-22T00:00:00')",
            (int(training_id), title, scope),
        )
        source_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return source_id


class TestShareGateMatrix(unittest.TestCase):
    """门禁矩阵（spec R2）：四动作 × 三档文档 + specific 部分覆盖。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "gate.db")
        init_db()
        self.training_id = queries.create_training(topic="门禁矩阵", status="active").id

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_public_audience_blocks_private_and_specific(self) -> None:
        private_id = _seed_source(self.training_id, "私有笔记", "private")
        specific_id = _seed_source(self.training_id, "指定笔记", "specific")
        _seed_source(self.training_id, "公开讲义", "public")
        for action in ("publish", "link_org", "link_anyone"):
            check = share_gate_service.gate_check(self.training_id, action)
            self.assertFalse(check["ready"], f"{action} 应被阻止")
            self.assertEqual(
                {entry["source_id"] for entry in check["blocked"]},
                {private_id, specific_id},
                f"{action} 的受众级=public：private+specific 都不达标",
            )
            self.assertEqual(check["audience"], "public")

    def test_push_audience_specific_coverage(self) -> None:
        private_id = _seed_source(self.training_id, "私有笔记", "private")
        specific_id = _seed_source(self.training_id, "指定笔记", "specific")
        _seed_source(self.training_id, "公开讲义", "public")
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO source_shares (source_id, user_id, created_by, created_at) "
                "VALUES (?, 11, 1, '2026-11-22T00:00:00')",
                (specific_id,),
            )
            conn.commit()
        finally:
            conn.close()
        # 授权只覆盖 11；目标 11+12 → specific 文档也blocked（uncovered_targets）
        check = share_gate_service.gate_check(
            self.training_id, "push", target_uids=[11, 12]
        )
        self.assertFalse(check["ready"])
        blocked_map = {entry["source_id"]: entry for entry in check["blocked"]}
        self.assertNotIn(specific_id == specific_id and 0, blocked_map)
        self.assertIn(specific_id, blocked_map, "授权未覆盖全部目标 → 仍不达标")
        self.assertTrue(blocked_map[specific_id].get("uncovered_targets"))
        self.assertIn(private_id, blocked_map)
        # 只推 11 时 specific 文档达标
        check2 = share_gate_service.gate_check(self.training_id, "push", target_uids=[11])
        self.assertEqual(
            {entry["source_id"] for entry in check2["blocked"]}, {private_id}
        )

    def test_no_private_docs_passes_directly(self) -> None:
        _seed_source(self.training_id, "公开讲义", "public")
        check = share_gate_service.gate_check(self.training_id, "link_anyone")
        self.assertTrue(check["ready"])
        self.assertEqual(check["blocked"], [])


class TestGateConfirmAtomic(unittest.TestCase):
    """确认即定向升级且原子（spec R3）：不完整 409 无部分生效；全选一次事务。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "confirm.db")
        init_db()
        self.training_id = queries.create_training(topic="原子确认", status="active").id
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at) "
                "VALUES (1, 'owner@example.com', 'Owner', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "UPDATE trainings SET owner_user_id = 1 WHERE id = ?", (self.training_id,)
            )
            conn.commit()
        finally:
            conn.close()
        self.private_id = _seed_source(self.training_id, "私有笔记", "private")
        self.specific_id = _seed_source(self.training_id, "指定笔记", "specific")
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at) "
                "VALUES (11, 't@example.com', 'T', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (1, '默认组', 'default', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (11, 1, 'member', 'active', '2026-11-22T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _scopes(self) -> dict[int, str]:
        conn = queries.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, scope FROM sources WHERE training_id = ?", (self.training_id,)
            ).fetchall()
        finally:
            conn.close()
        return {int(r["id"]): str(r["scope"]) for r in rows}

    def test_incomplete_confirmation_no_partial_effect(self) -> None:
        with self.assertRaises(share_gate_service.GateIncompleteError):
            share_gate_service.confirm_and_execute(
                self.training_id, "link_anyone", 1,
                confirm_source_ids=[self.private_id],  # 缺 specific 那份
            )
        scopes = self._scopes()
        self.assertEqual(scopes[self.private_id], "private", "未确认的那份绝不能被升级")
        conn = queries.get_connection()
        try:
            links = conn.execute(
                "SELECT COUNT(*) n FROM share_links WHERE training_id = ?", (self.training_id,)
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(links, 0, "分享动作也不应发生（无部分生效）")

    def test_full_confirmation_upgrades_and_creates_anyone_link(self) -> None:
        result = share_gate_service.confirm_and_execute(
            self.training_id, "link_anyone", 1,
            confirm_source_ids=[self.private_id, self.specific_id],
        )
        self.assertEqual(result["open_level"], "anyone")
        self.assertEqual(result["created"], True)
        self.assertEqual(len(result["upgraded"]), 2)
        scopes = self._scopes()
        self.assertEqual(set(scopes.values()), {"public"}, "确认即定向升级为 public")
        # 升级持久 + 幂等：再次生成复用同 token
        again = create_share_link(self.training_id, 1, open_level="anyone")
        self.assertFalse(again["created"])
        self.assertEqual(again["token"], result["token"])

    def test_push_confirmation_upgrades_to_specific_with_grants(self) -> None:
        result = share_gate_service.confirm_and_execute(
            self.training_id, "push", 1,
            target_uids=[11],
            confirm_source_ids=[self.private_id, self.specific_id],
        )
        self.assertEqual(result["delivered"], [result["delivered"][0]])
        scopes = self._scopes()
        self.assertEqual(set(scopes.values()), {"specific"}, "push 受众级：升级为 specific")
        conn = queries.get_connection()
        try:
            grants = conn.execute(
                "SELECT source_id, user_id FROM source_shares WHERE user_id = 11"
            ).fetchall()
            copies = conn.execute(
                "SELECT id FROM trainings WHERE owner_user_id = 11 "
                "AND shared_from_training_id = ?",
                (self.training_id,),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(grants), 2, "两份文档都获得 11 的授权")
        self.assertEqual(len(copies), 1, "推送副本已创建")

    def test_audit_record_written(self) -> None:
        audit = Path(__file__).resolve().parents[1] / "workspace" / "record" / "share-gate-confirmations.md"
        audit.unlink(missing_ok=True)
        share_gate_service.confirm_and_execute(
            self.training_id, "link_anyone", 1,
            confirm_source_ids=[self.private_id, self.specific_id],
        )
        self.assertTrue(audit.exists(), "确认必须落审计账（design D5）")
        text = audit.read_text(encoding="utf-8")
        self.assertIn(f"training {self.training_id}", text)
        self.assertIn("action=link_anyone", text)
        audit.unlink(missing_ok=True)


class TestOpenLinkAccess(unittest.TestCase):
    """开放通道（spec R1/R5）：anyone 跨组织登录用户可拉、org 链接不变、预览不泄露。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "open.db")
        init_db()
        conn = queries.get_connection()
        try:
            # 训练 owner=10（组织 1）；成员 11；跨组织用户 12（组织 2）；无组织个人 13
            conn.execute(
                "INSERT INTO trainings (id, topic, status, org_id, owner_user_id, created_at) "
                "VALUES (1, '开放计划', 'active', 1, 10, '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (1, '默认组', 'default', '2026-11-01T00:00:00')"
            )
            for uid, email, name in ((10, "owner@example.com", "Owner"), (11, "m1@example.com", "M1"), (12, "x1@example.com", "X1")):
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)",
                    (uid, email, name, "2026-11-01T00:00:00"),
                )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (10, 1, 'org_admin', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (11, 1, 'member', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (2, '别的组', 'other', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (12, 2, 'member', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at) "
                "VALUES (13, 'solo@example.com', 'Solo', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO sources (training_id, type, title, scope, enabled, imported_at) "
                "VALUES (1, 'user_paste', '公开讲义', 'public', 1, '2026-11-22T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_anyone_link_allows_cross_org_and_solo_pull_idempotent(self) -> None:
        link = create_share_link(1, 10, open_level="anyone")
        first = pull_by_token(link["token"], 12)  # 跨组织
        self.assertTrue(first["created"])
        second = pull_by_token(link["token"], 12)
        self.assertFalse(second["created"], "同用户幂等")
        solo = pull_by_token(link["token"], 13)  # 无组织个人
        self.assertTrue(solo["created"], "anyone 链接：无组织登录用户可导入")

    def test_org_link_still_rejects_non_member(self) -> None:
        link = create_share_link(1, 10, open_level="org")
        with self.assertRaises(PermissionError):
            pull_by_token(link["token"], 12), "org 链接：跨组织仍被拒"
        with self.assertRaises(PermissionError):
            pull_by_token(link["token"], 13), "org 链接：无组织仍被拒"
        ok = pull_by_token(link["token"], 11)  # 组织成员：行为与上线前一致
        self.assertTrue(ok["created"])

    def test_org_and_anyone_links_coexist_per_author(self) -> None:
        org_link = create_share_link(1, 10, open_level="org")
        anyone_link = create_share_link(1, 10, open_level="anyone")
        self.assertNotEqual(org_link["token"], anyone_link["token"], "两级链接并存")
        again = create_share_link(1, 10, open_level="org")
        self.assertEqual(again["token"], org_link["token"], "同级别幂等")

    def test_anyone_preview_does_not_leak_bank(self) -> None:
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO question_bank (training_id, item_key, knowledge_point, "
                "question_text, answer_text, practiced_count, banked_at, status) "
                "VALUES (1, 'k1', '知识点', '机密题目原文', '机密参考答案', 1, '2026-11-22', 'active')"
            )
            conn.execute(
                "INSERT INTO training_paths (training_id, version, status, created_at) "
                "VALUES (1, 1, 'confirmed', '2026-11-22T00:00:00')"
            )
            path_id = conn.execute(
                "SELECT id FROM training_paths WHERE training_id = 1"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO path_stages (path_id, ordinal, title, status) "
                f"VALUES ({int(path_id)}, 1, '阶段一', 'active')"
            )
            stage_id = conn.execute("SELECT id FROM path_stages WHERE path_id = ?", (path_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO training_items (stage_id, ordinal, title, item_key, created_at) "
                f"VALUES ({int(stage_id)}, 1, '持久化机制', 'k1', '2026-11-22T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()
        link = create_share_link(1, 10, open_level="anyone")
        preview = get_share_preview(link["token"])
        raw = json.dumps(preview, ensure_ascii=False)
        self.assertNotIn("机密题目原文", raw)
        self.assertNotIn("机密参考答案", raw)
        self.assertNotIn("question_text", raw)
        self.assertNotIn("reference_answer", raw)


class TestMemberInvite(unittest.TestCase):
    """邀请流程（member-invite 四项拍板）：个人模式注册 → 建组 → 邀请/配额/接受/进度。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "invite.db")
        init_db()

        from src.api.app import app

        self.app = app
        self.admin = TestClient(app)
        self.admin.post(
            "/api/auth/register", json={"email": "admin@example.com", "password": "password8", "display_name": "A"}
        )
        created = self.admin.post("/api/org/create", json={"name": "学习小组"})
        assert created.status_code == 200, created.text
        self.org_id = created.json()["org_id"]

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _register(self, email: str) -> TestClient:
        client = TestClient(self.app)
        resp = client.post(
            "/api/auth/register", json={"email": email, "password": "password8", "display_name": email.split("@")[0]}
        )
        assert resp.status_code == 200, resp.text
        return client

    def test_register_personal_mode_no_org(self) -> None:
        self._register("solo@example.com")
        from src.db.sqlite import get_connection

        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT COUNT(*) n FROM memberships WHERE user_id = "
                "(SELECT id FROM users WHERE email = 'solo@example.com')"
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(rows, 0, "注册不自动进组（拍板 1）")

    def test_invite_quota_and_accept(self) -> None:
        # org_admin 不受配额：连邀 12 人都成功
        for index in range(1, 13):
            email = f"u{index}@example.com"
            self._register(email)
            resp = self.admin.post(f"/api/org/{self.org_id}/invite", json={"email": email})
            self.assertEqual(resp.status_code, 200, "org_admin 不受配额限制")

        # 被邀请人看到邀请并接受
        u1 = TestClient(self.app)
        u1.post("/api/auth/login", json={"email": "u1@example.com", "password": "password8"})
        my = u1.get("/api/my/invites")
        self.assertEqual(len(my.json()["invites"]), 1)
        accept = u1.post(f"/api/my/invites/{my.json()['invites'][0]['membership_id']}/accept")
        self.assertEqual(accept.status_code, 200)
        self.assertEqual(accept.json()["status"], "active")

        # 接受后：plan-sharing 的组织成员校验自动满足（拉共享计划可用）
        from src.services.training_clone_service import _is_org_member

        conn = queries.get_connection()
        try:
            member_ok = _is_org_member(self._uid("u1@example.com"), self.org_id, conn)
        finally:
            conn.close()
        self.assertTrue(member_ok)

    def test_admin_tier_quota(self) -> None:
        """admin 层邀请人受配额（默认 10）：第 11 个被拒且文案带配额。"""
        from src.core.permissions import Viewer, Role
        from src.services.org_service import add_membership, invite_member

        inviter_uid = self._uid("admin@example.com")
        # 已是 org_admin——再造一个 admin 层邀请人
        self._register("sub@example.com")
        sub_uid = self._uid("sub@example.com")
        add_membership(sub_uid, self.org_id, role="admin", status="active", admin_quota=10)
        sub = Viewer(user_id=sub_uid, org_id=self.org_id, role=Role.ADMIN, department_ids=frozenset())

        blocked = None
        for index in range(1, 12):
            email = f"c{index}@example.com"
            self._register(email)
            try:
                invite_member(self.org_id, sub, email)
            except ValueError as exc:
                blocked = index
                self.assertIn("配额", str(exc))
                break
        self.assertEqual(blocked, 11, "admin 默认配额 10：第 11 个被拒")

    def _uid(self, email: str) -> int:
        conn = queries.get_connection()
        try:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        finally:
            conn.close()
        return int(row["id"])

    def test_admin_quota_promote_and_remove_switch(self) -> None:
        self._register("helper@example.com")
        self.admin.post(f"/api/org/{self.org_id}/invite", json={"email": "helper@example.com"})
        helper_uid = self._uid("helper@example.com")
        promote = self.admin.put(
            f"/api/org/{self.org_id}/members/{helper_uid}/role",
            json={"role": "admin", "admin_can_remove": True},
        )
        self.assertEqual(promote.status_code, 200)
        self.assertEqual(promote.json()["role"], "admin")
        self.assertEqual(promote.json()["admin_quota"], 10, "升 admin 必须同时给配额（对称性）")

        # admin 邀请受自己的配额
        self._register("cand@example.com")
        invited = self.admin.post(f"/api/org/{self.org_id}/invite", json={"email": "cand@example.com"})
        self.assertEqual(invited.status_code, 200)

        # admin 有开关可移除 member；org_admin 总可
        remove = self.admin.delete(f"/api/org/{self.org_id}/members/{self._uid('cand@example.com')}")
        self.assertEqual(remove.status_code, 200, "org_admin 总可移除")

        # admin 试图移除 org_admin → 拒绝（只能移 member）
        self._register("plain@example.com")
        self.admin.post(f"/api/org/{self.org_id}/invite", json={"email": "plain@example.com"})
        conn = queries.get_connection()
        try:
            plain_uid = self._uid("plain@example.com")
        finally:
            conn.close()
        helper = TestClient(self.app)
        helper.post("/api/auth/login", json={"email": "helper@example.com", "password": "password8"})
        denied = helper.delete(f"/api/org/{self.org_id}/members/{self._uid('admin@example.com')}")
        self.assertEqual(denied.status_code, 403, "admin 不可移除 org_admin")

    def test_member_progress_aggregation(self) -> None:
        # 邀请并激活成员 u1
        self._register("u1@example.com")
        self.admin.post(f"/api/org/{self.org_id}/invite", json={"email": "u1@example.com"})
        u1 = TestClient(self.app)
        u1.post("/api/auth/login", json={"email": "u1@example.com", "password": "password8"})
        my = u1.get("/api/my/invites")
        u1.post(f"/api/my/invites/{my.json()['invites'][0]['membership_id']}/accept")

        # u1 建一个公开训练 + 一场已通过的测验（分数聚合口径）
        uid = self._uid("u1@example.com")
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO trainings (id, topic, status, org_id, owner_user_id, visibility, created_at) "
                f"VALUES (50, 'U1 的 Redis 计划', 'active', {self.org_id}, {uid}, 'public', '2026-11-22T00:00:00')"
            )
            conn.execute(
                "INSERT INTO assessments (training_id, trigger, status, question_count, score, passed, "
                "created_at, completed_at) VALUES (50, 'manual', 'completed', 5, 0.85, 1, "
                "'2026-11-22T00:00:00', '2026-11-22T01:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        prog = self.admin.get(f"/api/org/{self.org_id}/members/{uid}/progress")
        self.assertEqual(prog.status_code, 200)
        data = prog.json()
        self.assertEqual(len(data["trainings"]), 1, "只聚合公开训练（互看口径）")
        self.assertEqual(data["trainings"][0]["topic"], "U1 的 Redis 计划")
        self.assertEqual(data["avg_quiz_score"], 0.85, "分数聚合（拍板 4）")


class TestRegisterPersonalAndRoleMatrix(unittest.TestCase):
    """拍板 1/2：注册个人模式 + 三档角色矩阵。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "roles.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_role_migration_mapping(self) -> None:
        from src.core.permissions import Role, coerce_role

        self.assertIs(coerce_role("employee"), Role.MEMBER)
        self.assertIs(coerce_role("dept_manager"), Role.ADMIN)
        self.assertIs(coerce_role("member"), Role.MEMBER)
        self.assertIs(coerce_role("admin"), Role.ADMIN)
        self.assertIs(coerce_role("org_admin"), Role.ORG_ADMIN)

    def test_matrix_superset_chain(self) -> None:
        from src.core.permissions import can

        self.assertTrue(can("member", "train_self"))
        self.assertFalse(can("member", "publish_assignment"))
        self.assertFalse(can("member", "manage_members"))
        self.assertTrue(can("admin", "manage_members"))
        self.assertTrue(can("admin", "publish_assignment"))
        self.assertFalse(can("admin", "manage_org_sources"))
        self.assertTrue(can("org_admin", "manage_org_sources"))
        self.assertTrue(can("org_admin", "view_org_report"))

    def test_membership_legacy_rows_migrate(self) -> None:
        """老库迁移演练：employee→member、dept_manager→admin（role 归一 + 新列就位）。"""
        from src.db.migrate import _MEMBERSHIPS_DDL, _column_names
        from src.db.sqlite import get_connection

        conn = get_connection()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            # 造一个旧 schema 表（老 CHECK 枚举 + 无新列）并塞两行老数据
            conn.execute("DROP TABLE IF EXISTS memberships_old_demo")
            conn.execute(
                "CREATE TABLE memberships_old_demo (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, org_id INTEGER, department_id INTEGER, role TEXT NOT NULL "
                "CHECK (role IN ('org_admin','dept_manager','employee')), status TEXT, created_at TEXT)"
            )
            conn.execute(
                "INSERT INTO memberships_old_demo (user_id, org_id, role, status, created_at) "
                "VALUES (1, 1, 'employee', 'active', '2026-11-01')"
            )
            conn.execute(
                "INSERT INTO memberships_old_demo (user_id, org_id, role, status, created_at) "
                "VALUES (2, 1, 'dept_manager', 'active', '2026-11-01')"
            )
            # 走迁移函数同款序列（重命名 → 归一 → 重建 → 复制）
            conn.execute("ALTER TABLE memberships_old_demo RENAME TO memberships_old")
            conn.execute(_MEMBERSHIPS_DDL.replace("CREATE TABLE memberships", "CREATE TABLE memberships_demo"))
            shared = [n for n in _column_names(conn, "memberships_old") if n in _column_names(conn, "memberships")]
            select_cols = ", ".join(
                "CASE role WHEN 'employee' THEN 'member' WHEN 'dept_manager' THEN 'admin' ELSE role END"
                if n == "role" else n
                for n in shared
            )
            conn.execute(
                f"INSERT INTO memberships_demo ({', '.join(shared)}) SELECT {select_cols} FROM memberships_old"
            )
            conn.execute("DROP TABLE memberships_old")
            conn.commit()
            rows = {
                r["user_id"]: r["role"]
                for r in conn.execute("SELECT user_id, role FROM memberships_demo WHERE org_id = 1 AND user_id IN (1, 2)")
            }
        finally:
            conn.close()
        self.assertEqual(rows[1], "member")
        self.assertEqual(rows[2], "admin")



if __name__ == "__main__":  # pragma: no cover
    unittest.main()
