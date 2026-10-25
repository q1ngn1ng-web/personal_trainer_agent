"""按需解析服务测试：真实客户端契约下 schema 必须传入，否则 output_json 永远为空。

回归背景：``generate_explanation`` 曾以 ``schema=None`` 调用统一客户端，
而客户端仅在 ``schema`` 非空时才解析 ``output_json``，导致按需解析主路径
永远返回「模型未返回解析内容」。本测试打桩 ``_call_api`` 返回**符合 schema
的合法 JSON**，走真实 ``complete()`` 的解析与校验逻辑，防止契约再次漂移。
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

from src.db.sqlite import init_db  # noqa: E402
from src.services import explanation_service  # noqa: E402


class TestExplanationService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "explanation.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api

        def fake_call_api(messages):  # 模拟真实 API：返回符合 schema 的纯 JSON
            payload = {
                "explanation": "RDB 快照是某一时刻内存数据集的完整拷贝，由子进程写入，默认文件名 dump.rdb。",
                "source_refs": ["手册第 2 章"],
            }
            return json.dumps(payload, ensure_ascii=False), 100, 50

        client_module._call_api = fake_call_api

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _seed_question(self) -> int:
        from src.db import queries

        training = queries.create_training(topic="Redis 持久化", status="active")
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO question_bank "
                "(training_id, item_key, question_text, answer_text, banked_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (training.id, "q1", "RDB 的默认持久化文件名是什么？", "dump.rdb"),
            )
            conn.commit()
        finally:
            conn.close()
        return int(training.id)

    def test_generate_explanation_parses_under_real_client_contract(self) -> None:
        training_id = self._seed_question()

        result = explanation_service.generate_explanation(training_id, "q1")

        self.assertTrue(
            result.get("ok"),
            f"按需解析在真实客户端契约下必须成功，实际返回：{result}",
        )
        self.assertIn("dump.rdb", str(result.get("text", "")))

    def test_generate_explanation_persists_row(self) -> None:
        from src.db import queries

        training_id = self._seed_question()
        explanation_service.generate_explanation(training_id, "q1")

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT explanation_text, source_refs FROM explanations "
                "WHERE training_id = ? AND item_key = ?",
                (training_id, "q1"),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "解析成功后必须落库（llm 调用可追溯）")
        self.assertIn("dump.rdb", str(row["explanation_text"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
