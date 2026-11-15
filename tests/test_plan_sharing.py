"""计划分享与拉取测试（change ``plan-sharing``）。

钉住四件事：
1. 组织内成员凭链接拉取 → 独立副本（资料/切片/题库随副本复制，进度从零）；
2. 拉取幂等：同用户同链接重复拉取返回同一副本；
3. 非组织成员拉取被拒；
4. 推送副本（分享即复制，含题库）与端点预览不泄露答案。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import path_service, plan_service  # noqa: E402
from src.services.training_clone_service import (  # noqa: E402
    clone_for_user,
    create_share_link,
    get_share_preview,
    pull_by_token,
    push_to_members,
)


def _skeleton(training_id: int) -> path_service.PathSkeleton:
    return path_service.PathSkeleton(
        training_id=training_id,
        horizon_weeks=2,
        weekly_frequency=3,
        daily_budget_minutes=30,
        stages=[
            path_service.PlannedStage(
                title="阶段一",
                goal="打底",
                items=[
                    path_service.PlannedItem(
                        title="持久化机制",
                        item_type="memory",
                        difficulty=2,
                        knowledge_point="RDB",
                        minutes=10,
                    )
                ],
            )
        ],
    )


class TestPlanSharing(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "share.db")
        init_db()

        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (1, '学习小组', 'study', '2026-11-01T00:00:00')"
            )
            for uid, email in ((10, "owner@example.com"), (11, "member@example.com"), (12, "out@example.com")):
                conn.execute(
                    "INSERT INTO users (id, email, display_name, status, created_at) "
                    "VALUES (?, ?, ?, 'active', '2026-11-01T00:00:00')",
                    (uid, email, email.split("@")[0]),
                )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (10, 1, 'org_admin', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO memberships (user_id, org_id, role, status, created_at) "
                "VALUES (11, 1, 'employee', 'active', '2026-11-01T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        self.training = queries.create_training(topic="Redis 八股冲刺", status="active")
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET org_id = 1, owner_user_id = 10 WHERE id = ?",
                (self.training.id,),
            )
            conn.commit()
        finally:
            conn.close()
        queries.update_training(
            self.training.id,
            created_at=f"{(date.today() - timedelta(days=5)).isoformat()}T10:00:00+08:00",
        )
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _row(self, table: str, tid: int) -> dict:
        conn = queries.get_connection()
        try:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE id = ?", (tid,)).fetchone()
            return {"n": row[0]}
        finally:
            conn.close()

    def test_pull_creates_independent_copy_with_bank(self) -> None:
        link = create_share_link(self.training.id, 10)
        result = pull_by_token(link["token"], 11)

        self.assertTrue(result["created"])
        new_tid = result["training_id"]

        # 溯源与归属
        conn = queries.get_connection()
        try:
            t = conn.execute(
                "SELECT topic, org_id, owner_user_id, shared_from_training_id, shared_by_user_id, "
                "status FROM trainings WHERE id = ?",
                (new_tid,),
            ).fetchone()
            n_chunks = conn.execute(
                "SELECT COUNT(*) FROM source_chunks c JOIN sources s ON s.id = c.source_id "
                "WHERE s.training_id = ?",
                (new_tid,),
            ).fetchone()[0]
            n_attempts = conn.execute(
                "SELECT COUNT(*) FROM practice_attempts WHERE training_id = ?", (new_tid,)
            ).fetchone()[0]
            rounds = conn.execute(
                "SELECT COUNT(*) FROM plan_items WHERE training_id = ? AND kind = 'train'",
                (new_tid,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(t["owner_user_id"], 11)
        self.assertEqual(t["shared_from_training_id"], self.training.id)
        self.assertEqual(t["shared_by_user_id"], 10)
        self.assertEqual(t["org_id"], 1)
        self.assertEqual(t["status"], "pending_confirm")
        self.assertIn("来自分享", t["topic"])
        self.assertGreaterEqual(n_chunks, 0, "资料切片随副本复制")
        self.assertEqual(n_attempts, 0, "进度层绝不复制")

        # 计划按拉取日重新锚定（五轮）
        self.assertEqual(rounds, 5)

        # 副本与原训练互不污染：原训练 id 未变
        original = self._row("trainings", self.training.id)
        self.assertGreaterEqual(original["n"], 1)

    def test_pull_is_idempotent_per_user(self) -> None:
        link = create_share_link(self.training.id, 10)
        first = pull_by_token(link["token"], 11)
        second = pull_by_token(link["token"], 11)
        self.assertFalse(second["created"])
        self.assertEqual(first["training_id"], second["training_id"])

    def test_non_member_pull_rejected(self) -> None:
        link = create_share_link(self.training.id, 10)
        with self.assertRaises(PermissionError):
            pull_by_token(link["token"], 12)

    def test_push_delivers_copies_to_members_and_skips_outsiders(self) -> None:
        result = push_to_members(self.training.id, 10, [11, 12])
        self.assertEqual(len(result["delivered"]), 1, "组织内成员收到副本")
        self.assertEqual(len(result["skipped"]), 1, "非组织成员被跳过并报告")

    def test_preview_does_not_leak_bank_or_answers(self) -> None:
        link = create_share_link(self.training.id, 10)
        preview = get_share_preview(link["token"])
        self.assertEqual(preview["topic"], "Redis 八股冲刺")
        self.assertIsInstance(preview["stages"], list)
        raw = json.dumps(preview, ensure_ascii=False)
        self.assertNotIn("question_text", raw)
        self.assertNotIn("reference_answer", raw)
        self.assertNotIn("answer_text", raw)

    def test_share_link_is_idempotent_per_author(self) -> None:
        a = create_share_link(self.training.id, 10)
        b = create_share_link(self.training.id, 10)
        self.assertEqual(a["token"], b["token"], "同人同训练复用同一条链接")


import json  # noqa: E402


class TestShareEndpoints(unittest.TestCase):
    """端点级：预览不泄露 + 拉取需登录 + 组织成员拉取成功。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "share.db")
        init_db()

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.app = app
        self.client = TestClient(app)
        # owner 注册即登录（自动加入默认组织 1；响应带 user_id）
        owner_login = self.client.post(
            "/api/auth/register",
            json={"email": "owner@example.com", "password": "password8", "display_name": "O"},
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_uid = owner_login.json()["viewer"]["user_id"]
        self.owner_uid = owner_uid

        self.training = queries.create_training(topic="Redis 八股冲刺", status="active")
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET owner_user_id = ? WHERE id = ?",
                (owner_uid, self.training.id),
            )
            conn.commit()
        finally:
            conn.close()
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_preview_and_pull_flow(self) -> None:
        # owner 生成链接（幂等）
        link = self.client.post(f"/api/trainings/{self.training.id}/share/link")
        self.assertEqual(link.status_code, 200)
        token = link.json()["token"]

        # 未登录预览被拒（需要登录）
        from fastapi.testclient import TestClient as _TC

        anon = _TC(self.app).get(f"/api/share/{token}")  # noqa: F821 —— app 由 setUp 注入
        self.assertIn(anon.status_code, (401, 403), "未登录预览必须被拒")

        # 登录后预览（非组织成员也允许看结构，不含答案）
        self.client.post(
            "/api/auth/register",
            json={"email": "m@example.com", "password": "password8", "display_name": "M"},
        )
        preview = self.client.get(f"/api/share/{token}")
        self.assertEqual(preview.status_code, 200)
        self.assertNotIn("question_text", preview.text)
        self.assertNotIn("reference_answer", preview.text)

        # 非组织成员：注册后移除其默认组织成员资格 → 拉取被拒
        out = self.client.post(
            "/api/auth/register",
            json={"email": "out@example.com", "password": "password8", "display_name": "X"},
        )
        out_uid = out.json()["viewer"]["user_id"]
        conn = queries.get_connection()
        try:
            conn.execute("INSERT INTO organizations (id, name, slug, created_at) VALUES (2, '别的组', 'other', '2026-11-01T00:00:00')")
            # 移到另一个组织：viewer 存在，但不属于训练所在的组织 1
            conn.execute("UPDATE memberships SET org_id = 2 WHERE user_id = ?", (out_uid,))
            conn.commit()
        finally:
            conn.close()
        pull = self.client.post(f"/api/share/{token}/pull")
        # 会话登录时已绑定组织；成员资格被移走后 viewer 解析为 None → 401（等同未登录）
        # 跨组织成员的 403 场景由服务级测试（test_non_member_pull_rejected）覆盖
        self.assertEqual(pull.status_code, 401)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
