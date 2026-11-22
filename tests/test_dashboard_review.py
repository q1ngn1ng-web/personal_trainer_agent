"""仪表盘与周复盘端点测试（第一版 Streamlit → Vue 迁移的回归钉子）。"""
from __future__ import annotations

import os
import sqlite3
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


class TestDashboardAndReview(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "dash.db")
        init_db()

        # 周复盘的 LLM 走启发式兜底（不联网）
        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api

        def _no_key(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            raise client_module.LLMError("no key in test")

        client_module._call_api = _no_key

        training = queries.create_training(topic="Redis 持久化", status="active")
        queries.update_training(
            training.id,
            created_at=f"{(date.today() - timedelta(days=3)).isoformat()}T10:00:00+08:00",
        )
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        reg = self.client.post(
            "/api/auth/register",
            json={"email": "o@example.com", "password": "password8", "display_name": "O"},
        )
        self.assertEqual(reg.status_code, 200)
        # member-invite：注册不再自动进组——显式入默认组织（本测试依赖组织可见性口径）
        from src.services.org_service import add_membership

        add_membership(reg.json()["viewer"]["user_id"], 1, role="member")

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_dashboard_endpoint(self) -> None:
        resp = self.client.get("/api/dashboard")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreaterEqual(body["total_all"], 1)
        match = [t for t in body["trainings"] if t["training_id"] == self.training.id]
        self.assertTrue(match, "仪表盘应包含本次训练")
        self.assertIn("consecutive_days", match[0])
        self.assertIn("today_completion", match[0])
        self.assertEqual(match[0]["status"], "active")

    def test_review_prepare_uses_heuristic_fallback(self) -> None:
        resp = self.client.get(f"/api/trainings/{self.training.id}/review/weekly")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("week_start", body["metrics"])
        self.assertIn("next_week_focus", body["suggestion"])
        self.assertTrue(body["suggestion"]["fallback_used"], "断路环境下应使用启发式兜底")
        self.assertFalse(body["applied"])

    def test_review_apply_persists_and_archives(self) -> None:
        prep = self.client.get(f"/api/trainings/{self.training.id}/review/weekly").json()
        apply_resp = self.client.post(
            f"/api/trainings/{self.training.id}/review/apply",
            json={"suggestion": prep["suggestion"]},
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json()["applied"])

        conn = queries.get_connection()
        try:
            archives = conn.execute(
                "SELECT user_action FROM review_archives WHERE training_id = ?", (self.training.id,)
            ).fetchall()
            baseline = conn.execute(
                "SELECT COUNT(*) FROM baseline_history WHERE training_id = ?", (self.training.id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual([a["user_action"] for a in archives], ["confirmed"])
        self.assertGreaterEqual(baseline, 1, "应用建议必须写基线历史")

    def test_review_skip_archives_without_changes(self) -> None:
        skip_resp = self.client.post(f"/api/trainings/{self.training.id}/review/skip")
        self.assertEqual(skip_resp.status_code, 200)
        self.assertFalse(skip_resp.json()["applied"])

        conn = queries.get_connection()
        try:
            archives = conn.execute(
                "SELECT user_action FROM review_archives WHERE training_id = ?", (self.training.id,)
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([a["user_action"] for a in archives], ["skipped"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
