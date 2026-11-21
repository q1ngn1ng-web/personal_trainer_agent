"""三档可见性测试（change ``content-visibility``，训练与资料同口径）。

钉住：
1. private：仅 owner（组织内其他成员不可见）；
2. specific：owner + 指定成员可见，未指定成员不可见；
3. public：同组织成员全部可见；
4. 可见性修改端点（owner 校验 + 取值校验 + shares 重置）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import path_service, plan_service  # noqa: E402


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


class TestVisibilityTiers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "vis.db")
        init_db()

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        # owner / member / outsider 三个账号（注册即入默认组织 1）
        self.owner_uid = self._register("owner@example.com")
        self.member_uid = self._register("member@example.com")
        self.outsider_uid = self._register("outsider@example.com")

        self.training = queries.create_training(topic="可见性测试训练", status="active")
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET owner_user_id = ? WHERE id = ?",
                (self.owner_uid, self.training.id),
            )
            conn.commit()
        finally:
            conn.close()
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)

        self.owner = TestClient(app)
        self._login(self.owner, "owner@example.com")
        self.member = TestClient(app)
        self._login(self.member, "member@example.com")

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _register(self, email: str) -> int:
        from fastapi.testclient import TestClient

        from src.api.app import app

        c = TestClient(app)
        resp = c.post(
            "/api/auth/register",
            json={"email": email, "password": "password8", "display_name": email.split("@")[0]},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["viewer"]["user_id"]

    def _login(self, client, email: str) -> None:
        resp = client.post("/api/auth/login", json={"email": email, "password": "password8"})
        assert resp.status_code == 200, resp.text

    def test_visibility_endpoints_owner_only(self) -> None:
        # 非 owner 修改可见性被拒
        resp = self.member.put(
            f"/api/trainings/{self.training.id}/visibility", json={"visibility": "public"}
        )
        self.assertEqual(resp.status_code, 403)
        # owner 修改成功
        resp = self.owner.put(
            f"/api/trainings/{self.training.id}/visibility", json={"visibility": "public"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["visibility"], "public")
        # 取值非法被拒
        resp = self.owner.put(
            f"/api/trainings/{self.training.id}/visibility", json={"visibility": "everyone"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_specific_shares_replace_and_grant_view(self) -> None:
        resp = self.owner.put(
            f"/api/trainings/{self.training.id}/visibility",
            json={"visibility": "specific", "shared_user_ids": [self.member_uid]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["shared_user_ids"], [self.member_uid])
        # 再次设置（替换语义）：指向 outsider
        resp = self.owner.put(
            f"/api/trainings/{self.training.id}/visibility",
            json={"visibility": "specific", "shared_user_ids": [self.outsider_uid]},
        )
        self.assertEqual(resp.json()["shared_user_ids"], [self.outsider_uid])
        # 共享表被替换：member 不再可见，outsider 可见
        from src.db import queries

        conn = queries.get_connection()
        try:
            shared = queries.list_training_shared_user_ids(self.training.id)
        finally:
            conn.close()
        self.assertEqual(shared, [self.outsider_uid])

    def test_can_view_training_three_tiers(self) -> None:
        from types import SimpleNamespace

        from src.core.permissions import can_view_training

        base = {"org_id": 1, "owner_user_id": self.owner_uid}

        def viewer(uid: int, org_id: int = 1):
            return SimpleNamespace(user_id=uid, org_id=org_id, role="employee", department_ids=frozenset())

        self.assertTrue(can_view_training(viewer(self.owner_uid), base))
        self.assertFalse(can_view_training(viewer(99), base), "private 默认他人不可见")

        public = {**base, "visibility": "public"}
        self.assertTrue(can_view_training(viewer(99), public))

        specific = {**base, "visibility": "specific"}
        self.assertFalse(can_view_training(viewer(99), specific, [self.member_uid]))
        self.assertTrue(
            can_view_training(viewer(self.member_uid), specific, [self.member_uid])
        )

        self.assertFalse(can_view_training(viewer(99, org_id=2), public), "跨组织不可见")

    def test_trainings_list_reflects_visibility(self) -> None:
        """端点级回归钉子：列表 payload 必须携带 visibility，否则三档过滤失效。"""
        resp = self.owner.get("/api/trainings")
        self.assertTrue(any(t["id"] == self.training.id for t in resp.json()["trainings"]))
        resp = self.member.get("/api/trainings")
        self.assertFalse(
            any(t["id"] == self.training.id for t in resp.json()["trainings"]),
            "private 默认他人不可见",
        )

        self.owner.put(f"/api/trainings/{self.training.id}/visibility", json={"visibility": "public"})
        resp = self.member.get("/api/trainings")
        self.assertTrue(
            any(t["id"] == self.training.id for t in resp.json()["trainings"]),
            "public 同组织可见",
        )

        self.owner.put(
            f"/api/trainings/{self.training.id}/visibility",
            json={"visibility": "specific", "shared_user_ids": [self.member_uid]},
        )
        resp = self.member.get("/api/trainings")
        self.assertTrue(
            any(t["id"] == self.training.id for t in resp.json()["trainings"]),
            "specific 指定人可见",
        )

        self.owner.put(f"/api/trainings/{self.training.id}/visibility", json={"visibility": "private"})
        resp = self.member.get("/api/trainings")
        self.assertFalse(
            any(t["id"] == self.training.id for t in resp.json()["trainings"]),
            "改回 private 后他人不可见",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
