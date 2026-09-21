"""训练作答测试：系统出题（含降级）、提交后系统判分、判分不可用时不伪造对错。"""
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

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import answer_service, path_service, plan_service  # noqa: E402
from src.services import source_service as svc  # noqa: E402

ANCHOR = date(2026, 9, 20)
ROUND1 = date(2026, 9, 21)


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


class TestAnswerService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "answer.db")
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
        self.source = svc.create_source(
            self.training.id,
            type="user_paste",
            title="讲义",
            content="# RDB\n\nRDB 通过 fork 子进程把内存快照写入磁盘，主进程继续服务。\n",
        )
        svc.parse_source(self.source.id)
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)
        self.task = plan_service.today_tasks(training_id=self.training.id, today=ROUND1)[0]
        # 把资料片段挂到训练项上（出题依据）
        chunks = svc.list_chunks(self.source.id)
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE training_items SET source_chunk_ids = ? WHERE item_key = ?",
                (json.dumps([chunks[0].id]), self.task.item_key),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api  # type: ignore[assignment]
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _question_row(self, plan_id: int) -> dict:
        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT question, reference_answer, answer_text, verdict, graded_by, status "
                "FROM plan_items WHERE id = ?",
                (plan_id,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row)

    def _attempt_count(self) -> int:
        conn = queries.get_connection()
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM practice_attempts WHERE training_id = ?",
                    (self.training.id,),
                ).fetchone()["n"]
            )
        finally:
            conn.close()

    def test_ensure_question_generates_and_is_idempotent(self) -> None:
        first = answer_service.ensure_question(self.task.plan_id)
        self.assertTrue(first["question"], "系统必须给出一道具体题目")
        self.assertEqual(first["source"], "fallback", "模型不可用时应走兜底")
        row = self._question_row(self.task.plan_id)
        self.assertEqual(row["question"], first["question"])

        second = answer_service.ensure_question(self.task.plan_id)
        self.assertEqual(second["source"], "stored", "已有题目时不再重复生成")
        self.assertEqual(second["question"], first["question"])

    def test_ensure_question_uses_model_when_available(self) -> None:
        def fake_call(messages):  # noqa: ANN001
            payload = {
                "question": "RDB 为什么用子进程写盘？",
                "reference_answer": "为了不阻塞主进程，fork 后由子进程写快照。",
                "difficulty": 3,
            }
            return json.dumps(payload, ensure_ascii=False), 10, 20

        self._client._call_api = fake_call  # type: ignore[assignment]
        result = answer_service.ensure_question(self.task.plan_id)
        self.assertEqual(result["source"], "llm")
        self.assertIn("子进程", result["question"])

    def test_submit_answer_requires_content(self) -> None:
        with self.assertRaises(ValueError):
            answer_service.submit_answer(self.task.plan_id, "   ")

    def test_submit_answer_without_grading_does_not_fake_result(self) -> None:
        """判分不可用时：答案照存、标记练过，但**不写客观记录**（宁缺勿假）。"""
        outcome = answer_service.submit_answer(self.task.plan_id, "RDB 用子进程写快照")
        self.assertFalse(outcome["graded"])
        self.assertIsNone(outcome["verdict"])
        self.assertTrue(outcome["reference_answer"])

        row = self._question_row(self.task.plan_id)
        self.assertEqual(row["answer_text"], "RDB 用子进程写快照")
        self.assertEqual(row["status"], "practiced", "练过仍然成立")
        self.assertEqual(row["graded_by"], "unavailable")
        self.assertEqual(self._attempt_count(), 0, "没判分就不能写进客观表现")

    def test_submit_answer_grades_and_masters_after_two_passes(self) -> None:
        def fake_grade(messages):  # noqa: ANN001
            payload = {
                "results": [
                    {"item_key": self.task.item_key, "verdict": "pass", "reason": "答到 fork 子进程这一关键点"}
                ]
            }
            return json.dumps(payload, ensure_ascii=False), 10, 20

        self._client._call_api = fake_grade  # type: ignore[assignment]
        first = answer_service.submit_answer(self.task.plan_id, "子进程写快照")
        self.assertTrue(first["graded"])
        self.assertEqual(first["verdict"], "pass")
        self.assertFalse(first["mastered"], "只有一次通过还不算达标")
        self.assertEqual(self._attempt_count(), 1)
        conn = queries.get_connection()
        try:
            source = conn.execute(
                "SELECT source FROM practice_attempts WHERE training_id = ?",
                (self.training.id,),
            ).fetchone()["source"]
        finally:
            conn.close()
        self.assertEqual(source, "llm", "训练作答的判分来源是模型")

        # 再答对一次（同一道题的第 1 轮重新作答）→ 连续 2 次通过 → 达标
        second = answer_service.submit_answer(self.task.plan_id, "fork 出子进程写 RDB")
        self.assertTrue(second["mastered"], "连续 2 次通过应判达标")

        conn = queries.get_connection()
        try:
            item = conn.execute(
                "SELECT status, mastered_at FROM training_items WHERE item_key = ?",
                (self.task.item_key,),
            ).fetchone()
            banked = conn.execute(
                "SELECT COUNT(*) AS n FROM question_bank WHERE training_id = ?",
                (self.training.id,),
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(item["status"], "passed")
        self.assertTrue(item["mastered_at"])
        self.assertEqual(int(banked), 1, "练过即入题库")

    def test_mark_practiced_only_skips_grading(self) -> None:
        answer_service.mark_practiced_only(self.task.plan_id)
        row = self._question_row(self.task.plan_id)
        self.assertEqual(row["status"], "practiced")
        self.assertEqual(self._attempt_count(), 0)


if __name__ == "__main__":
    unittest.main()
