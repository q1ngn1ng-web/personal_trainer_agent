"""阶段达标与任务达标测试：覆盖/达成两种模式、任务终态、阶段状态写回、老库状态迁移。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.mastery import (  # noqa: E402
    COVERAGE_MODE,
    MASTERY_MODE,
    acceptance_satisfied,
    coverage_satisfied,
    stage_mastered,
)
from src.db import queries  # noqa: E402
from src.db.migrate import migrate  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import attempt_service, mastery_service, path_service, plan_service  # noqa: E402

ANCHOR = date(2026, 9, 20)


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
            ),
            path_service.PlannedStage(
                title="阶段二",
                goal="综合",
                items=[
                    path_service.PlannedItem(
                        title="AOF 重写",
                        item_type="comprehension",
                        difficulty=3,
                        knowledge_point="AOF",
                        minutes=15,
                    )
                ],
            ),
        ],
    )


class TestMasteryPure(unittest.TestCase):
    def test_coverage_requires_every_item_passed(self) -> None:
        self.assertTrue(coverage_satisfied(["passed", "passed"]))
        self.assertFalse(coverage_satisfied(["passed", "practiced"]))
        self.assertFalse(coverage_satisfied([]))

    def test_acceptance_quantitative_metrics(self) -> None:
        accuracy_target = {"type": "quantitative", "metric": "accuracy", "target": 0.9}
        self.assertTrue(acceptance_satisfied(accuracy_target, accuracy=0.95)[0])
        self.assertFalse(acceptance_satisfied(accuracy_target, accuracy=0.8)[0])
        volume_target = {"type": "quantitative", "metric": "volume", "target": 10}
        self.assertTrue(acceptance_satisfied(volume_target, practiced=12)[0])
        streak_target = {"type": "quantitative", "metric": "streak", "target": 3}
        self.assertFalse(acceptance_satisfied(streak_target, streak=2)[0])

    def test_acceptance_cannot_judge_speed_or_qualitative(self) -> None:
        speed_target = {"type": "quantitative", "metric": "speed", "target": 10}
        self.assertIsNone(acceptance_satisfied(speed_target)[0])
        self.assertIsNone(acceptance_satisfied({"type": "qualitative", "statement": "能讲清楚"})[0])
        self.assertIsNone(acceptance_satisfied(None)[0])

    def test_stage_mastered_coverage_mode(self) -> None:
        self.assertTrue(stage_mastered(COVERAGE_MODE, ["passed", "passed"]).mastered)
        verdict = stage_mastered(COVERAGE_MODE, ["passed", "practiced"])
        self.assertFalse(verdict.mastered)
        self.assertIn("必修项未达标", verdict.reason)

    def test_stage_mastered_mastery_mode_and_fallback(self) -> None:
        verdict = stage_mastered(
            MASTERY_MODE,
            ["passed", "practiced"],
            acceptance={"type": "quantitative", "metric": "accuracy", "target": 0.8},
            accuracy=0.9,
        )
        self.assertTrue(verdict.mastered)
        fallback = stage_mastered(
            MASTERY_MODE,
            ["passed", "practiced"],
            acceptance={"type": "quantitative", "metric": "speed", "target": 10},
        )
        self.assertFalse(fallback.mastered)
        self.assertIn("退回覆盖口径", fallback.reason)


class TestMasteryService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "mastery.db")
        init_db()
        self.training = queries.create_training(topic="Redis 持久化", status="active")
        queries.update_training(
            self.training.id, created_at=f"{ANCHOR.isoformat()}T10:00:00+08:00"
        )
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)
        self.items = self._items()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _items(self) -> list[dict]:
        conn = queries.get_connection()
        try:
            rows = conn.execute(
                "SELECT i.id, i.item_key, i.title, s.id AS stage_id, s.ordinal AS stage_ordinal "
                "FROM training_items i JOIN path_stages s ON s.id = i.stage_id "
                "ORDER BY s.ordinal, i.ordinal"
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def _pass_item(self, item_key: str, times: int = 2) -> None:
        for _ in range(times):
            attempt_service.record_and_evaluate(self.training.id, item_key, "pass")

    def _insert_passed_quiz(self) -> None:
        conn = queries.get_connection()
        try:
            conn.execute(
                "INSERT INTO assessments (training_id, trigger, status, question_count, score, "
                "passed, created_at, completed_at) VALUES (?, 'manual', 'completed', 2, 1.0, 1, "
                "'2026-10-05T00:00:00+00:00', '2026-10-05T00:00:00+00:00')",
                (self.training.id,),
            )
            conn.commit()
        finally:
            conn.close()

    def test_stage_status_written_back(self) -> None:
        before = mastery_service.sync_stages(self.training.id)
        self.assertEqual([stage.status for stage in before], ["active", "locked"])
        self.assertFalse(any(stage.mastered for stage in before))

        self._pass_item(self.items[0]["item_key"])
        after = mastery_service.sync_stages(self.training.id)
        self.assertTrue(after[0].mastered)
        self.assertEqual(after[0].status, "completed")
        self.assertEqual(after[1].status, "active", "第一个未达标阶段应变成 active")

    def test_training_not_mastered_without_passed_quiz(self) -> None:
        for item in self.items:
            self._pass_item(item["item_key"])
        report = mastery_service.training_progress(self.training.id)
        self.assertTrue(report.coverage_done)
        self.assertFalse(report.quiz_passed)
        self.assertFalse(report.mastered)
        self.assertIn("测验", report.reason)
        self.assertIsNone(mastery_service.sync_training_status(self.training.id))

    def test_training_mastered_after_coverage_and_quiz(self) -> None:
        for item in self.items:
            self._pass_item(item["item_key"])
        self._insert_passed_quiz()

        report = mastery_service.evaluate(self.training.id)
        self.assertTrue(report.mastered)
        self.assertEqual([stage.status for stage in report.stages], ["completed", "completed"])

        conn = queries.get_connection()
        try:
            status = conn.execute(
                "SELECT status FROM trainings WHERE id = ?", (self.training.id,)
            ).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(status, "completed", "任务达标 → 训练进入终态")

    def test_mastery_mode_uses_acceptance_target(self) -> None:
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE training_paths SET mode = 'mastery' WHERE training_id = ?",
                (self.training.id,),
            )
            conn.execute(
                "UPDATE trainings SET goal_json = ? WHERE id = ?",
                (
                    json.dumps(
                        {
                            "acceptance": {
                                "type": "quantitative",
                                "metric": "accuracy",
                                "target": 1.0,
                            }
                        },
                        ensure_ascii=False,
                    ),
                    self.training.id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._pass_item(self.items[0]["item_key"], times=1)
        stages = mastery_service.stage_statuses(self.training.id)
        self.assertFalse(stages[0].mastered, "达成模式必须看验收判据而不是单次练习")


class TestCompletedStatusMigration(unittest.TestCase):
    """老库的 trainings.status CHECK 没有 completed，必须能迁移。"""

    _LEGACY_SQL = """
    CREATE TABLE trainings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        status TEXT DEFAULT 'draft' CHECK (status IN ('created', 'draft', 'pending_confirm', 'confirmed', 'active', 'paused', 'archived', 'failed')),
        goal_json TEXT,
        goal_confirmed_at DATETIME,
        clarification_rounds INTEGER DEFAULT 0,
        keywords TEXT,
        must_cover_count INTEGER DEFAULT 2,
        forbidden TEXT,
        directory TEXT,
        baseline_score REAL DEFAULT 0,
        baseline_level TEXT,
        targets TEXT,
        review_items TEXT,
        pretrain_checklist TEXT,
        schedule TEXT,
        materials TEXT,
        current_week INTEGER DEFAULT 1,
        last_review_at DATETIME,
        created_at DATETIME NOT NULL,
        last_active_at DATETIME
    );
    INSERT INTO trainings (id, topic, status, created_at)
        VALUES (1, 'Redis', 'active', '2026-09-20T10:00:00');
    """

    def test_migration_allows_completed_status(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = sqlite3.connect(str(Path(tmp.name) / "legacy_trainings.db"))
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(self._LEGACY_SQL)
            conn.commit()
            applied = migrate(conn)
            self.assertTrue(any(name.startswith("trainings:") for name in applied), applied)

            row = conn.execute("SELECT topic, status FROM trainings WHERE id = 1").fetchone()
            self.assertEqual(row["topic"], "Redis")
            self.assertEqual(row["status"], "active", "老状态必须保留")
            conn.execute("UPDATE trainings SET status = 'completed' WHERE id = 1")
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT status FROM trainings WHERE id = 1").fetchone()["status"],
                "completed",
            )
            self.assertEqual(migrate(conn), [], "迁移必须幂等")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
