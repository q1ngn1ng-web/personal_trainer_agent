"""题目级深度解析测试：错因随作答落库、历史注入解析、端点契约。

对应 change ``item-history-deep-explanation``：
第一次答错、第二次又答错，第三次点「深度解析」时模型能看到前两次怎么错的并给改进动作。
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

from src.db.sqlite import init_db  # noqa: E402
from src.services import attempt_service, explanation_service  # noqa: E402

_POINT_RESULTS = json.dumps(
    {
        "score": 0.4,
        "detail": [
            {"point_id": "p1", "verdict": "missing", "required": True},
            {"point_id": "p2", "verdict": "wrong"},
        ],
    },
    ensure_ascii=False,
)


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


class TestAttemptMistakeReasons(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "history.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _training_id(self) -> int:
        from src.db import queries

        return int(queries.create_training(topic="Redis 持久化", status="active").id)

    def test_record_attempt_derives_mistake_reasons(self) -> None:
        tid = self._training_id()
        attempt = attempt_service.record_attempt(
            tid, "itemkey000001", "fail", point_results=_POINT_RESULTS, source="llm"
        )
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT mistake_reasons FROM practice_attempts WHERE id = ?", (attempt.id,)
        ).fetchone()
        conn.close()
        reasons = json.loads(row["mistake_reasons"])
        self.assertEqual(reasons["p1"], "key_omission")  # 必答缺失 → 关键遗漏
        self.assertEqual(reasons["p2"], "concept_confusion")

    def test_record_attempt_without_points_keeps_null(self) -> None:
        tid = self._training_id()
        attempt = attempt_service.record_attempt(tid, "itemkey000001", "pass")
        self.assertIsNone(attempt.to_dict().get("mistake_reasons"))


class TestItemExplanation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "explain.db")
        init_db()
        self._conn = sqlite3.connect(os.environ["DB_PATH"])
        self._conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self._conn.close()
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _seed(self) -> tuple[int, int]:
        from src.db import queries

        tid = int(queries.create_training(topic="Redis 持久化", status="active").id)
        self._conn.execute(
            "INSERT INTO sources (id, training_id, type, title, parse_status, imported_at) "
            "VALUES (1, ?, 'user_paste', '手册', 'ok', ?)",
            (tid, _now()),
        )
        self._conn.execute(
            "INSERT INTO source_chunks (id, source_id, ordinal, heading_path, text, char_count) "
            "VALUES (1, 1, 1, 'RDB > 快照', 'RDB 是快照持久化，适合备份与恢复。', 24)"
        )
        self._conn.execute(
            "INSERT INTO training_paths (training_id, version, status, created_at) "
            "VALUES (?, 1, 'confirmed', ?)",
            (tid, _now()),
        )
        path_id = int(self._conn.execute("SELECT MAX(id) FROM training_paths").fetchone()[0])
        self._conn.execute(
            "INSERT INTO path_stages (path_id, ordinal, title, goal) "
            "VALUES (?, 1, '阶段一', '打底')",
            (path_id,),
        )
        stage_id = int(self._conn.execute("SELECT MAX(id) FROM path_stages").fetchone()[0])
        self._conn.execute(
            "INSERT INTO training_items (stage_id, ordinal, title, item_key, knowledge_point, "
            "source_chunk_ids, status, created_at) VALUES (?, 1, 'RDB 是什么', 'itemkey000001', 'RDB', "
            "'[1]', 'pending', ?)",
            (stage_id, _now()),
        )
        self._conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, question, reference_answer, "
            "points, created_at) VALUES (?, 'itemkey000001', 1, 'train', date('now'), date('now'), "
            "date('now'), 'planned', 10, 'RDB 和 AOF 的差异？', 'RDB 快照，AOF 追加', ?, ?)",
            (
                tid,
                json.dumps(
                    [{"point_id": "p1", "text": "RDB 是快照", "weight": 2, "is_required": True}],
                    ensure_ascii=False,
                ),
                _now(),
            ),
        )
        plan_id = int(
            self._conn.execute("SELECT id FROM plan_items WHERE item_key='itemkey000001'").fetchone()["id"]
        )
        # 两次失败作答（错因由 record_attempt 自动推导）
        attempt_service.record_attempt(
            tid, "itemkey000001", "fail", plan_id=plan_id, round_index=1,
            answer_text="RDB 是日志", point_results=_POINT_RESULTS, source="llm",
            conn=self._conn,
        )
        attempt_service.record_attempt(
            tid, "itemkey000001", "fail", plan_id=plan_id, round_index=1,
            answer_text="RDB 是一种日志，每次写入都记录",
            point_results=_POINT_RESULTS, source="llm", conn=self._conn,
        )
        self._conn.commit()
        return tid, plan_id

    def test_generate_item_explanation_injects_history(self) -> None:
        tid, plan_id = self._seed()
        captured: dict[str, object] = {}

        def fake_complete(prompt_name, variables, **kwargs):
            captured["prompt_name"] = prompt_name
            captured["variables"] = variables
            captured["kwargs"] = kwargs
            return {
                "output_json": {"explanation": "RDB 是快照不是日志；你两次都把它说成日志。", "source_refs": []},
                "output_text": "",
                "prompt_name": "explanation",
                "prompt_version": "v1.1.0",
                "model": "test-model",
                "latency_ms": 1,
                "tokens_in": 1,
                "tokens_out": 1,
                "retry_count": 0,
            }

        orig = explanation_service.complete
        explanation_service.complete = fake_complete  # type: ignore[assignment]
        try:
            result = explanation_service.generate_item_explanation(tid, plan_id)
        finally:
            explanation_service.complete = orig  # type: ignore[assignment]

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts_used"], 2)
        variables = captured["variables"]
        history_text = variables["attempt_history"]
        self.assertIn("RDB 是日志", history_text)
        self.assertIn("每次写入都记录", history_text)
        self.assertIn("关键遗漏", history_text)  # 规则错因已翻译成中文标签
        self.assertIn("概念混淆", history_text)
        self.assertEqual(captured["prompt_name"], "explanation")
        self.assertEqual(captured["kwargs"].get("training_id"), tid)

        row = self._conn.execute(
            "SELECT prompt_version, model FROM explanations WHERE training_id = ?", (tid,)
        ).fetchone()
        self.assertEqual(row["prompt_version"], "v1.1.0")
        self.assertEqual(row["model"], "test-model")

    def test_generate_item_explanation_without_question(self) -> None:
        tid, _ = self._seed()
        self._conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, created_at) "
            "VALUES (?, 'noquestion0001', 1, 'train', date('now'), date('now'), date('now'), "
            "'planned', 10, ?)",
            (tid, _now()),
        )
        self._conn.commit()
        plan_id = int(
            self._conn.execute("SELECT id FROM plan_items WHERE item_key='noquestion0001'").fetchone()["id"]
        )
        result = explanation_service.generate_item_explanation(tid, plan_id)
        self.assertFalse(result["ok"])
        self.assertIn("题目", result["error"])


class TestExplanationEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "endpoint.db")
        self._old_auth = os.environ.get("TRAINER_AUTH")
        os.environ["TRAINER_AUTH"] = "0"  # 个人版免登录形态
        init_db()
        self._conn = sqlite3.connect(os.environ["DB_PATH"])
        self._conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self._conn.close()
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        if self._old_auth is None:
            os.environ.pop("TRAINER_AUTH", None)
        else:
            os.environ["TRAINER_AUTH"] = self._old_auth
        self._tmp.cleanup()

    def test_endpoint_contract(self) -> None:
        from fastapi.testclient import TestClient

        from src.api.app import app

        self._conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now(),),
        )
        self._conn.commit()
        tid = int(self._conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        self._conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, question, created_at) "
            "VALUES (?, 'ep0001item000', 1, 'train', date('now'), date('now'), date('now'), "
            "'planned', 10, 'RDB 是什么？', ?)",
            (tid, _now()),
        )
        self._conn.commit()
        plan_id = int(self._conn.execute("SELECT MAX(id) FROM plan_items").fetchone()[0])

        def fake_complete(prompt_name, variables, **kwargs):
            return {
                "output_json": {"explanation": "RDB 是快照持久化。", "source_refs": []},
                "output_text": "",
                "prompt_name": "explanation",
                "prompt_version": "v1.1.0",
                "model": "test-model",
                "latency_ms": 1,
                "tokens_in": 1,
                "tokens_out": 1,
                "retry_count": 0,
            }

        orig = explanation_service.complete
        explanation_service.complete = fake_complete  # type: ignore[assignment]
        try:
            client = TestClient(app)
            ok = client.post(f"/api/plan-items/{plan_id}/explanation")
            self.assertEqual(ok.status_code, 200)
            payload = ok.json()
            self.assertTrue(payload["ok"])
            self.assertIn("快照", payload["text"])

            missing = client.post("/api/plan-items/999999/explanation")
            self.assertEqual(missing.status_code, 404)
        finally:
            explanation_service.complete = orig  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
