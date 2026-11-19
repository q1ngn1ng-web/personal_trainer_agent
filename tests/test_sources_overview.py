"""资料总览聚合测试（按内容指纹聚合，回答「被几个训练计划引用」）。"""
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
from src.services.source_service import sources_overview  # noqa: E402


def _seed_source(conn, training_id: int, title: str, checksum: str | None, chunks: int = 2) -> None:
    conn.execute(
        "INSERT INTO sources (training_id, type, title, snapshot_text, checksum, "
        "parse_status, imported_at) VALUES (?, 'user_paste', ?, '内容', ?, "
        "'ok', '2026-11-01T00:00:00')",
        (training_id, title, checksum),
    )
    source_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in range(chunks):
        conn.execute(
            "INSERT INTO source_chunks (source_id, ordinal, heading_path, text, char_count) "
            "VALUES (?, ?, '', ?, ?)",
            (source_id, i + 1, f"切片{i}", 50),
        )


class TestSourcesOverview(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "src.db")
        init_db()

        conn = queries.get_connection()
        try:
            # 两个训练共享同一份文档（同 checksum），另一个训练用独立文档
            conn.execute(
                "INSERT INTO trainings (id, topic, status, created_at) "
                "VALUES (1, 'Redis 八股冲刺', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO trainings (id, topic, status, created_at) "
                "VALUES (2, 'Redis 八股冲刺（任务分享副本）', 'active', '2026-11-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO trainings (id, topic, status, created_at) "
                "VALUES (3, 'MySQL 索引优化', 'active', '2026-11-01T00:00:00')"
            )
            _seed_source(conn, 1, "Redis 持久化八股文.pdf", "ck-shared", chunks=19)
            _seed_source(conn, 2, "Redis 持久化八股文.pdf（任务分享）", "ck-shared", chunks=19)
            _seed_source(conn, 3, "MySQL 索引要点", "ck-mysql", chunks=3)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_shared_document_aggregates_reference_count(self) -> None:
        rows = sources_overview(None)
        shared = [r for r in rows if r["checksum"] == "ck-shared"]
        self.assertEqual(len(shared), 1, "同 checksum 聚合为一条")
        g = shared[0]
        self.assertEqual(g["reference_count"], 2, "同一文档被 2 个训练计划引用")
        self.assertEqual(g["chunk_total"], 38, "切片数跨副本累加")
        self.assertEqual(len(g["trainings"]), 2, "引用的训练计划列表")

    def test_distinct_documents_stay_separate(self) -> None:
        rows = sources_overview(None)
        mysql = [r for r in rows if r["checksum"] == "ck-mysql"]
        self.assertEqual(len(mysql), 1)
        self.assertEqual(mysql[0]["reference_count"], 1)

    def test_visibility_filter_limits_references(self) -> None:
        # 只看得见训练 1 时：同文档的引用计数按可见口径降为 1
        rows = sources_overview([1])
        shared = [r for r in rows if r["checksum"] == "ck-shared"]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["reference_count"], 1, "不可见训练的引用不计入")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
