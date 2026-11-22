"""教练记忆三层（change ``coach-memory-three-layers``）回归钉子。

钉住：
1. 连败纯函数：只数系统判分（llm/quiz/rule），自评 self 不计、practice-only
   不落 attempts 天然不计、pass 清零、提示 ≥3 触发含历次分数、开关可关；
2. submit_answer 响应只加键不改键（既有键一个不动）；
3. 会话小结：读时聚合（题数/通过率/错要点/最弱知识点/各题 streak）、空日不报错；
4. 端点契约：小结过训练可见性守卫（越权 403）、偏好读写、非法键/值 400。
"""
from __future__ import annotations

import json
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
from src.services import (  # noqa: E402
    answer_service,
    attempt_service,
    preferences_service,
    session_summary,
)


def _choice_payload() -> dict:
    return {
        "question": "Redis 持久化机制中，哪一种通过定期把内存数据生成快照文件保存？",
        "reference_answer": "RDB",
        "difficulty": 2,
        "question_type": "choice",
        "options": [
            {"key": "A", "text": "AOF 追加写命令日志", "is_correct": False},
            {"key": "B", "text": "RDB 定时生成内存快照", "is_correct": True},
            {"key": "C", "text": "混合持久化", "is_correct": False},
        ],
        "points": [{"point_id": "p1", "text": "答出 RDB", "weight": 2, "is_required": True}],
    }


class TestFailureStreak(unittest.TestCase):
    """连败纯函数规则（D2）：来源过滤 / pass 清零 / 阈值触发。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "streak.db")
        init_db()
        self.training_id = queries.create_training(topic="连败测试", status="active").id

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _record(self, item_key: str, result: str, source: str = "llm", score: float | None = 0.5) -> None:
        attempt_service.record_attempt(
            self.training_id,
            item_key,
            result,
            source=source,
            score=score,
            point_results=json.dumps({"detail": [{"point_id": "p1", "text": "要点A", "verdict": "wrong", "required": True}]})
            if result == "fail"
            else None,
        )

    def test_streak_counts_only_graded_sources_and_zeroes_on_pass(self) -> None:
        self._record("item-a", "fail", source="self")  # 自评：无客观信号，不计
        self._record("item-a", "fail", source="llm", score=0.4)
        self._record("item-a", "fail", source="rule", score=0.5)
        streak, scores = answer_service.failure_streak(self.training_id, "item-a")
        self.assertEqual(streak, 2, "自评不计，只数 llm/rule")
        self.assertEqual(scores, [0.4, 0.5], "历次分数时间正序")

        self._record("item-a", "pass", source="llm", score=0.9)
        streak, scores = answer_service.failure_streak(self.training_id, "item-a")
        self.assertEqual((streak, scores), (0, []), "pass 即清零")

    def test_hint_threshold_and_toggle(self) -> None:
        self.assertEqual(answer_service.coach_hint_text(2, [0.5, 0.6]), "", "未达阈值空串")
        hint = answer_service.coach_hint_text(3, [0.4, 0.5, 0.55])
        self.assertIn("3 次", hint)
        self.assertIn("0.40", hint)
        self.assertIn("深度解析", hint)

        # 开关默认开；显式关闭后 is_coach_hint_enabled=False
        self.assertTrue(preferences_service.is_coach_hint_enabled())
        preferences_service.set_preferences({"coach_hint_enabled": "0"})
        self.assertFalse(preferences_service.is_coach_hint_enabled())
        preferences_service.set_preferences({"coach_hint_enabled": "1"})

    def test_streak_per_item_isolated(self) -> None:
        self._record("item-b", "fail", source="llm", score=0.3)
        self._record("item-b", "fail", source="llm", score=0.35)
        self._record("item-c", "pass", source="llm", score=0.9)
        self.assertEqual(answer_service.failure_streak(self.training_id, "item-b")[0], 2)
        self.assertEqual(answer_service.failure_streak(self.training_id, "item-c")[0], 0)


class TestSubmitAnswerAdditiveKeys(unittest.TestCase):
    """submit_answer 响应只加键不改键：既有键一个不动，附加 streak/hint。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "submit.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._llm_calls = 0

        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            self._llm_calls += 1
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(_choice_payload(), ensure_ascii=False), 10, 20
            if "判分" in content or "批改" in content:
                # 首三次语义判 fail，第四次仍 fail（客观题本该走 rule——这里强制走 LLM 路径
                # 以覆盖 hint 生成；判分口径不变，只是 stub）
                return json.dumps(
                    {
                        "verdict": "fail",
                        "score": 0.4 + 0.05 * self._llm_calls,
                        "reason": "要点未答出",
                        "point_results": {"detail": [
                            {"point_id": "p1", "text": "答出 RDB", "verdict": "wrong", "required": True}
                        ]},
                    },
                    ensure_ascii=False,
                ), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        client_module._call_api = fake_call_api

        from src.services import path_service, plan_service

        training = queries.create_training(topic="附加字段训练", status="active")
        path_service.save_skeleton(
            path_service.PathSkeleton(
                training_id=training.id,
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
        )
        plan_service.generate_plan(training.id)
        self.training_id = training.id
        self.plan_id = plan_service.training_plan_items(training.id)[0].plan_id

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_fourth_fail_returns_streak_and_hint(self) -> None:
        base_keys = {
            "graded", "verdict", "reason", "score", "point_results",
            "reference_answer", "question_source", "mastered",
        }
        item_key = self._item_key()
        last: dict = {}
        for _ in range(3):
            last = answer_service.submit_answer(self.plan_id, "我觉得是 AOF")
        self.assertTrue(set(last.keys()) >= base_keys, "既有键一个不动")
        self.assertEqual(last["failure_streak"], 3, "第三次 fail 后 streak=3")
        self.assertIn("3 次", last["coach_hint"], "streak≥3 即提示（tasks 1.2 / spec MUST）")
        self.assertEqual(
            answer_service.failure_streak(self.training_id, item_key)[0], 3
        )

        last = answer_service.submit_answer(self.plan_id, "真的是 AOF 吧")
        self.assertEqual(last["failure_streak"], 4)
        self.assertIn("4 次", last["coach_hint"])
        self.assertIn("深度解析", last["coach_hint"])
        # 判分结果本身不受提示影响
        self.assertEqual(last["verdict"], "fail")
        self.assertTrue(last["graded"])

    def _item_key(self) -> str:
        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT item_key FROM plan_items WHERE id = ?", (self.plan_id,)
            ).fetchone()
        finally:
            conn.close()
        return str(row["item_key"])

    def test_pass_zeroes_and_no_hint(self) -> None:
        item_key = self._item_key()
        for _ in range(2):
            answer_service.submit_answer(self.plan_id, "AOF 吧")
        streak, scores = answer_service.failure_streak(self.training_id, item_key)
        self.assertGreaterEqual(streak, 2)
        attempt_service.record_attempt(
            self.training_id, item_key, "pass", source="llm", score=0.95
        )
        streak, scores = answer_service.failure_streak(self.training_id, item_key)
        self.assertEqual((streak, scores), (0, []))


class TestSessionSummary(unittest.TestCase):
    """会话小结：读时聚合 + 空日不报错。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "summary.db")
        init_db()
        self.training_id = queries.create_training(topic="小结测试", status="active").id

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _record_today(self, item_key: str, result: str, score: float, plan_id: int | None = None) -> None:
        attempt_service.record_attempt(
            self.training_id,
            item_key,
            result,
            source="llm",
            score=score,
            plan_id=plan_id,
            point_results=json.dumps(
                {
                    "detail": [
                        {"point_id": "p1", "text": "AOF 被说成日志", "verdict": "wrong", "required": True}
                    ]
                },
            )
            if result == "fail"
            else None,
        )

    def test_empty_day_returns_zero_summary(self) -> None:
        summary = session_summary.summarize_day(self.training_id, "2030-01-01")
        self.assertEqual(summary["question_count"], 0)
        self.assertIsNone(summary["pass_rate"])
        self.assertEqual(summary["mistake_points"], [])
        self.assertIsNone(summary["weakest_knowledge_point"])
        self.assertTrue(summary["narrative"])
        self.assertFalse(summary["llm_narrative_enabled"], "LLM 叙述开关默认关")

    def test_aggregates_day(self) -> None:
        self._record_today("item-a", "fail", 0.4)
        self._record_today("item-a", "fail", 0.5)
        self._record_today("item-a", "fail", 0.55)
        self._record_today("item-b", "pass", 0.95)
        summary = session_summary.summarize_day(self.training_id, None)
        self.assertEqual(summary["question_count"], 4)
        self.assertEqual(summary["item_count"], 2)
        self.assertAlmostEqual(summary["pass_rate"], 1 / 4, places=4)
        self.assertEqual(summary["mistake_points"][0]["point"], "AOF 被说成日志")
        self.assertEqual(summary["mistake_points"][0]["count"], 3)
        items = {b["item_key"]: b for b in summary["items"]}
        self.assertEqual(items["item-a"]["failure_streak"], 3)
        self.assertEqual(items["item-b"]["failure_streak"], 0)
        self.assertIn("连败", summary["narrative"], "连败≥3 进叙述")
        self.assertIn("高频错点", summary["narrative"])

    def test_only_today_counts(self) -> None:
        self._record_today("item-a", "fail", 0.4)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        summary = session_summary.summarize_day(self.training_id, yesterday)
        self.assertEqual(summary["question_count"], 0, "昨天的 attempt 不计入今天")


class TestEndpoints(unittest.TestCase):
    """端点契约：小结越权 403、偏好读写、非法键/值 400。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "ep.db")
        init_db()

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.app = app
        owner = TestClient(app)
        resp = owner.post(
            "/api/auth/register",
            json={"email": "owner@example.com", "password": "password8", "display_name": "O"},
        )
        assert resp.status_code == 200, resp.text
        self.owner_uid = resp.json()["viewer"]["user_id"]
        self.training_id = queries.create_training(topic="端点训练", status="active").id
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET owner_user_id = ? WHERE id = ?",
                (self.owner_uid, self.training_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.owner = owner

        self.outsider = TestClient(app)
        resp = self.outsider.post(
            "/api/auth/register",
            json={"email": "out@example.com", "password": "password8", "display_name": "X"},
        )
        assert resp.status_code == 200, resp.text

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_session_summary_endpoint(self) -> None:
        resp = self.owner.get(f"/api/trainings/{self.training_id}/session-summary")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("question_count", resp.json())
        # 非法日期 400
        bad = self.owner.get(f"/api/trainings/{self.training_id}/session-summary", params={"date": "not-a-date"})
        self.assertEqual(bad.status_code, 400)

    def test_session_summary_forbidden_for_outsider(self) -> None:
        resp = self.outsider.get(f"/api/trainings/{self.training_id}/session-summary")
        self.assertEqual(resp.status_code, 403, "private 训练对他人不可见")

    def test_preferences_roundtrip(self) -> None:
        resp = self.owner.get("/api/preferences")
        self.assertEqual(resp.status_code, 200)
        prefs = resp.json()["preferences"]
        self.assertEqual(prefs["coach_hint_enabled"], "1")
        self.assertEqual(prefs["daily_minutes_target"], "30")
        self.assertEqual(prefs["question_type_preference"], "any")

        resp = self.owner.put("/api/preferences", json={"values": {"daily_minutes_target": 20}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["preferences"]["daily_minutes_target"], "20")
        self.assertEqual(self.owner.get("/api/preferences").json()["preferences"]["daily_minutes_target"], "20")

    def test_preferences_rejects_bad_key_and_value(self) -> None:
        resp = self.owner.put("/api/preferences", json={"values": {"not_a_key": "1"}})
        self.assertEqual(resp.status_code, 400)
        resp = self.owner.put("/api/preferences", json={"values": {"daily_minutes_target": "abc"}})
        self.assertEqual(resp.status_code, 400)
        resp = self.owner.put("/api/preferences", json={"values": {"question_type_preference": "easy"}})
        self.assertEqual(resp.status_code, 400)
        resp = self.owner.put("/api/preferences", json={"values": {"daily_minutes_target": 99999}})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
