"""日常训练「要点出题 → 要点判分」接线测试。

回归背景（审计 P0-3 的真实缺口）：测验链路已按要点判分，但日常训练链路
``ensure_question`` 丢弃模型输出的要点清单、``_grade_answer`` 只读二元 verdict。
本文件钉住三件事：

1. 出题时要点清单随题固化到 ``plan_items.points``（判分只引用不再生成）；
2. 有要点时判分走「模型逐条判定 → 规则层算分达标」，**缺必答要点必挂**，
   且 ``practice_attempts`` 落 ``score`` / ``point_results``（客观表现可解释）；
3. 无要点（模型没吐 / 旧数据）时退回整体二元判定，行为与接线前一致。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import answer_service, path_service, plan_service  # noqa: E402

ANCHOR = date(2026, 9, 20)

TRAIN_PAYLOAD = {
    "question": "RDB 持久化的默认文件名是什么？由谁写入？",
    "reference_answer": "dump.rdb；fork 出的子进程写入",
    "difficulty": 2,
    "question_type": "qa",
    "points": [
        {"point_id": "p1", "text": "默认文件名 dump.rdb", "weight": 2, "is_required": True},
        {"point_id": "p2", "text": "由 fork 出的子进程写入快照", "weight": 1, "is_required": False},
    ],
}

GRADE_ALL_HIT = {
    "results": [
        {
            "item_key": "PLACEHOLDER",
            "verdict": "pass",
            "point_verdicts": [
                {"point_id": "p1", "verdict": "hit", "evidence": "fork 创建子进程"},
                {"point_id": "p2", "verdict": "hit", "evidence": "返回进程 id"},
            ],
            "reason": "要点齐全",
        }
    ]
}

GRADE_REQUIRED_MISSING = {
    "results": [
        {
            "item_key": "PLACEHOLDER",
            "verdict": "pass",  # 模型整体说 pass——规则层必须否决（必答要点缺失）
            "point_verdicts": [
                {"point_id": "p1", "verdict": "missing", "evidence": ""},
                {"point_id": "p2", "verdict": "hit", "evidence": "返回进程 id"},
            ],
            "reason": "提到了子进程，但没说文件名",
        }
    ]
}


def _skeleton(training_id: int) -> path_service.PathSkeleton:
    return path_service.PathSkeleton(
        training_id=training_id,
        horizon_weeks=2,
        weekly_frequency=3,
        daily_budget_minutes=30,
        stages=[
            path_service.PlannedStage(
                title="阶段一",
                goal="打底",
                items=[
                    path_service.PlannedItem(
                        title="RDB 是什么",
                        item_type="memory",
                        difficulty=2,
                        knowledge_point="RDB",
                        minutes=10,
                    )
                ],
            )
        ],
    )


class TestTrainPointsWiring(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "points.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._grade_payload: dict | None = None
        self._last_grade_prompt: str | None = None

        training = queries.create_training(topic="Redis 持久化", status="active")
        anchor = ANCHOR - timedelta(days=1)
        queries.update_training(training.id, created_at=f"{anchor.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training
        self.task = plan_service.today_tasks(training_id=training.id)[0]

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _install_stub(self, *, train_payload: dict, grade_payload: dict | None = None) -> None:
        """按 prompt 标题分流：训练出题助手 → 出题载荷；测验评分员 → 判分载荷。"""

        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(train_payload, ensure_ascii=False), 10, 20
            if "测验评分员" in content:
                self._last_grade_prompt = content
                payload = dict(grade_payload or {})
                results = payload.get("results") or []
                if results:
                    payload["results"] = [dict(results[0], item_key=self.task.item_key)]
                return json.dumps(payload, ensure_ascii=False), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        self._client._call_api = fake_call_api

    def test_ensure_question_persists_normalized_points(self) -> None:
        self._install_stub(train_payload=TRAIN_PAYLOAD)

        result = answer_service.ensure_question(self.task.plan_id)

        self.assertEqual(result["source"], "llm")
        self.assertEqual(len(result["points"]), 2)

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT points FROM plan_items WHERE id = ?", (self.task.plan_id,)
            ).fetchone()
        finally:
            conn.close()
        points = json.loads(row["points"])
        self.assertEqual(len(points), 2)
        self.assertTrue(points[0]["is_required"])
        self.assertEqual(points[0]["point_id"], "p1")

    def test_normalize_points_tolerates_dirty_input(self) -> None:
        """纯单元：脏要点（空正文 / 非法权重 / 缺 id）逐条修正或丢弃，不连坐。"""
        normalized = answer_service._normalize_points(
            [
                {"point_id": "", "text": "要点甲", "weight": 0, "is_required": True},
                {"point_id": "p1", "text": "  ", "weight": 2, "is_required": False},
                {"point_id": "p1", "text": "要点乙", "weight": "x", "is_required": False},
                "not-a-dict",
            ]
        )
        self.assertIsNotNone(normalized)
        self.assertEqual(len(normalized), 2)
        ids = [p["point_id"] for p in normalized]
        self.assertEqual(len(set(ids)), 2, "point_id 必须去重")
        self.assertEqual(normalized[0]["weight"], 1.0, "非法权重回退为 1.0")
        self.assertTrue(normalized[0]["is_required"])

        self.assertIsNone(answer_service._normalize_points([]))
        self.assertIsNone(answer_service._normalize_points("junk"))
        self.assertEqual(answer_service._parse_points_json("{bad json"), [])
        self.assertEqual(answer_service._parse_points_json(None), [])

    def test_required_point_missing_fails_despite_llm_pass(self) -> None:
        """必答要点缺失时，即使模型整体 verdict=pass，规则层也必须判 fail。"""
        self._install_stub(
            train_payload=TRAIN_PAYLOAD, grade_payload=GRADE_REQUIRED_MISSING
        )

        outcome = answer_service.submit_answer(self.task.plan_id, "fork 出子进程写快照")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "fail", "缺必答要点（dump.rdb）必须判 fail")
        self.assertIn("必答", outcome["reason"])
        self.assertIsNotNone(outcome["score"], "要点判分必须给出可解释分数")

        conn = queries.get_connection()
        try:
            attempt = conn.execute(
                "SELECT result, score, point_results FROM practice_attempts "
                "WHERE training_id = ? ORDER BY id DESC LIMIT 1",
                (self.training.id,),
            ).fetchone()
            item = conn.execute(
                "SELECT graded_by, verdict FROM plan_items WHERE id = ?",
                (self.task.plan_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(attempt["result"], "fail")
        self.assertIsNotNone(attempt["score"])
        detail = json.loads(attempt["point_results"])["detail"]
        self.assertEqual(detail[0]["verdict"], "missing", "p1 的判定必须落进 point_results")

    def test_all_points_hit_passes_with_score(self) -> None:
        self._install_stub(train_payload=TRAIN_PAYLOAD, grade_payload=GRADE_ALL_HIT)

        outcome = answer_service.submit_answer(self.task.plan_id, "默认 dump.rdb，fork 子进程写快照")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "pass")
        self.assertGreaterEqual(outcome["score"], 0.8)

    def test_without_points_falls_back_to_binary_verdict(self) -> None:
        payload = {k: v for k, v in TRAIN_PAYLOAD.items() if k != "points"}
        binary = {
            "results": [
                {"item_key": self.task.item_key, "verdict": "pass", "reason": "答到关键点"}
            ]
        }
        self._install_stub(train_payload=payload, grade_payload=binary)

        outcome = answer_service.submit_answer(self.task.plan_id, "dump.rdb")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "pass")
        self.assertIsNone(outcome["score"], "二元判定不伪造分数")
        self.assertIsNone(outcome["point_results"])

    def test_plan_items_has_points_column(self) -> None:
        conn = queries.get_connection()
        try:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(plan_items)").fetchall()
            }
        finally:
            conn.close()
        self.assertIn("points", cols, "新库建表必须带 points 列")


class TestGradePromptMemoryContext(unittest.TestCase):
    """任务 4.3 判分侧：判分 prompt 注入学习者记忆块（默认开、可关、无数据不注入）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "points.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._last_grade_prompt: str | None = None

        training = queries.create_training(topic="Redis 持久化", status="active")
        anchor = ANCHOR - timedelta(days=1)
        queries.update_training(training.id, created_at=f"{anchor.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training
        self.task = plan_service.today_tasks(training_id=training.id)[0]

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _install_stub(self, *, grade_payload: dict) -> None:
        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(TRAIN_PAYLOAD, ensure_ascii=False), 10, 20
            if "测验评分员" in content:
                self._last_grade_prompt = content
                payload = dict(grade_payload)
                payload["results"] = [
                    dict(payload["results"][0], item_key=self.task.item_key)
                ]
                return json.dumps(payload, ensure_ascii=False), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        self._client._call_api = fake_call_api

    def _seed_history_attempt(self) -> None:
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO practice_attempts "
                "(training_id, item_key, result, score, mistake_reasons, created_at) "
                "VALUES (?, ?, 'fail', 0.5, ?, '2026-09-21T10:00:00')",
                (
                    self.training.id,
                    self.task.item_key,
                    json.dumps({"p1": "memory_gap"}),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_grade_prompt_injects_memory_context(self) -> None:
        self._seed_history_attempt()
        self._install_stub(grade_payload=GRADE_ALL_HIT)

        answer_service.submit_answer(self.task.plan_id, "默认 dump.rdb，fork 子进程写快照")

        self.assertIsNotNone(self._last_grade_prompt)
        self.assertIn("【学习者背景】", self._last_grade_prompt)
        self.assertIn("记忆缺失", self._last_grade_prompt)

    def test_grade_prompt_skips_memory_without_history(self) -> None:
        self._install_stub(grade_payload=GRADE_ALL_HIT)

        answer_service.submit_answer(self.task.plan_id, "默认 dump.rdb，fork 子进程写快照")

        self.assertIsNotNone(self._last_grade_prompt)
        self.assertNotIn("【学习者背景】", self._last_grade_prompt)

    def test_grade_prompt_respects_disabled_switch(self) -> None:
        from src.services import memory_service

        self._seed_history_attempt()
        memory_service.set_memory_context_enabled(False)
        self._install_stub(grade_payload=GRADE_ALL_HIT)

        answer_service.submit_answer(self.task.plan_id, "默认 dump.rdb，fork 子进程写快照")

        self.assertIsNotNone(self._last_grade_prompt)
        self.assertNotIn("【学习者背景】", self._last_grade_prompt)


class TestGradingCacheIntegration(unittest.TestCase):
    """判分结果缓存（change grading-consistency）：同卷同答第二次判分零 LLM 调用、结果逐字一致。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "gc.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._quiz_calls = 0

        training = queries.create_training(topic="Redis 持久化", status="active")
        self.training = training
        self._context = {
            "training_id": training.id,
            "item_key": "kp00-qa",
            "question": TRAIN_PAYLOAD["question"],
            "reference_answer": TRAIN_PAYLOAD["reference_answer"],
            "points": json.dumps(TRAIN_PAYLOAD["points"], ensure_ascii=False),
        }

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _install_quiz_stub(self) -> None:
        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "测验评分员" in content:
                self._quiz_calls += 1
                payload = dict(GRADE_ALL_HIT)
                payload["results"] = [
                    dict(payload["results"][0], item_key=self._context["item_key"])
                ]
                return json.dumps(payload, ensure_ascii=False), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        self._client._call_api = fake_call_api

    def test_second_identical_grading_hits_cache(self) -> None:
        self._install_quiz_stub()
        answer = "默认 dump.rdb，fork 出的子进程写快照"

        first = answer_service._grade_answer(self._context, answer)
        calls_after_first = self._quiz_calls
        self.assertGreaterEqual(calls_after_first, 1)

        second = answer_service._grade_answer(self._context, answer)

        self.assertEqual(self._quiz_calls, calls_after_first, "同卷同答第二次不得再调模型")
        self.assertEqual(first, second, "缓存命中必须给出逐字一致的判分结果")

    def test_changed_answer_bypasses_cache(self) -> None:
        self._install_quiz_stub()
        answer_service._grade_answer(self._context, "默认 dump.rdb，fork 出的子进程写快照")
        calls_after_first = self._quiz_calls

        answer_service._grade_answer(self._context, "完全不同的另一种作答")

        self.assertEqual(self._quiz_calls, calls_after_first + 1, "作答变了必须重新调模型")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
