"""学习信号与动作裁决的测试：四失映射、冲突裁决、限频、留痕。"""
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
from src.services import signal_service as svc  # noqa: E402


class TestDecide(unittest.TestCase):
    def test_four_signals_have_directions(self) -> None:
        for code, meta in svc.SIGNAL_ACTIONS.items():
            with self.subTest(code=code):
                self.assertTrue(meta["direction"])
                self.assertTrue(meta["action"])

    def test_self_reported_easy_but_objectively_low_is_blocked(self) -> None:
        decision = svc.decide("too_easy", objective="low", same_signal_today=5, structural_today=0)
        self.assertFalse(decision.applied)
        self.assertEqual(decision.blocked_reason, "objective_conflict")
        self.assertIn("还没通过", decision.message)

    def test_self_reported_hard_but_objectively_high_reduces_load(self) -> None:
        decision = svc.decide("too_hard", objective="high", same_signal_today=0, structural_today=0)
        self.assertTrue(decision.applied)
        self.assertEqual(decision.action, "reduce_load")

    def test_unknown_objective_only_light_adjustment(self) -> None:
        decision = svc.decide("too_hard", objective="unknown", same_signal_today=9, structural_today=0)
        self.assertEqual(decision.action, "light_hint")
        self.assertIn("作答数据", decision.message)

    def test_first_signal_only_hints(self) -> None:
        decision = svc.decide("too_easy", objective="high", same_signal_today=0, structural_today=0)
        self.assertEqual(decision.action, "light_hint")

    def test_second_same_signal_triggers_structural_change(self) -> None:
        decision = svc.decide("too_easy", objective="high", same_signal_today=1, structural_today=0)
        self.assertEqual(decision.action, "raise_difficulty")

    def test_daily_limit_blocks_second_structural_change(self) -> None:
        decision = svc.decide("too_hard", objective="low", same_signal_today=1, structural_today=1)
        self.assertFalse(decision.applied)
        self.assertEqual(decision.blocked_reason, "daily_limit")

    def test_unknown_signal_rejected(self) -> None:
        with self.assertRaises(ValueError):
            svc.decide("whatever", objective="high", same_signal_today=0, structural_today=0)


class TestSignalPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "signal.db")
        init_db()
        self.training = queries.create_training(topic="信号测试", status="active")

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_record_and_count(self) -> None:
        svc.record_signal(self.training.id, "too_hard")
        svc.record_signal(self.training.id, "too_hard")
        svc.record_signal(self.training.id, "too_easy")
        counts = svc.signal_counts(self.training.id)
        self.assertEqual(counts["too_hard"], 2)
        self.assertEqual(counts["too_easy"], 1)
        self.assertEqual(counts["too_much"], 0)
        self.assertEqual(len(svc.list_signals(self.training.id)), 3)

    def test_process_writes_adjustment_log(self) -> None:
        decision = svc.process_signal(self.training.id, "too_much", item_status=None)
        self.assertTrue(decision.applied)
        logs = svc.list_adjustments(self.training.id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].signal_type, "too_much")
        self.assertEqual(int(logs[0].blocked), 0)

    def test_blocked_adjustment_is_logged_too(self) -> None:
        decision = svc.process_signal(self.training.id, "too_easy", item_status="failed")
        self.assertFalse(decision.applied)
        logs = svc.list_adjustments(self.training.id)
        self.assertEqual(int(logs[0].blocked), 1)
        self.assertEqual(logs[0].reason, "objective_conflict")

    def test_invalid_signal_not_recorded(self) -> None:
        with self.assertRaises(ValueError):
            svc.record_signal(self.training.id, "nonsense")


if __name__ == "__main__":
    unittest.main()
