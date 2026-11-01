"""主观判分结果缓存测试（change grading-consistency）。

钉住三件事：
1. 缓存键对任一语义输入（模型/prompt 版本/题目/参考答案/要点/作答）敏感；
2. store→lookup 往返一致，坏数据不致命；
3. 判分用途温度为 0（同输入消除采样抖动），其他用途不受影响。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db.sqlite import get_connection, init_db  # noqa: E402
from src.llm.client import DEFAULT_TEMPERATURE, temperature_for  # noqa: E402
from src.services import grading_cache as gc  # noqa: E402

OUTPUT = {
    "results": [
        {
            "item_key": "k1",
            "verdict": "pass",
            "point_verdicts": [{"point_id": "p1", "verdict": "hit"}],
            "reason": "要点齐全",
        }
    ]
}


class TestTemperatureByPurpose(unittest.TestCase):
    def test_quiz_grade_is_zero(self) -> None:
        self.assertEqual(temperature_for("quiz_grade"), 0.0)

    def test_other_purposes_keep_default(self) -> None:
        self.assertEqual(temperature_for("goal_clarification"), DEFAULT_TEMPERATURE)
        self.assertEqual(temperature_for("unknown_purpose"), DEFAULT_TEMPERATURE)


class TestGradingCacheKey(unittest.TestCase):
    def test_same_inputs_same_key(self) -> None:
        self.assertEqual(
            gc.cache_key("m", "v1.2.0", "题干", "参考", "[]", "作答"),
            gc.cache_key("m", "v1.2.0", "题干", "参考", "[]", "作答"),
        )

    def test_any_semantic_change_changes_key(self) -> None:
        base = dict(
            model="m", prompt_version="v1.2.0", question="题干",
            reference_answer="参考", points_json="[]", answer="作答",
        )
        key = gc.cache_key(**base)
        for field, value in (
            ("model", "m2"),
            ("prompt_version", "v1.3.0"),
            ("question", "题干2"),
            ("reference_answer", "参考2"),
            ("points_json", '[{"point_id": "p1"}]'),
            ("answer", "作答2"),
        ):
            mutated = dict(base)
            mutated[field] = value
            self.assertNotEqual(key, gc.cache_key(**mutated), f"{field} 变化必须换键")


class TestGradingCacheStoreLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "gc.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_store_then_lookup_roundtrip(self) -> None:
        key = gc.cache_key("m", "v1", "q", "r", "[]", "a")
        gc.store(key, "v1", "m", OUTPUT, tokens_in=10, tokens_out=20, latency_ms=30)
        self.assertEqual(gc.lookup(key), OUTPUT)

    def test_lookup_miss_on_fresh_db(self) -> None:
        self.assertIsNone(gc.lookup(gc.cache_key("m", "v1", "q", "r", "[]", "a")))

    def test_corrupt_entry_tolerated(self) -> None:
        key = gc.cache_key("m", "v1", "q", "r", "[]", "a")
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO grading_cache (cache_key, prompt_name, prompt_version, model, "
                "output_json, created_at) VALUES (?, 'quiz_grade', 'v1', 'm', '{bad', 'now')",
                (key,),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertIsNone(gc.lookup(key), "坏缓存必须当未命中，不得抛异常阻断判分")

    def test_same_key_store_twice_keeps_first(self) -> None:
        key = gc.cache_key("m", "v1", "q", "r", "[]", "a")
        gc.store(key, "v1", "m", OUTPUT)
        gc.store(key, "v1", "m", {"results": []})
        self.assertEqual(gc.lookup(key), OUTPUT, "首次结果为准，禁止被后写覆盖")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
