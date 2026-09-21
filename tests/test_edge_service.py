"""理解边缘定位的测试：三态规则、知识点推导、出题降级、结果落库。"""
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
from src.services import edge_service, source_service as svc  # noqa: E402

_MD = """# 第三章 虚拟语气

本章介绍虚拟语气的整体用法。

## 3.2 用法

主句用 would + 动词原形。

## 3.3 易错点

if only 与 wish 的区别。
"""


class TestJudgeState(unittest.TestCase):
    def test_pass_high_difficulty_is_mastered(self) -> None:
        self.assertEqual(edge_service.judge_state("pass", 3), "mastered")
        self.assertEqual(edge_service.judge_state("pass", 4), "mastered")

    def test_pass_low_difficulty_is_edge(self) -> None:
        self.assertEqual(edge_service.judge_state("pass", 1), "edge")
        self.assertEqual(edge_service.judge_state("pass", 2), "edge")

    def test_fail_low_difficulty_is_unreached(self) -> None:
        self.assertEqual(edge_service.judge_state("fail", 1), "unreached")
        self.assertEqual(edge_service.judge_state("fail", 2), "unreached")

    def test_fail_high_difficulty_is_edge(self) -> None:
        self.assertEqual(edge_service.judge_state("fail", 3), "edge")
        self.assertEqual(edge_service.judge_state("fail", 4), "edge")


class TestEdgeService(unittest.TestCase):

    def test_knowledge_point_truncation_is_disclosed(self) -> None:
        """知识点超过上限时必须如实告知（审计 M4）：总数、本次探测数、是否截断。"""
        before = edge_service.count_knowledge_points(self.training.id)
        sections = "\n\n".join(
            f"## 知识点 {index}\n\n第 {index} 个知识点的内容。" for index in range(1, 13)
        )
        source = svc.create_source(
            self.training.id, type="user_paste", title="大资料", content=f"# 总览\n\n{sections}"
        )
        svc.parse_source(source.id)

        total = edge_service.count_knowledge_points(self.training.id)
        selected = edge_service.build_knowledge_points(self.training.id)
        self.assertEqual(total - before, 12, "新增资料带来 12 个知识点")
        self.assertEqual(len(selected), edge_service.MAX_KNOWLEDGE_POINTS)

        probe = edge_service.generate_probe_items(self.training.id, topic="虚拟语气")
        self.assertEqual(probe.total_points, total)
        self.assertEqual(probe.selected_points, len(selected))
        self.assertTrue(probe.truncated, "截断必须可被页面识别")
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "edge.db")
        self._old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        # 注入必然失败的模型调用：让测试快且确定，同时覆盖降级路径
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
        if self._old_key is not None:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key
        self._tmp.cleanup()

    def test_knowledge_points_from_chunks(self) -> None:
        points = edge_service.build_knowledge_points(self.training.id)
        names = [point.name for point in points]
        self.assertEqual(len(points), 3)  # 第三章 / 3.2 用法 / 3.3 易错点
        self.assertIn("3.2 用法", names)
        self.assertTrue(all(point.sample_text for point in points))

    def test_knowledge_points_capped(self) -> None:
        points = edge_service.build_knowledge_points(self.training.id, limit=2)
        self.assertEqual(len(points), 2)

    def test_probe_without_llm_falls_back_to_naive_questions(self) -> None:
        probe = edge_service.generate_probe_items(self.training.id, topic="英语虚拟语气")
        self.assertTrue(probe.fallback_used)
        self.assertEqual(len(probe.items), 3)
        self.assertTrue(all(item.question for item in probe.items))
        self.assertTrue(all(item.difficulty == 2 for item in probe.items))

    def test_grade_without_llm_treats_all_as_fail(self) -> None:
        probe = edge_service.generate_probe_items(self.training.id, topic="英语虚拟语气")
        for item in probe.items:
            item.answer = "不会"
        graded = edge_service.grade_probe(self.training.id, probe.items, topic="英语虚拟语气")
        self.assertTrue(graded.is_graded)
        self.assertEqual(graded.state_counts()["unreached"], len(probe.items))

    def test_save_and_load_roundtrip(self) -> None:
        probe = edge_service.generate_probe_items(self.training.id, topic="英语虚拟语气")
        for index, item in enumerate(probe.items):
            item.answer = "不知道"
            item.verdict = "fail"
            item.state = edge_service.judge_state("fail", item.difficulty)
        edge_service.save_probe(probe)

        loaded = edge_service.load_probe(self.training.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.items), len(probe.items))
        self.assertEqual(loaded.items[0].verdict, "fail")
        self.assertEqual(loaded.items[0].state, "unreached")

    def test_save_replaces_previous_probe(self) -> None:
        first = edge_service.generate_probe_items(self.training.id, topic="t")
        edge_service.save_probe(first)
        second = edge_service.generate_probe_items(self.training.id, topic="t")
        edge_service.save_probe(second)
        loaded = edge_service.load_probe(self.training.id)
        self.assertEqual(len(loaded.items), len(second.items))

    def test_no_sources_raises(self) -> None:
        empty = queries.create_training(topic="空训练", status="confirmed")
        with self.assertRaises(ValueError):
            edge_service.generate_probe_items(empty.id, topic="空训练")


if __name__ == "__main__":
    unittest.main()
