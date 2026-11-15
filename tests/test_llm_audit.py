"""LLM 审计守卫测试：complete() 的成功 / 降级 / 彻底失败都必须在 llm_calls 落一行。

背景（change: llm-audit-unified-client）：此前出题、判分、探测、路径、变式、解析等
新链路成功调用不写 llm_calls，"所有调用可追溯"不成立。审计下沉到统一客户端后，
用本文件钉死三类路径的落账行为与 training_id 守卫。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.llm import client as llm_client  # noqa: E402

_TRAIN_QUESTION_OK = json.dumps(
    {
        "question": "RDB 和 AOF 的差异是什么？",
        "reference_answer": "RDB 是快照，AOF 是命令追加。",
        "difficulty": 2,
        "question_type": "qa",
        "options": [],
        "points": [
            {"point_id": "p1", "text": "说出 RDB 是快照持久化", "weight": 2, "is_required": True},
            {"point_id": "p2", "text": "说出 AOF 是命令追加", "weight": 2, "is_required": False},
        ],
    },
    ensure_ascii=False,
)


class TestLlmAudit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "audit.db")
        init_db()

        self._orig_call_api = llm_client._call_api
        self._orig_key = llm_client.DEEPSEEK_API_KEY

    def tearDown(self) -> None:
        llm_client._call_api = self._orig_call_api
        llm_client.DEEPSEEK_API_KEY = self._orig_key
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _make_training(self) -> int:
        row = queries.create_training(topic="审计测试", status="active")
        return int(row.id)

    def _rows(self) -> list[sqlite3.Row]:
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        try:
            return list(conn.execute("SELECT * FROM llm_calls ORDER BY id"))
        finally:
            conn.close()

    def _ok_api(self) -> None:
        llm_client.DEEPSEEK_API_KEY = "test-key"
        llm_client._call_api = lambda messages, *args, **kwargs: (_TRAIN_QUESTION_OK, 12, 34)  # type: ignore[assignment]

    def _broken_api(self) -> None:
        llm_client.DEEPSEEK_API_KEY = "test-key"

        def _boom(messages, *args, **kwargs):
            raise llm_client.LLMError("simulated outage")

        llm_client._call_api = _boom  # type: ignore[assignment]

    def test_success_records_one_row(self) -> None:
        self._ok_api()
        tid = self._make_training()
        result = llm_client.complete(
            "train_question",
            {
                "topic": "Redis",
                "knowledge_point": "持久化",
                "round_index": 1,
                "total_rounds": 5,
                "sample_text": "RDB 是快照持久化。",
            },
            training_id=tid,
        )
        self.assertTrue(result["output_json"])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["call_purpose"], "train_question")
        self.assertEqual(row["prompt_name"], "train_question")
        self.assertEqual(row["validation_result"], "pass")
        self.assertEqual(row["fallback_used"], 0)
        self.assertEqual(row["training_id"], tid)
        self.assertEqual(row["tokens_in"], 12)
        self.assertEqual(row["tokens_out"], 34)

    def test_fallback_records_with_flag(self) -> None:
        self._broken_api()
        tid = self._make_training()
        result = llm_client.complete(
            "goal_clarification",
            {"description": "学 Python", "known": "{}", "history": "", "rounds": 0},
            training_id=tid,
        )
        self.assertTrue(result["output_json"])  # 静态降级载荷
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fallback_used"], 1)
        self.assertEqual(rows[0]["prompt_name"], "goal_clarification")
        self.assertEqual(rows[0]["training_id"], tid)

    def test_failure_without_fallback_records_reason(self) -> None:
        self._broken_api()
        tid = self._make_training()
        with self.assertRaises(llm_client.LLMError):
            llm_client.complete("quiz_variant", {"blueprints": "[]"}, training_id=tid)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["validation_result"], "fail")
        self.assertIn("simulated outage", rows[0]["failure_reason"])
        self.assertEqual(rows[0]["fallback_used"], 0)

    def test_placeholder_training_id_recorded_as_null(self) -> None:
        self._ok_api()
        llm_client.complete(
            "train_question",
            {
                "topic": "Redis",
                "knowledge_point": "持久化",
                "round_index": 1,
                "total_rounds": 5,
                "sample_text": "RDB 是快照持久化。",
            },
            training_id=0,  # 老流程的占位值
        )
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["training_id"])

    def test_call_purpose_override(self) -> None:
        tid = self._make_training()
        llm_client.DEEPSEEK_API_KEY = "test-key"
        quiz_grade_ok = json.dumps(
            {
                "results": [
                    {
                        "item_key": "abc123",
                        "verdict": "pass",
                        "reason": "覆盖了必答要点",
                        "point_verdicts": [{"point_id": "p1", "verdict": "hit", "evidence": "快照"}],
                    }
                ]
            },
            ensure_ascii=False,
        )
        llm_client._call_api = lambda messages, *args, **kwargs: (quiz_grade_ok, 5, 6)  # type: ignore[assignment]
        llm_client.complete(
            "quiz_grade",
            {"items": "[]", "memory_block": ""},
            training_id=tid,
            call_purpose="daily_grade",
        )
        rows = self._rows()
        self.assertEqual(rows[0]["call_purpose"], "daily_grade")
        self.assertEqual(rows[0]["prompt_name"], "quiz_grade")


if __name__ == "__main__":
    unittest.main()
