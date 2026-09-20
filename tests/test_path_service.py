"""训练路径生成的测试：预算校验、兜底骨架、落库、版本、回指校验。"""
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
from src.services import edge_service, path_service, source_service as svc  # noqa: E402

_MD = """# 第三章 虚拟语气

本章介绍虚拟语气的整体用法。

## 3.2 用法

主句用 would + 动词原形。

## 3.3 易错点

if only 与 wish 的区别。
"""


def _skeleton(**overrides) -> path_service.PathSkeleton:
    item = path_service.PlannedItem(
        title="练习", item_type="memory", difficulty=2, knowledge_point="3.2 用法", minutes=10
    )
    stage = path_service.PlannedStage(title="阶段一", goal="打基础", items=[item])
    defaults = dict(
        training_id=1,
        horizon_weeks=2,
        weekly_frequency=5,
        daily_budget_minutes=30,
        stages=[stage],
    )
    defaults.update(overrides)
    return path_service.PathSkeleton(**defaults)  # type: ignore[arg-type]


class TestBudget(unittest.TestCase):
    def test_within_budget(self) -> None:
        report = path_service.check_budget(_skeleton())
        self.assertTrue(report.ok)
        self.assertEqual(report.budget_minutes, 300)
        self.assertEqual(report.planned_minutes, 10)

    def test_over_budget_rejected(self) -> None:
        many = [
            path_service.PlannedItem(
                title=f"练习{i}", item_type="practice", difficulty=3, knowledge_point="x", minutes=60
            )
            for i in range(10)
        ]
        report = path_service.check_budget(
            _skeleton(stages=[path_service.PlannedStage(title="阶段一", goal="g", items=many)])
        )
        self.assertFalse(report.ok)
        self.assertGreater(report.over_by, 0)
        self.assertIn("超出预算", report.message)

    def test_too_light_is_warning_not_block(self) -> None:
        report = path_service.check_budget(_skeleton())
        self.assertTrue(report.ok)
        self.assertTrue(report.too_light)
        self.assertIn("偏松", report.message)


class TestPathService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "path.db")
        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        client_module._call_api = lambda messages: (_ for _ in ()).throw(  # type: ignore[assignment]
            client_module.LLMError("forced failure for test")
        )
        init_db()
        self.training = queries.create_training(topic="英语虚拟语气", status="confirmed")
        source = svc.create_source(self.training.id, type="user_paste", title="讲义", content=_MD)
        svc.parse_source(source.id)

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api  # type: ignore[assignment]
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_skeleton_without_llm_uses_edge_states(self) -> None:
        probe = edge_service.generate_probe_items(self.training.id, topic="英语虚拟语气")
        for item in probe.items:
            item.answer = "不会"
            item.verdict = "fail"
            item.state = edge_service.judge_state("fail", item.difficulty)
        edge_service.save_probe(probe)

        skeleton, report = path_service.generate_skeleton(
            self.training.id, topic="英语虚拟语气"
        )
        self.assertTrue(skeleton.fallback_used)
        self.assertTrue(skeleton.stages)
        self.assertTrue(report.ok)
        # 未达的知识点应先出现铺垫项
        types = [item.item_type for stage in skeleton.stages for item in stage.items]
        self.assertIn("prerequisite", types)

    def test_skeleton_items_link_to_source_chunks(self) -> None:
        skeleton, _ = path_service.generate_skeleton(self.training.id, topic="英语虚拟语气")
        linked = [item.source_chunk_ids for stage in skeleton.stages for item in stage.items]
        self.assertTrue(any(ids for ids in linked), "至少应有训练项回指到来源切片")

    def test_save_and_load_path(self) -> None:
        skeleton, _ = path_service.generate_skeleton(self.training.id, topic="英语虚拟语气")
        saved = path_service.save_skeleton(skeleton)
        self.assertEqual(saved.version, 1)
        self.assertEqual(saved.status, "draft")

        loaded = path_service.load_path(self.training.id)
        self.assertIsNotNone(loaded)
        stages = path_service.load_stages(loaded.id)
        self.assertEqual(len(stages), len(skeleton.stages))
        items = path_service.load_items(stages[0].id)
        self.assertTrue(items)
        self.assertEqual(items[0].status, "pending")

    def test_confirm_path_and_supersede(self) -> None:
        skeleton, _ = path_service.generate_skeleton(self.training.id, topic="t")
        first = path_service.save_skeleton(skeleton)
        confirmed = path_service.confirm_path(self.training.id)
        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed.id, first.id)
        self.assertEqual(confirmed.status, "confirmed")
        self.assertTrue(confirmed.confirmed_at)

        # 再生成一版并确认 → 旧版本被取代
        skeleton2, _ = path_service.generate_skeleton(self.training.id, topic="t")
        path_service.save_skeleton(skeleton2)
        second = path_service.confirm_path(self.training.id)
        self.assertEqual(second.status, "confirmed")
        active = path_service.load_path(self.training.id)
        self.assertEqual(active.id, second.id)

    def test_adjust_budget_recalculates(self) -> None:
        skeleton, _ = path_service.generate_skeleton(self.training.id, topic="t")
        path_service.save_skeleton(skeleton)
        updated = path_service.adjust_budget(
            self.training.id, horizon_weeks=4, weekly_frequency=3, daily_budget_minutes=20
        )
        self.assertEqual(updated.budget_minutes, 4 * 3 * 20)
        self.assertEqual(updated.horizon_weeks, 4)

    def test_stale_chunk_links_are_cleaned(self) -> None:
        skeleton, _ = path_service.generate_skeleton(self.training.id, topic="t")
        path_service.save_skeleton(skeleton)
        path = path_service.load_path(self.training.id)
        stages = path_service.load_stages(path.id)
        item = path_service.load_items(stages[0].id)[0]

        # 手动写入一个不存在的切片 ID
        import json

        from src.db.sqlite import get_connection

        conn = get_connection()
        conn.execute(
            "UPDATE training_items SET source_chunk_ids = ? WHERE id = ?",
            (json.dumps([item.source_chunk_ids[0] if item.source_chunk_ids else 1, 999999]), item.id),
        )
        conn.commit()
        conn.close()

        dropped = path_service.validate_item_chunk_links(self.training.id)
        self.assertGreaterEqual(dropped, 1)
        refreshed = path_service.load_items(stages[0].id)[0]
        self.assertNotIn(999999, refreshed.source_chunk_ids or [])


if __name__ == "__main__":
    unittest.main()
