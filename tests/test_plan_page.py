"""训练计划页面的 UI 回归测试（Streamlit AppTest）：任务卡来自计划表、勾选=练过、首页有今日训练区块。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DAILY_WRAPPER = """import sys
sys.path.insert(0, {root!r})
from src.ui.page_daily import render
render()
"""

_HOME_WRAPPER = """import sys
sys.path.insert(0, {root!r})
from src.ui.page_home import render
render()
"""


def _skeleton(training_id: int):
    from src.services import path_service

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


class TestPlanPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._old_db_path = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(cls._tmpdir.name) / "plan_page.db")
        cls._daily_wrapper = str(Path(cls._tmpdir.name) / "plan_daily_app.py")
        Path(cls._daily_wrapper).write_text(
            _DAILY_WRAPPER.format(root=str(ROOT)), encoding="utf-8"
        )
        cls._home_wrapper = str(Path(cls._tmpdir.name) / "plan_home_app.py")
        Path(cls._home_wrapper).write_text(
            _HOME_WRAPPER.format(root=str(ROOT)), encoding="utf-8"
        )
        from src.db.sqlite import init_db

        init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = cls._old_db_path
        cls._tmpdir.cleanup()

    def _training_with_plan(self) -> int:
        from src.core.plan import local_today
        from src.db import queries
        from src.services import path_service

        training = queries.create_training(topic="Redis 持久化", status="active")
        anchor = local_today() - timedelta(days=1)
        queries.update_training(
            training.id, created_at=f"{anchor.isoformat()}T10:00:00+08:00"
        )
        path_service.save_skeleton(_skeleton(training.id))
        return int(training.id)

    def test_daily_card_lists_plan_round_and_practices(self) -> None:
        from streamlit.testing.v1 import AppTest

        from src.db import queries
        from src.services import plan_service

        training_id = self._training_with_plan()
        plan_service.generate_plan(training_id)

        app = AppTest.from_file(self._daily_wrapper, default_timeout=60)
        app.query_params["page"] = "daily"
        app.query_params["training_id"] = str(training_id)
        app.run()

        self.assertFalse(app.exception)
        labels = [expander.label for expander in app.expander]
        self.assertTrue(any("第 1/5 轮" in label for label in labels), labels)
        self.assertEqual(len(app.checkbox), 2)

        app.checkbox[0].check().run()
        self.assertFalse(app.exception)

        conn = queries.get_connection()
        try:
            plan_row = conn.execute(
                "SELECT status FROM plan_items WHERE training_id = ? AND status = 'practiced'",
                (training_id,),
            ).fetchone()
            item_rows = conn.execute(
                "SELECT status FROM training_items WHERE stage_id IN "
                "(SELECT id FROM path_stages WHERE path_id IN "
                "(SELECT id FROM training_paths WHERE training_id = ?))",
                (training_id,),
            ).fetchall()
        finally:
            conn.close()
        self.assertIsNotNone(plan_row, "勾选应把计划项写成 practiced")
        self.assertTrue(any(row["status"] == "practiced" for row in item_rows))
        self.assertFalse(
            any(row["status"] == "passed" for row in item_rows), "勾选不得产生达标"
        )

    def test_home_shows_today_plan_block(self) -> None:
        from streamlit.testing.v1 import AppTest

        from src.services import plan_service

        training_id = self._training_with_plan()
        plan_service.generate_plan(training_id)

        app = AppTest.from_file(self._home_wrapper, default_timeout=60)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(
            any("今日训练" in subheader.value for subheader in app.subheader),
            [subheader.value for subheader in app.subheader],
        )

    def test_answer_button_records_attempt(self) -> None:
        """点「✓ 答对」应写一条作答记录并把训练项标为练过（不是达标）。"""
        from streamlit.testing.v1 import AppTest

        from src.db import queries
        from src.services import plan_service

        training_id = self._training_with_plan()
        plan_service.generate_plan(training_id)
        task = plan_service.today_tasks(training_id=training_id)[0]

        app = AppTest.from_file(self._daily_wrapper, default_timeout=60)
        app.query_params["page"] = "daily"
        app.query_params["training_id"] = str(training_id)
        app.run()
        self.assertFalse(app.exception)
        app.button(key=f"dl_pass_{task.plan_id}").click().run()
        self.assertFalse(app.exception)

        conn = queries.get_connection()
        try:
            attempt = conn.execute(
                "SELECT result, item_key, plan_id FROM practice_attempts WHERE training_id = ?",
                (training_id,),
            ).fetchone()
            item = conn.execute(
                "SELECT status FROM training_items WHERE item_key = ?", (task.item_key,)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(attempt, "点答对必须留下作答记录")
        self.assertEqual(attempt["result"], "pass")
        self.assertEqual(attempt["plan_id"], task.plan_id)
        self.assertEqual(item["status"], "practiced")

    def test_quiz_section_starts_assessment(self) -> None:
        """点「开始测验」应生成一次测验批次（题目来自冷却期外的题库）。"""
        from streamlit.testing.v1 import AppTest

        from src.db import queries
        from src.services import plan_service

        training_id = self._training_with_plan()
        plan_service.generate_plan(training_id)
        task = plan_service.today_tasks(training_id=training_id)[0]
        plan_service.complete_tasks([task.plan_id])  # 练过 → 入题库（冷却期 14 天）

        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE question_bank SET cooldown_until = '2026-01-01' WHERE training_id = ?",
                (training_id,),
            )
            conn.commit()
        finally:
            conn.close()

        app = AppTest.from_file(self._daily_wrapper, default_timeout=60)
        app.query_params["page"] = "daily"
        app.query_params["training_id"] = str(training_id)
        app.run()
        self.assertFalse(app.exception)
        app.button(key=f"dl_quiz_start_{training_id}").click().run()
        self.assertFalse(app.exception, "开始测验不应抛异常（LLM 不可用时应降级为原题）")

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT id, status, question_count FROM assessments WHERE training_id = ?",
                (training_id,),
            ).fetchone()
            item_count = conn.execute(
                "SELECT COUNT(*) AS n FROM assessment_items WHERE assessment_id = ?",
                (int(row["id"]),),
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertIsNotNone(row, "应生成一条测验批次")
        self.assertEqual(row["status"], "in_progress")
        self.assertEqual(int(row["question_count"]), 1)
        self.assertEqual(int(item_count), 1)


if __name__ == "__main__":
    unittest.main()
