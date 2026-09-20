"""作答记录与达标判定测试：客观口径、连续达标、难度执行点、与四失信号的联动。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.mastery import (  # noqa: E402
    MASTERY_STREAK,
    MIN_ATTEMPTS_FOR_OBJECTIVE,
    accuracy,
    consecutive_passes,
    difficulty_delta,
    evaluate,
    objective_state,
)
from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import attempt_service, path_service, plan_service, signal_service  # noqa: E402


class TestMasteryPure(unittest.TestCase):
    def test_streak_counts_from_the_end(self) -> None:
        self.assertEqual(consecutive_passes(["pass", "fail", "pass", "pass"]), 2)
        self.assertEqual(consecutive_passes(["fail"]), 0)

    def test_accuracy_returns_none_without_data(self) -> None:
        self.assertIsNone(accuracy([]))
        self.assertAlmostEqual(accuracy(["pass", "fail"]), 0.5)

    def test_evaluate_marks_mastered_after_two_passes(self) -> None:
        self.assertEqual(MASTERY_STREAK, 2)
        state = evaluate(["fail", "pass", "pass"])
        self.assertTrue(state.mastered)
        self.assertEqual(state.streak, 2)
        self.assertFalse(evaluate(["pass", "fail"]).mastered)

    def test_objective_needs_at_least_three_attempts(self) -> None:
        self.assertEqual(MIN_ATTEMPTS_FOR_OBJECTIVE, 3)
        self.assertEqual(objective_state([]), "unknown")
        self.assertEqual(objective_state(["pass", "fail"]), "unknown")
        self.assertEqual(objective_state(["fail", "fail", "fail"]), "low")
        self.assertEqual(objective_state(["pass", "pass", "pass", "pass"]), "high")
        self.assertEqual(objective_state(["pass", "fail", "pass"]), "mid")

    def test_difficulty_delta_is_rule_based(self) -> None:
        self.assertEqual(difficulty_delta("high", "too_easy"), 1)
        self.assertEqual(difficulty_delta("mid", "too_easy"), 1)
        self.assertEqual(difficulty_delta("low", "too_easy"), 0)
        self.assertEqual(difficulty_delta("low", "too_hard"), -1)
        self.assertEqual(difficulty_delta("high", "too_hard"), 0)
        self.assertEqual(difficulty_delta("unknown", "too_easy"), 0)
        self.assertEqual(difficulty_delta("unknown", "too_hard"), 0)


class TestAttemptService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "attempt.db")
        init_db()
        self.training = queries.create_training(topic="Redis 持久化", status="active")
        queries.update_training(
            self.training.id, created_at="2026-09-20T10:00:00+08:00"
        )
        path_service.save_skeleton(self._skeleton())
        plan_service.generate_plan(self.training.id)
        self.task = plan_service.today_tasks(
            training_id=self.training.id, today=date(2026, 9, 21)
        )[0]

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _skeleton(self) -> path_service.PathSkeleton:
        return path_service.PathSkeleton(
            training_id=self.training.id,
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

    def test_record_attempt_validates_input(self) -> None:
        with self.assertRaises(ValueError):
            attempt_service.record_attempt(self.training.id, self.task.item_key, "maybe")
        with self.assertRaises(ValueError):
            attempt_service.record_attempt(self.training.id, "  ", "pass")

    def test_two_consecutive_passes_mark_mastered(self) -> None:
        item_key = self.task.item_key
        attempt_service.record_and_evaluate(self.training.id, item_key, "fail")
        self.assertFalse(attempt_service.mark_mastered_if_ready(self.training.id, item_key))
        attempt_service.record_and_evaluate(self.training.id, item_key, "pass")
        self.assertFalse(attempt_service.mark_mastered_if_ready(self.training.id, item_key))
        _, just_mastered = attempt_service.record_and_evaluate(self.training.id, item_key, "pass")
        self.assertTrue(just_mastered)

        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT status, mastered_at FROM training_items WHERE item_key = ?", (item_key,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "passed")
        self.assertTrue(row["mastered_at"], "达标时间必须留痕")

    def test_objective_for_training_tracks_recent_results(self) -> None:
        item_key = self.task.item_key
        for _ in range(3):
            attempt_service.record_attempt(self.training.id, item_key, "fail")
        self.assertEqual(attempt_service.objective_for_training(self.training.id), "low")
        for _ in range(5):
            attempt_service.record_attempt(self.training.id, item_key, "pass")
        self.assertEqual(attempt_service.objective_for_training(self.training.id), "high")

    def test_signal_uses_real_objective_and_blocks_conflict(self) -> None:
        item_key = self.task.item_key
        for _ in range(3):
            attempt_service.record_attempt(self.training.id, item_key, "fail")
        objective = attempt_service.objective_for_training(self.training.id)
        decision = signal_service.process_signal(
            self.training.id,
            "too_easy",
            item_key=item_key,
            item_id=plan_service.item_id_for(self.training.id, item_key),
            objective=objective,
        )
        self.assertEqual(decision.action, "none")
        self.assertEqual(decision.blocked_reason, "objective_conflict")

    def test_difficulty_execution_point_changes_tier_only(self) -> None:
        item_key = self.task.item_key
        for _ in range(3):
            attempt_service.record_attempt(self.training.id, item_key, "pass")
        objective = attempt_service.objective_for_training(self.training.id)
        self.assertEqual(objective, "high")

        before_tier = self._tier(item_key)
        decision = signal_service.decide(
            "too_easy", objective=objective, same_signal_today=1, structural_today=0
        )
        self.assertEqual(decision.action, "raise_difficulty")
        detail = signal_service.apply_decision(
            decision, training_id=self.training.id, item_key=item_key
        )
        self.assertEqual(detail.get("difficulty_before"), before_tier)
        self.assertEqual(detail.get("difficulty_after"), before_tier + 1)

        # 排期日期不受难度调整影响（ADR-0021）
        plan_dates = self._plan_dates(item_key)
        self.assertEqual(len(plan_dates), 5)

    def test_plan_signals_still_logged_as_light_hint_when_data_insufficient(self) -> None:
        decision = signal_service.process_signal(self.training.id, "too_hard", objective="unknown")
        self.assertEqual(decision.action, "light_hint")
        self.assertTrue(decision.applied)

    def _tier(self, item_key: str) -> int:
        conn = queries.get_connection()
        try:
            return int(
                conn.execute(
                    "SELECT difficulty_tier FROM training_items WHERE item_key = ?", (item_key,)
                ).fetchone()["difficulty_tier"]
            )
        finally:
            conn.close()

    def _plan_dates(self, item_key: str) -> list[str]:
        conn = queries.get_connection()
        try:
            rows = conn.execute(
                "SELECT due_date FROM plan_items WHERE training_id = ? AND item_key = ? "
                "ORDER BY round_index",
                (self.training.id, item_key),
            ).fetchall()
        finally:
            conn.close()
        return [str(row["due_date"]) for row in rows]


if __name__ == "__main__":
    unittest.main()
