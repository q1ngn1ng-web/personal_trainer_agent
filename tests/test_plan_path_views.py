"""训练详情两个视图的端点级回归钉子（change training-path-sessions-view）。

钉住（接线缺口教训：函数级测试盖不住 payload 断链，必须在端点响应上断言）：
1. GET /api/trainings/{id}/sources：每条来源带 chunk_count / parse_error
   ——资料就绪可视化与探测门控的数据前提；
2. GET /api/trainings/{id}/plan-items：每条计划项带 last_score（该题×该轮
   最近一次判分得分，source∈llm/quiz/rule）/ mastery / difficulty_tier
   ——训练路径场次视图与聚合分数的数据前提。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402


class _EndpointBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "views.db")
        init_db()
        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        resp = self.client.post(
            "/api/auth/register",
            json={"email": "views@example.com", "password": "password8", "display_name": "V"},
        )
        assert resp.status_code == 200, resp.text
        start = self.client.post("/api/wizard/start", json={"topic": "我想系统学习 Redis 持久化机制"})
        assert start.status_code == 200, start.text
        self.training_id = start.json()["training_id"]

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _conn(self):
        return queries.get_connection()


class TestSourcesStatusFields(_EndpointBase):
    """资料列表必须暴露「到哪一步了」：切片数 + 失败原因。"""

    def _insert_source(self, *, parse_status: str, parse_error: str | None = None) -> int:
        conn = self._conn()
        try:
            cur = conn.execute(
                "INSERT INTO sources (training_id, type, title, enabled, parse_status, "
                "parse_error, imported_at) VALUES (?, 'user_upload', ?, 1, ?, ?, ?)",
                (
                    self.training_id,
                    f"src-{parse_status}",
                    parse_status,
                    parse_error,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def test_sources_payload_carries_chunk_count_and_parse_error(self) -> None:
        # 1) 正常链路：粘贴资料 → 解析切片 → chunk_count > 0
        add = self.client.post(
            f"/api/wizard/{self.training_id}/sources",
            json={"type": "text", "title": "持久化笔记", "content": "# RDB\n\n快照持久化。\n\n# AOF\n\n追加日志。"},
        )
        self.assertEqual(add.status_code, 200, add.text)

        # 2) 解析失败：有 parse_error、零切片
        failed_id = self._insert_source(parse_status="failed", parse_error="文件损坏")
        # 3) 解析 ok 但无切片（空文本文档的静默失败态）
        empty_id = self._insert_source(parse_status="ok")

        resp = self.client.get(f"/api/trainings/{self.training_id}/sources")
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = {s["id"]: s for s in resp.json()["sources"]}

        ok_row = next(s for s in rows.values() if s["title"] == "持久化笔记")
        self.assertEqual(ok_row["parse_status"], "ok")
        self.assertGreater(ok_row["chunk_count"], 0, "粘贴资料解析后应有切片")

        self.assertEqual(rows[failed_id]["chunk_count"], 0)
        self.assertEqual(rows[failed_id]["parse_error"], "文件损坏")

        self.assertEqual(rows[empty_id]["chunk_count"], 0)
        self.assertEqual(rows[empty_id]["parse_status"], "ok")


class TestPathItemsCarryItemKey(_EndpointBase):
    """path 端点的阶段条目必须带 item_key——「去练习」按它定位计划轮次，
    此前 payload 缺该字段导致跳转静默落空（第二处接线缺口）。"""

    def test_path_stage_items_include_item_key(self) -> None:
        conn = self._conn()
        now = datetime.now().isoformat()
        try:
            cur = conn.execute(
                "INSERT INTO training_paths (training_id, version, status, created_at) "
                "VALUES (?, 1, 'confirmed', ?)",
                (self.training_id, now),
            )
            path_id = int(cur.lastrowid)
            cur = conn.execute(
                "INSERT INTO path_stages (path_id, ordinal, title, estimated_minutes, status) "
                "VALUES (?, 1, '阶段一', 20, 'active')",
                (path_id,),
            )
            stage_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO training_items (stage_id, ordinal, title, item_key, item_type, "
                "difficulty_tier, knowledge_point, status, created_at) "
                "VALUES (?, 1, 'RDB 是什么', 'rdb-intro', 'memory', 2, 'RDB', 'pending', ?)",
                (stage_id, now),
            )
            conn.commit()
        finally:
            conn.close()

        resp = self.client.get(f"/api/trainings/{self.training_id}/path")
        self.assertEqual(resp.status_code, 200, resp.text)
        stages = resp.json()["stages"]
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["items"][0]["item_key"], "rdb-intro")


class TestPlanItemsMetrics(_EndpointBase):
    """计划项必须带 last_score / mastery / difficulty_tier（场次聚合分数的前提）。"""

    def _seed_plan(self) -> None:
        conn = self._conn()
        now = datetime.now().isoformat()
        try:
            rows = [
                # (item_key, round_index, due)
                ("item-a", 1, "2026-11-20"),
                ("item-b", 1, "2026-11-20"),
                ("item-a", 2, "2026-11-27"),
            ]
            for key, rnd, due in rows:
                conn.execute(
                    "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
                    "anchor_date, original_date, status, planned_minutes, created_at) "
                    "VALUES (?, ?, ?, 'train', ?, ?, ?, 'planned', 10, ?)",
                    (self.training_id, key, rnd, due, due, due, now),
                )
            # item-a 第 1 轮：两次判分（0.4 → 0.9），最近一次 0.9 胜出
            conn.execute(
                "INSERT INTO practice_attempts (training_id, item_key, round_index, result, score, "
                "source, created_at) VALUES (?, 'item-a', 1, 'fail', 0.4, 'llm', ?)",
                (self.training_id, now),
            )
            conn.execute(
                "INSERT INTO practice_attempts (training_id, item_key, round_index, result, score, "
                "source, created_at) VALUES (?, 'item-a', 1, 'pass', 0.9, 'llm', ?)",
                (self.training_id, now),
            )
            # 无得分的自评尝试不应参与 last_score
            conn.execute(
                "INSERT INTO practice_attempts (training_id, item_key, round_index, result, score, "
                "source, created_at) VALUES (?, 'item-a', 2, 'pass', NULL, 'self', ?)",
                (self.training_id, now),
            )
            # 掌握度：只有 item-a 有
            conn.execute(
                "INSERT INTO learner_knowledge (training_id, item_key, mastery, updated_at) "
                "VALUES (?, 'item-a', 0.8, ?)",
                (self.training_id, now),
            )
            conn.commit()
        finally:
            conn.close()

    def test_plan_items_carry_last_score_and_mastery(self) -> None:
        self._seed_plan()
        resp = self.client.get(f"/api/trainings/{self.training_id}/plan-items")
        self.assertEqual(resp.status_code, 200, resp.text)
        items = resp.json()["items"]
        by_key = {(i["item_key"], i["round_index"]): i for i in items}

        self.assertAlmostEqual(by_key[("item-a", 1)]["last_score"], 0.9, "取该题×该轮最近一次判分得分")
        self.assertIsNone(by_key[("item-b", 1)]["last_score"], "未作答题为 null")
        self.assertIsNone(by_key[("item-a", 2)]["last_score"], "只有无得分自评的轮次为 null")
        self.assertAlmostEqual(by_key[("item-a", 1)]["mastery"], 0.8)
        self.assertIsNone(by_key[("item-b", 1)]["mastery"], "无掌握度记录为 null")
        for i in items:
            self.assertIn("difficulty_tier", i, "difficulty_tier 字段必须在场（值可空）")


if __name__ == "__main__":
    unittest.main()
