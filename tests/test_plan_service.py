"""训练计划测试：5 轮排期、当日取数、累计顺延、题库冷却期、迁移。"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.plan import (  # noqa: E402
    COOLDOWN_DAYS,
    PlanSlot,
    cooldown_until,
    item_key_for,
    local_today,
    quiz_due_dates,
    round_due_dates,
    select_today_slots,
)
from src.db import queries  # noqa: E402
from src.db.migrate import migrate  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import path_service, plan_service  # noqa: E402

ANCHOR = date(2026, 9, 20)


def _skeleton(training_id: int) -> path_service.PathSkeleton:
    """两道阶段、共 3 个训练项的最小路径。"""
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
                        title="AOF 重写过程",
                        item_type="comprehension",
                        difficulty=3,
                        knowledge_point="AOF",
                        minutes=15,
                    ),
                ],
            ),
            path_service.PlannedStage(
                title="阶段二",
                goal="综合",
                items=[
                    path_service.PlannedItem(
                        title="RDB 与 AOF 混合持久化",
                        item_type="practice",
                        difficulty=4,
                        knowledge_point="混合持久化",
                        minutes=20,
                    )
                ],
            ),
        ],
    )


class TestPlanPureFunctions(unittest.TestCase):
    def test_local_today_uses_local_timezone(self) -> None:
        # UTC 20:00 = 东八区次日 04:00
        moment = datetime(2026, 9, 20, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(local_today(moment), date(2026, 9, 21))

    def test_round_due_dates(self) -> None:
        dues = round_due_dates(ANCHOR)
        self.assertEqual(
            [dues[index] for index in sorted(dues)],
            [
                date(2026, 9, 21),
                date(2026, 9, 23),
                date(2026, 9, 27),
                date(2026, 10, 5),
                date(2026, 10, 20),
            ],
        )
        self.assertEqual(len(dues), 5)

    def test_quiz_due_dates_every_two_weeks(self) -> None:
        last_round = round_due_dates(ANCHOR)[5]
        self.assertEqual(quiz_due_dates(ANCHOR, last_round), [date(2026, 10, 4), date(2026, 10, 18)])

    def test_cooldown_is_two_weeks(self) -> None:
        self.assertEqual(COOLDOWN_DAYS, 14)
        self.assertEqual(cooldown_until(ANCHOR), date(2026, 10, 4))

    def test_item_key_is_stable_and_normalized(self) -> None:
        first = item_key_for(7, "RDB", "RDB  是什么")
        second = item_key_for(7, "RDB", "rdb 是什么")
        third = item_key_for(7, "AOF", "RDB 是什么")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(len(first), 12)

    def test_select_today_slots_keeps_earliest_unfinished_round(self) -> None:
        slots = [
            PlanSlot("a", 1, date(2026, 9, 21), "planned"),
            PlanSlot("a", 2, date(2026, 9, 23), "planned"),
            PlanSlot("b", 1, date(2026, 9, 21), "practiced"),
            PlanSlot("b", 2, date(2026, 9, 23), "planned"),
            PlanSlot("c", 1, date(2026, 9, 30), "planned"),
        ]
        picked = select_today_slots(slots, date(2026, 9, 24))
        self.assertEqual([(slot.item_key, slot.round_index) for slot in picked], [("a", 1), ("b", 2)])


class TestPlanService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "plan.db")
        init_db()
        self.training = queries.create_training(topic="Redis 持久化", status="active")
        # 固定创建日，让排期可复现
        queries.update_training(self.training.id, created_at=f"{ANCHOR.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(self.training.id))

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _plan_count(self) -> int:
        conn = queries.get_connection()
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM plan_items WHERE training_id = ?",
                    (self.training.id,),
                ).fetchone()["n"]
            )
        finally:
            conn.close()

    def test_generate_plan_creates_five_rounds_and_quizzes(self) -> None:
        summary = plan_service.generate_plan(self.training.id)
        self.assertEqual(summary.rounds, 5)
        self.assertEqual(summary.item_count, 3)
        self.assertEqual(summary.last_due_date, date(2026, 10, 20))
        self.assertEqual(summary.quiz_dates, [date(2026, 10, 4), date(2026, 10, 18)])
        # 3 题 × 5 轮 + 2 次测验
        self.assertEqual(summary.created, 17)
        self.assertEqual(self._plan_count(), 17)

    def test_generate_plan_is_idempotent(self) -> None:
        plan_service.generate_plan(self.training.id)
        again = plan_service.generate_plan(self.training.id)
        self.assertEqual(again.created, 0)
        self.assertEqual(self._plan_count(), 17)

    def test_training_items_get_stable_item_key(self) -> None:
        items = [
            item
            for stage in path_service.load_stages(
                path_service.load_path(self.training.id).id
            )
            for item in path_service.load_items(stage.id)
        ]
        self.assertTrue(all(item.item_key for item in items), "每个训练项都应有稳定题目键")
        # 重新生成路径（draft 会被替换）后 item_key 不变
        before = sorted(item_key_for(self.training.id, item.knowledge_point, item.title) for item in items)
        path_service.save_skeleton(_skeleton(self.training.id))
        after = sorted(item_key_for(self.training.id, item.knowledge_point, item.title) for item in items)
        self.assertEqual(before, after)

    def test_today_tasks_are_the_first_round_on_anchor_plus_one(self) -> None:
        plan_service.generate_plan(self.training.id)
        tasks = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))
        self.assertEqual(len(tasks), 3)
        self.assertTrue(all(task.round_index == 1 for task in tasks))
        self.assertTrue(all(not task.is_overdue(date(2026, 9, 21)) for task in tasks))

    def test_unfinished_items_accumulate_to_next_day(self) -> None:
        plan_service.generate_plan(self.training.id)
        # 9/22 没有轮次到期，但 9/21 的第 1 轮没做，应继续出现在今天
        tasks = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 22))
        self.assertEqual(len(tasks), 3)
        self.assertTrue(all(task.round_index == 1 for task in tasks))
        self.assertTrue(all(task.is_overdue(date(2026, 9, 22)) for task in tasks))
        self.assertTrue(all(task.due_date == date(2026, 9, 21) for task in tasks))

    def test_second_round_waits_until_first_round_done(self) -> None:
        plan_service.generate_plan(self.training.id)
        stale = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 24))
        self.assertTrue(all(task.round_index == 1 for task in stale), "第 1 轮没做完就不该出现第 2 轮")

        first_round = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))
        plan_service.complete_tasks([task.plan_id for task in first_round], today=date(2026, 9, 21))
        after = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 24))
        self.assertTrue(after)
        self.assertTrue(all(task.round_index == 2 for task in after))

    def test_complete_task_marks_practiced_not_passed(self) -> None:
        plan_service.generate_plan(self.training.id)
        task = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))[0]
        plan_service.complete_tasks([task.plan_id], today=date(2026, 9, 21))

        conn = queries.get_connection()
        try:
            plan_row = conn.execute(
                "SELECT status, practiced_at FROM plan_items WHERE id = ?", (task.plan_id,)
            ).fetchone()
            item_row = conn.execute(
                "SELECT status FROM training_items WHERE item_key = ?", (task.item_key,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(plan_row["status"], "practiced")
        self.assertTrue(plan_row["practiced_at"])
        self.assertEqual(item_row["status"], "practiced")
        self.assertNotEqual(item_row["status"], "passed")

    def test_question_bank_registration_and_cooldown(self) -> None:
        plan_service.generate_plan(self.training.id)
        task = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))[0]
        plan_service.complete_tasks([task.plan_id], today=date(2026, 9, 21))

        banked = plan_service.drawable_questions(self.training.id, today=date(2026, 9, 21))
        after_cooldown = plan_service.drawable_questions(
            self.training.id, today=date(2026, 10, 5)
        )
        self.assertEqual(banked, [], "刚练过的题在冷却期内不得被抽中")
        self.assertTrue(after_cooldown, "冷却期结束后应可被抽中")

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT practiced_count, cooldown_until, question_text FROM question_bank "
                "WHERE training_id = ? AND item_key = ?",
                (self.training.id, task.item_key),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(int(row["practiced_count"]), 1)
        self.assertEqual(row["cooldown_until"], "2026-10-05")
        self.assertTrue(row["question_text"], "题库应保存题目文本快照")

    def test_uncheck_keeps_practiced_history(self) -> None:
        plan_service.generate_plan(self.training.id)
        task = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))[0]
        plan_service.complete_tasks([task.plan_id], today=date(2026, 9, 21))
        plan_service.complete_tasks([task.plan_id], completed=False, today=date(2026, 9, 21))

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT status, practiced_at FROM plan_items WHERE id = ?", (task.plan_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "planned")
        self.assertTrue(row["practiced_at"], "取消勾选不应抹掉练过的证据")

    def test_skip_requires_reason(self) -> None:
        plan_service.generate_plan(self.training.id)
        task = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))[0]
        with self.assertRaises(ValueError):
            plan_service.skip_task(task.plan_id, "  ")
        plan_service.skip_task(task.plan_id, "出差")
        remaining = plan_service.today_tasks(training_id=self.training.id, today=date(2026, 9, 21))
        self.assertNotIn(task.plan_id, [item.plan_id for item in remaining])

    def test_cross_training_today_summary(self) -> None:
        plan_service.generate_plan(self.training.id)
        other = queries.create_training(topic="算法", status="active")
        queries.update_training(other.id, created_at=f"{ANCHOR.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(other.id))
        plan_service.generate_plan(other.id)

        summary = plan_service.today_summary(today=date(2026, 9, 21))
        self.assertEqual(summary["count"], 6)
        self.assertEqual(len(summary["groups"]), 2)
        self.assertEqual(summary["groups"][0]["count"], 3)

    def test_next_due_date_when_today_has_nothing(self) -> None:
        plan_service.generate_plan(self.training.id)
        # 第 5 轮之后：没有待做项
        self.assertIsNone(
            plan_service.next_due_date(self.training.id, today=date(2026, 10, 21))
        )
        self.assertEqual(
            plan_service.next_due_date(self.training.id, today=date(2026, 9, 21)),
            date(2026, 9, 23),
        )


class TestTrainingItemsMigration(unittest.TestCase):
    """老库（training_items 无 item_key、status 无 practiced）必须能迁移。"""

    _LEGACY_SQL = """
    CREATE TABLE trainings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        status TEXT DEFAULT 'draft',
        goal_json TEXT,
        created_at DATETIME NOT NULL
    );
    CREATE TABLE training_paths (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        training_id INTEGER NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        status TEXT DEFAULT 'draft',
        created_at DATETIME NOT NULL
    );
    CREATE TABLE path_stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL,
        title TEXT NOT NULL,
        goal TEXT,
        estimated_minutes INTEGER DEFAULT 0,
        status TEXT DEFAULT 'locked'
    );
    CREATE TABLE training_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL,
        title TEXT NOT NULL,
        item_type TEXT,
        difficulty_tier INTEGER,
        difficulty_basis TEXT,
        knowledge_point TEXT,
        source_chunk_ids TEXT,
        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'passed', 'failed')),
        created_at DATETIME NOT NULL
    );
    INSERT INTO trainings (id, topic, status, created_at)
        VALUES (1, 'Redis', 'active', '2026-09-20T10:00:00');
    INSERT INTO training_paths (id, training_id, version, status, created_at)
        VALUES (1, 1, 1, 'confirmed', '2026-09-20T10:00:00');
    INSERT INTO path_stages (id, path_id, ordinal, title)
        VALUES (1, 1, 1, '阶段一');
    INSERT INTO training_items (id, stage_id, ordinal, title, item_type, knowledge_point, status, created_at)
        VALUES (1, 1, 1, 'RDB 是什么', 'memory', 'RDB', 'passed', '2026-09-20T10:00:00');
    """

    def test_migration_adds_item_key_and_practiced_status(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(self._LEGACY_SQL)
            conn.commit()
            applied = migrate(conn)
            self.assertIn("training_items:item_key", applied)

            row = conn.execute(
                "SELECT item_key, status, title FROM training_items WHERE id = 1"
            ).fetchone()
            self.assertTrue(row["item_key"], "迁移必须回填稳定题目键")
            self.assertEqual(row["title"], "RDB 是什么")
            self.assertEqual(row["status"], "passed", "老状态必须保留")

            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'training_items'"
            ).fetchone()["sql"]
            self.assertIn("practiced", ddl)

            # 迁移后可以写入 practiced
            conn.execute("UPDATE training_items SET status = 'practiced' WHERE id = 1")
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT status FROM training_items WHERE id = 1").fetchone()["status"],
                "practiced",
            )

            # 幂等
            self.assertEqual(migrate(conn), [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
