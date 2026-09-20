"""澄清流程的端到端冒烟测试（使用临时库，LLM 不可用时走降级路径）。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.goal import CLARIFY_HARD_LIMIT, is_generation_ready  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import goal_clarification_service as svc  # noqa: E402

_FAKE_OUTPUT: dict = {
    "draft": {"content": "英语虚拟语气", "level": "", "acceptance": {"type": "qualitative", "statement": ""}},
    "field_sources": {"content": "user_input"},
    "missing_fields": ["level", "acceptance"],
    "follow_up_question": "你希望达到什么程度？怎样才算学会？",
    "confidence": 0.4,
}


def _fake_complete(prompt_name: str, variables: dict, schema: dict | None = None, max_attempts: int = 3) -> dict:
    """替代真实 LLM 调用：返回固定草案，避免测试里的重试退避等待。"""
    return {
        "output_text": "{}",
        "output_json": dict(_FAKE_OUTPUT),
        "latency_ms": 1,
        "tokens_in": 0,
        "tokens_out": 0,
        "retry_count": 0,
        "model": "fake-model",
        "prompt_name": prompt_name,
        "prompt_version": "v1.0.0",
    }


class TestGoalClarificationFlow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = os.environ.get("DB_PATH")
        self._old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        self._orig_complete = svc.complete
        svc.complete = _fake_complete  # type: ignore[assignment]
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "test.db")
        init_db()

    def tearDown(self) -> None:
        svc.complete = self._orig_complete  # type: ignore[assignment]
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
        if self._old_key is not None:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key
        self._tmp.cleanup()

    def test_start_session_creates_pending_confirm_training(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        self.assertEqual(session.topic, "我想学英语虚拟语气")
        self.assertEqual(session.rounds, 0)
        self.assertTrue(session.draft.content)
        # LLM 不可用时降级，仍应给出追问而不是崩溃
        self.assertTrue(session.missing_fields)
        self.assertTrue(session.question)
        training = svc.queries.get_training(session.training_id)
        self.assertEqual(training.status, "pending_confirm")
        self.assertEqual(training.clarification_rounds, 0)

    def test_empty_topic_rejected(self) -> None:
        with self.assertRaises(ValueError):
            svc.start_session("   ")

    def test_unconfirmed_training_cannot_generate(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        training = svc.queries.get_training(session.training_id)
        self.assertFalse(is_generation_ready(training.status))

    def test_rounds_increase_until_hard_limit_then_can_confirm(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        for _ in range(CLARIFY_HARD_LIMIT):
            session = svc.continue_session(session.training_id, "会用，10 句改错题做对 8 句")
        # 达到硬限后应强制收口，缺失字段由系统给出建议值
        self.assertEqual(session.action, "close")
        self.assertTrue(session.can_confirm)
        self.assertTrue(session.inferred_fields)

    def test_confirm_writes_snapshot_and_transitions(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        for _ in range(CLARIFY_HARD_LIMIT):
            session = svc.continue_session(session.training_id, "会用，10 句改错题做对 8 句")
        training = svc.confirm(session.training_id)
        self.assertEqual(training.status, "confirmed")
        self.assertTrue(is_generation_ready(training.status))
        self.assertIsNotNone(training.goal_confirmed_at)
        snapshot = training.goal_json
        self.assertEqual(snapshot["schema_version"], "1.0.0")
        self.assertIn("field_sources", snapshot)
        self.assertTrue(snapshot["confirmed"])
        # 三个字段是值，不是布尔标记
        self.assertIsInstance(snapshot["content"], str)
        self.assertTrue(snapshot["level"])

    def test_confirm_rejects_incomplete_goal(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        self.assertFalse(session.can_confirm)
        with self.assertRaises(ValueError):
            svc.confirm(session.training_id)

    def test_load_session_restores_state(self) -> None:
        session = svc.start_session("我想学英语虚拟语气")
        restored = svc.load_session(session.training_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.topic, session.topic)


class TestGoalClarificationFallback(unittest.TestCase):
    """没有 API Key 时必须降级为表单式追问，而不是抛异常。"""

    def setUp(self) -> None:
        self._old_key = os.environ.pop("DEEPSEEK_API_KEY", None)

    def tearDown(self) -> None:
        if self._old_key is not None:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key

    def test_fallback_shape(self) -> None:
        from src.llm.client import complete

        result = complete("goal_clarification", {"description": "x", "known": "{}", "history": "", "rounds": 0})
        payload = result.get("output_json") or {}
        self.assertIn("missing_fields", payload)
        self.assertTrue(payload["follow_up_question"])
        self.assertEqual(payload["confidence"], 0.0)


if __name__ == "__main__":
    unittest.main()
