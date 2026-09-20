"""删除训练：级联清理必须彻底，且不能误删其他训练的数据。"""
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
from src.db.sqlite import get_connection, init_db  # noqa: E402
from src.services import edge_service, path_service, signal_service  # noqa: E402
from src.services import source_service as svc  # noqa: E402


class TestDeleteTraining(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "del.db")
        from src.llm import client as client_module

        self._client = client_module
        self._orig = client_module._call_api
        client_module._call_api = lambda messages: (_ for _ in ()).throw(  # type: ignore[assignment]
            client_module.LLMError("forced failure for test")
        )
        init_db()
        self.victim = self._seed("待删除训练")
        self.keeper = self._seed("保留训练")

    def tearDown(self) -> None:
        self._client._call_api = self._orig  # type: ignore[assignment]
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _seed(self, topic: str) -> int:
        training = queries.create_training(topic=topic, status="confirmed")
        source = svc.create_source(
            training.id,
            type="user_paste",
            title=f"{topic}-资料",
            content="# 第一章\n\n内容一段。\n\n## 1.1 小节\n\n内容二段。",
        )
        svc.parse_source(source.id)
        probe = edge_service.generate_probe_items(training.id, topic=topic)
        for item in probe.items:
            item.answer = "不知道"
            item.verdict = "fail"
            item.state = edge_service.judge_state("fail", item.difficulty)
        edge_service.save_probe(probe)
        skeleton, _ = path_service.generate_skeleton(training.id, topic=topic)
        path_service.save_skeleton(skeleton)
        signal_service.process_signal(training.id, "too_hard")
        return training.id

    def _counts(self, training_id: int) -> dict[str, int]:
        conn = get_connection()
        try:
            tables = (
                "sources",
                "edge_assessments",
                "learning_signals",
                "adjustment_log",
                "training_paths",
            )
            counts = {
                table: int(
                    conn.execute(
                        f"SELECT COUNT(*) AS n FROM {table} WHERE training_id = ?", (training_id,)
                    ).fetchone()["n"]
                )
                for table in tables
            }
            # source_chunks 通过 sources 关联（它自己没有 training_id）
            counts["source_chunks"] = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM source_chunks WHERE source_id IN "
                    "(SELECT id FROM sources WHERE training_id = ?)",
                    (training_id,),
                ).fetchone()["n"]
            )
            return counts
        finally:
            conn.close()

    def test_seed_creates_related_rows(self) -> None:
        counts = self._counts(self.victim)
        self.assertGreater(counts["sources"], 0)
        self.assertGreater(counts["source_chunks"], 0)
        self.assertGreater(counts["training_paths"], 0)

    def test_delete_removes_training_and_all_related_rows(self) -> None:
        self.assertTrue(queries.delete_training(self.victim))
        self.assertIsNone(queries.get_training(self.victim))
        for table, count in self._counts(self.victim).items():
            with self.subTest(table=table):
                self.assertEqual(count, 0, f"{table} 仍有残留")

    def test_delete_does_not_touch_other_training(self) -> None:
        before = self._counts(self.keeper)
        queries.delete_training(self.victim)
        after = self._counts(self.keeper)
        self.assertEqual(before, after)
        self.assertIsNotNone(queries.get_training(self.keeper))

    def test_delete_missing_training_returns_false(self) -> None:
        self.assertFalse(queries.delete_training(999999))

    def test_foreign_key_check_clean_after_delete(self) -> None:
        queries.delete_training(self.victim)
        conn = get_connection()
        try:
            issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()
        self.assertEqual(len(issues), 0)


if __name__ == "__main__":
    unittest.main()
