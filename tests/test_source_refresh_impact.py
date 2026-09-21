"""刷新网页快照的影响面与回指清理测试（审计 M3）与影响面多切片漏报修复（S2）。"""
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

from src.core.source import Chunk, compute_impact  # noqa: E402
from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import path_service, source_service as svc, web_source  # noqa: E402

_OLD_MD = """# 持久化总览

Redis 有两种持久化方式。

## RDB

快照式持久化，按时间点落盘。

## AOF

日志式持久化，追加写命令。
"""

_NEW_MD = """# 持久化总览

Redis 有两种持久化方式。

## RDB

快照式持久化，按时间点落盘（fork 子进程写盘）。

## AOF

日志式持久化，追加写命令。

## 混合持久化

RDB 与 AOF 可以一起用。
"""


class TestComputeImpactManyChunks(unittest.TestCase):
    def test_change_in_later_chunk_of_same_heading_is_detected(self) -> None:
        """同一标题下被切成多片时，后续片段的变化也必须报出来（审计 S2）。"""
        old = [
            Chunk(ordinal=0, heading_path="A", text="x" * 2000),
            Chunk(ordinal=1, heading_path="A", text="tail-旧"),
            Chunk(ordinal=2, heading_path="B", text="B 的内容"),
        ]
        new = [
            Chunk(ordinal=0, heading_path="A", text="x" * 2000),
            Chunk(ordinal=1, heading_path="A", text="tail-新"),
            Chunk(ordinal=2, heading_path="B", text="B 的内容"),
        ]
        report = compute_impact(old, new)
        self.assertEqual(report.changed, ["A"])
        self.assertEqual(report.added, [])
        self.assertEqual(report.removed, [])

    def test_added_heading_detected(self) -> None:
        old = [Chunk(ordinal=0, heading_path="A", text="a")]
        new = [Chunk(ordinal=0, heading_path="A", text="a"), Chunk(ordinal=1, heading_path="C", text="c")]
        report = compute_impact(old, new)
        self.assertEqual(report.added, ["C"])


class TestRefreshSnapshotReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "refresh.db")
        init_db()
        self.training = queries.create_training(topic="Redis 持久化", status="active")
        self._saved_fetch = getattr(web_source, "fetch_and_extract", None)

    def tearDown(self) -> None:
        if self._saved_fetch is not None:
            web_source.fetch_and_extract = self._saved_fetch  # type: ignore[assignment]
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _patch_fetch(self, text: str) -> None:
        def _fake(url: str, timeout: float = 15.0):
            page = web_source.FetchedPage(
                url=url,
                final_url=url,
                status=200,
                html="<html></html>",
                fetched_at="2026-09-21T00:00:00Z",
            )
            return page, text

        self._orig_fetch = web_source.fetch_and_extract
        web_source.fetch_and_extract = _fake  # type: ignore[assignment]

    def _make_path_item_linking(self, chunk_ids: list[int]) -> None:
        skeleton = path_service.PathSkeleton(
            training_id=self.training.id,
            horizon_weeks=2,
            weekly_frequency=3,
            daily_budget_minutes=30,
            stages=[
                path_service.PlannedStage(
                    title="阶段一",
                    goal="打底",
                    items=[
                        path_service.PlannedItem(
                            title="RDB 与 AOF 的区别",
                            item_type="comprehension",
                            difficulty=3,
                            knowledge_point="RDB",
                            minutes=15,
                        )
                    ],
                )
            ],
        )
        path_service.save_skeleton(skeleton)
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE training_items SET source_chunk_ids = ? WHERE stage_id IN "
                "(SELECT id FROM path_stages WHERE path_id IN "
                "(SELECT id FROM training_paths WHERE training_id = ?))",
                (json.dumps(chunk_ids), self.training.id),
            )
            conn.commit()
        finally:
            conn.close()

    def _stale_link_count(self) -> int:
        conn = queries.get_connection()
        try:
            valid = {
                int(row["id"])
                for row in conn.execute(
                    "SELECT c.id FROM source_chunks c JOIN sources s ON s.id = c.source_id "
                    "WHERE s.training_id = ?",
                    (self.training.id,),
                ).fetchall()
            }
            rows = conn.execute("SELECT source_chunk_ids FROM training_items").fetchall()
        finally:
            conn.close()
        stale = 0
        for row in rows:
            raw = row["source_chunk_ids"]
            ids = json.loads(raw) if isinstance(raw, str) and raw else []
            stale += sum(1 for value in ids if int(value) not in valid)
        return stale

    def test_refresh_reports_impact_and_cleans_dangling_links(self) -> None:
        self._patch_fetch(_OLD_MD)
        try:
            source = svc.fetch_web_source(self.training.id, "https://example.com/redis")
        finally:
            web_source.fetch_and_extract = self._orig_fetch  # type: ignore[assignment]
        self.assertEqual(source.parse_status, "ok")

        old_chunks = svc.list_chunks(source.id, limit=1000)
        self._make_path_item_linking([old_chunks[0].id])
        self.assertEqual(self._stale_link_count(), 0)

        self._patch_fetch(_NEW_MD)
        try:
            report = svc.refresh_snapshot_report(source.id)
        finally:
            web_source.fetch_and_extract = self._orig_fetch  # type: ignore[assignment]

        impact = report["impact"]
        self.assertEqual(report["source"].parse_status, "ok")
        self.assertTrue(impact.changed, "改动的小节必须被报出来")
        self.assertTrue(
            any("混合持久化" in heading for heading in impact.added),
            f"新增的小节必须被报出来：{impact.added}",
        )
        self.assertEqual(report["affected_items"], 1, "应告诉用户有多少训练项的出处受影响")
        self.assertEqual(
            self._stale_link_count(), 0, "刷新后训练项的出处回指不能悬空（审计 M3）"
        )


if __name__ == "__main__":
    unittest.main()
