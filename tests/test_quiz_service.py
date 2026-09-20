"""测验服务测试：取题排除冷却期原题、变式与降级、判分降级自评、未通过回退重练。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.plan import item_key_for  # noqa: E402
from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import attempt_service, path_service, plan_service, quiz_service  # noqa: E402

ANCHOR = date(2026, 9, 20)
ROUND1 = date(2026, 9, 21)
AFTER_COOLDOWN = date(2026, 10, 6)  # 第 1 轮练过（9/21）+ 14 天冷却期之后


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
                    ),
                    path_service.PlannedItem(
                        title="AOF 重写",
                        item_type="comprehension",
                        difficulty=3,
                        knowledge_point="AOF",
                        minutes=15,
                    ),
                ],
            )
        ],
    )


class TestQuizService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "quiz.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        client_module._call_api = lambda messages: (_ for _ in ()).throw(  # type: ignore[assignment]
            client_module.LLMError("forced failure for test")
        )

        self.training = queries.create_training(topic="Redis 持久化", status="active")
        queries.update_training(
            self.training.id, created_at=f"{ANCHOR.isoformat()}T10:00:00+08:00"
        )
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)
        self.item_keys = [
            item_key_for(self.training.id, "RDB", "RDB 是什么"),
            item_key_for(self.training.id, "AOF", "AOF 重写"),
        ]

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api  # type: ignore[assignment]
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _practice_round_one(self) -> None:
        """把第 1 轮全部练过（写题库 + 冷却期），并补一条作答记录。"""
        tasks = plan_service.today_tasks(training_id=self.training.id, today=ROUND1)
        plan_service.complete_tasks(
            [task.plan_id for task in tasks], today=ROUND1
        )
        for task in tasks:
            attempt_service.record_attempt(self.training.id, task.item_key, "pass")

    def _start(self) -> int:
        assessment = quiz_service.start_assessment(
            self.training.id, trigger="manual", today=AFTER_COOLDOWN
        )
        return int(assessment.id)

    def test_pool_excludes_items_inside_cooldown(self) -> None:
        self._practice_round_one()
        self.assertEqual(quiz_service.question_pool(self.training.id, today=ROUND1), [])
        self.assertEqual(
            len(quiz_service.question_pool(self.training.id, today=AFTER_COOLDOWN)), 2
        )

    def test_start_assessment_requires_available_questions(self) -> None:
        self._practice_round_one()
        with self.assertRaises(ValueError):
            quiz_service.start_assessment(self.training.id, today=ROUND1)

    def test_start_assessment_falls_back_to_originals_without_llm(self) -> None:
        self._practice_round_one()
        assessment_id = self._start()
        items = quiz_service.load_items(assessment_id)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.is_variant == 0 for item in items), "LLM 不可用时应标记为非变式")
        self.assertTrue(all(item.question for item in items))
        # 覆盖两个不同知识点
        self.assertEqual({item.knowledge_point for item in items}, {"RDB", "AOF"})

    def test_start_assessment_uses_variant_when_llm_works(self) -> None:
        self._practice_round_one()
        first, second = self.item_keys

        def fake_call(messages):  # noqa: ANN001
            payload = {
                "questions": [
                    {"item_key": first, "question": "变式：RDB 与 AOF 同时开启会发生什么？", "reference_answer": "混合持久化"},
                    {"item_key": second, "question": "变式：AOF 重写期间的新写入去哪了？", "reference_answer": "重写缓冲区"},
                ]
            }
            return json.dumps(payload, ensure_ascii=False), 10, 20

        self._client._call_api = fake_call  # type: ignore[assignment]
        assessment_id = self._start()
        items = quiz_service.load_items(assessment_id)
        self.assertTrue(all(item.is_variant == 1 for item in items))
        self.assertTrue(all("变式" in item.question for item in items))

        # 判分：LLM 可用时按返回结果写 verdict
        def fake_grade(messages):  # noqa: ANN001
            payload = {
                "results": [
                    {"item_key": first, "verdict": "pass", "reason": "答到关键点"},
                    {"item_key": second, "verdict": "fail", "reason": "漏了写回缓冲"},
                ]
            }
            return json.dumps(payload, ensure_ascii=False), 10, 20

        self._client._call_api = fake_grade  # type: ignore[assignment]
        quiz_service.save_answers(assessment_id, {item.id: "我的作答" for item in items})
        self.assertTrue(quiz_service.grade_with_llm(assessment_id))
        results = quiz_service.finish_assessment(
            assessment_id, today=AFTER_COOLDOWN, graded_by="llm"
        )
        self.assertEqual(results.question_count, 2)
        self.assertAlmostEqual(results.score, 0.5)
        self.assertFalse(results.passed, "0.5 < 0.8 不应通过")
        self.assertEqual(results.extra_rounds, 1, "未通过的题应追加一轮补练")

    def test_manual_grading_fallback_and_pass(self) -> None:
        self._practice_round_one()
        assessment_id = self._start()
        items = quiz_service.load_items(assessment_id)
        quiz_service.save_answers(assessment_id, {item.id: "作答" for item in items})
        self.assertFalse(quiz_service.grade_with_llm(assessment_id), "LLM 不可用时判分应失败")
        quiz_service.save_manual_verdicts(
            assessment_id, {item.id: "pass" for item in items}
        )
        results = quiz_service.finish_assessment(
            assessment_id, today=AFTER_COOLDOWN, graded_by="self"
        )
        self.assertTrue(results.passed)
        self.assertEqual(results.extra_rounds, 0)
        self.assertEqual(results.failed_items, [])

    def test_failed_quiz_marks_plan_item_done_and_records_attempts(self) -> None:
        self._practice_round_one()
        plan_item = quiz_service.pending_quiz_plan(self.training.id, today=AFTER_COOLDOWN)
        self.assertIsNotNone(plan_item)
        assessment = quiz_service.start_assessment(
            self.training.id,
            trigger="scheduled",
            plan_id=int(plan_item["id"]),
            today=AFTER_COOLDOWN,
        )
        items = quiz_service.load_items(assessment.id)
        quiz_service.save_manual_verdicts(assessment.id, {item.id: "fail" for item in items})
        results = quiz_service.finish_assessment(assessment.id, today=AFTER_COOLDOWN, graded_by="self")

        self.assertFalse(results.passed)
        self.assertEqual(results.extra_rounds, 2)

        conn = queries.get_connection()
        try:
            plan_row = conn.execute(
                "SELECT status FROM plan_items WHERE id = ?", (int(plan_item["id"]),)
            ).fetchone()
            extra_rows = conn.execute(
                "SELECT item_key, round_index, due_date, reason FROM plan_items "
                "WHERE training_id = ? AND reason = 'quiz_failed' ORDER BY item_key",
                (self.training.id,),
            ).fetchall()
            quiz_attempts = conn.execute(
                "SELECT COUNT(*) AS n FROM practice_attempts WHERE training_id = ? AND source = 'quiz'",
                (self.training.id,),
            ).fetchone()["n"]
        finally:
            conn.close()

        self.assertEqual(plan_row["status"], "practiced", "测验任务本身应被标记完成")
        self.assertEqual(len(extra_rows), 2)
        self.assertTrue(all(int(row["round_index"]) == 6 for row in extra_rows), "补练轮次接在第 5 轮之后")
        self.assertTrue(all(row["due_date"] == "2026-10-07" for row in extra_rows))
        self.assertEqual(int(quiz_attempts), 2, "测验结果要进入作答记录（客观通道）")


if __name__ == "__main__":
    unittest.main()
