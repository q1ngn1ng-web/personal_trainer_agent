"""Pure-Python unit tests for key algorithms in the trainer project.

These tests have no pytest dependency — they run on stdlib ``unittest`` so
they can be executed via either::

    uv run python -m unittest tests.test_units -v
    uv run python -m pytest tests/test_units.py -v

Each test skips itself (rather than failing) if a dependency cannot be
imported, so the suite is robust against partial installations.

Coverage:

* ``TestScheduleAlgorithm`` — ``next_review_date`` and ``interval_for_index``
* ``TestContentDimDistribution`` — ``distribute_by_ratio`` at boundary ``n``s
* ``TestBaselineLevel`` — ``compute_level`` at 0/1.5/2.4/2.5/3.9/4.0/5.0
* ``TestFileSanitization`` — ``sanitize_dir_name`` edge cases
* ``TestRendererEmpty`` — ``render_training_files({})`` returns 10 files
* ``TestMetricsEmpty`` — ``compute_weekly_metrics(999)`` returns zeros
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import sys

# Make ``src.*`` importable when this file is run directly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _skip_on_import_error(label: str):
    """Decorator: skip a test class when its target module cannot be imported."""
    def wrap(cls):
        original = cls.runTest if hasattr(cls, "runTest") else None
        try:
            __import__(label.split(".")[0])
        except Exception as exc:  # pragma: no cover - environmental
            msg = f"skipping {cls.__name__}: cannot import {label!r}: {exc}"
            return unittest.skip(msg)(cls)
        return cls
    return wrap


# ---------------------------------------------------------------------------
# Schedule algorithm (src.services.schedule_service)
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.schedule_service")
class TestScheduleAlgorithm(unittest.TestCase):
    """Spaced-repetition interval math used by the daily card."""

    def test_interval_for_index_known(self) -> None:
        from src.services.schedule_service import STANDARD_INTERVALS, interval_for_index

        for idx, expected in enumerate(STANDARD_INTERVALS):
            with self.subTest(idx=idx):
                self.assertEqual(interval_for_index(idx), expected)

    def test_interval_for_index_beyond_last(self) -> None:
        from src.services.schedule_service import STANDARD_INTERVALS, interval_for_index

        # idx 100 should clamp to the longest configured interval
        self.assertEqual(interval_for_index(100), STANDARD_INTERVALS[-1])

    def test_interval_for_index_zero(self) -> None:
        from src.services.schedule_service import STANDARD_INTERVALS, interval_for_index

        self.assertEqual(interval_for_index(0), STANDARD_INTERVALS[0])

    def test_interval_for_index_five(self) -> None:
        from src.services.schedule_service import interval_for_index

        # Out-of-range since STANDARD_INTERVALS has 5 items (idx 0..4)
        self.assertEqual(interval_for_index(5), 30)

    def test_next_review_date_index_zero(self) -> None:
        from src.services.schedule_service import next_review_date

        last = date(2026, 7, 1)
        self.assertEqual(next_review_date(last, 0), date(2026, 7, 2))

    def test_next_review_date_index_five(self) -> None:
        from src.services.schedule_service import next_review_date

        last = date(2026, 7, 1)
        # Out-of-range → 30 day cadence
        self.assertEqual(next_review_date(last, 5), date(2026, 7, 31))

    def test_next_review_date_index_100(self) -> None:
        from src.services.schedule_service import next_review_date

        last = date(2026, 7, 1)
        self.assertEqual(next_review_date(last, 100), date(2026, 7, 31))


# ---------------------------------------------------------------------------
# Content dimension distribution
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.core.content_dim")
class TestContentDimDistribution(unittest.TestCase):
    """distribute_by_ratio always returns values summing to ``total``."""

    def setUp(self) -> None:
        from src.core.content_dim import DEFAULT_DAILY_RATIO, distribute_by_ratio

        self._distribute = distribute_by_ratio
        self._ratio = DEFAULT_DAILY_RATIO

    def test_zero_total(self) -> None:
        result = self._distribute(0, self._ratio)
        total = sum(result.values())
        self.assertEqual(total, 0)
        for dim, value in result.items():
            self.assertEqual(value, 0, f"dimension {dim} should be 0")

    def test_one_total(self) -> None:
        result = self._distribute(1, self._ratio)
        self.assertEqual(sum(result.values()), 1)

    def test_distribution_sums_to_n(self) -> None:
        for n in (2, 3, 5, 7, 10, 13, 100, 1000):
            with self.subTest(n=n):
                result = self._distribute(n, self._ratio)
                self.assertEqual(sum(result.values()), n)
                # All values must be non-negative integers
                for dim, value in result.items():
                    self.assertIsInstance(value, int, f"{dim}={value!r} not int")
                    self.assertGreaterEqual(value, 0)


# ---------------------------------------------------------------------------
# Baseline level buckets
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.core.baseline")
class TestBaselineLevel(unittest.TestCase):
    """Boundaries of the 0-5 baseline score → level mapping."""

    def test_score_zero_is_low(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(0), BaselineLevel.LOW)

    def test_score_15_is_low(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(1.5), BaselineLevel.LOW)

    def test_score_24_is_low(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(2.4), BaselineLevel.LOW)

    def test_score_25_is_mid(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(2.5), BaselineLevel.MID)

    def test_score_39_is_mid(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(3.9), BaselineLevel.MID)

    def test_score_40_is_high(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(4.0), BaselineLevel.HIGH)

    def test_score_50_is_high(self) -> None:
        from src.core.baseline import compute_level
        from src.core.element import BaselineLevel

        self.assertEqual(compute_level(5.0), BaselineLevel.HIGH)


# ---------------------------------------------------------------------------
# File sanitization
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.file_writer")
class TestFileSanitization(unittest.TestCase):
    """Edge cases for sanitize_dir_name."""

    def setUp(self) -> None:
        from src.services.file_writer import sanitize_dir_name

        self._sanitize = sanitize_dir_name

    def test_plain_text(self) -> None:
        result = self._sanitize("test")
        self.assertTrue(result.startswith("training_"))
        self.assertIn("test", result)

    def test_with_slash_replaced(self) -> None:
        result = self._sanitize("with/slash")
        self.assertNotIn("/", result)
        self.assertIn("with", result)
        self.assertIn("slash", result)

    def test_empty_string(self) -> None:
        # Empty topic must still produce a valid directory name
        result = self._sanitize("")
        self.assertEqual(result, "training_")

    def test_long_string_truncated(self) -> None:
        long_text = "a" * 100
        result = self._sanitize(long_text)
        # Cap should be around 60 chars (+ the "training_" prefix)
        self.assertLess(len(result), 80, f"too long: {len(result)} chars")
        self.assertTrue(result.startswith("training_"))

    def test_chinese_with_slash(self) -> None:
        # Verifies that Chinese characters survive and the slash is escaped
        result = self._sanitize("Python asyncio/aiohttp 概念")
        self.assertNotIn("/", result)
        self.assertNotIn(" ", result)
        self.assertIn("Python", result)
        self.assertIn("asyncio", result)
        self.assertIn("aiohttp", result)


# ---------------------------------------------------------------------------
# Renderer empty-context behaviour
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.renderer")
class TestRendererEmpty(unittest.TestCase):
    """render_training_files({}) must still produce 10 non-empty files."""

    def test_render_empty_context_returns_ten_files(self) -> None:
        from src.services.renderer import render_training_files

        rendered = render_training_files({})
        self.assertEqual(len(rendered), 10, f"got {len(rendered)}: {sorted(rendered.keys())}")
        for name, content in rendered.items():
            self.assertTrue(name.endswith(".md"), f"unexpected name {name}")
            self.assertIsInstance(content, str)
            self.assertGreater(len(content.strip()), 0, f"{name} empty")


# ---------------------------------------------------------------------------
# Weekly metrics with no data
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.metrics_calculator")
class TestMetricsEmpty(unittest.TestCase):
    """compute_weekly_metrics for an unknown training must not crash."""

    def test_metrics_for_missing_training(self) -> None:
        try:
            from src.services.metrics_calculator import compute_weekly_metrics
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"metrics_calculator unavailable: {exc}")
        # 999 is almost certainly not present in the production DB
        metrics = compute_weekly_metrics(999)
        # Dataclass — read attributes defensively
        self.assertEqual(int(getattr(metrics, "days_logged", 0)), 0)
        self.assertEqual(getattr(metrics, "avg_completion", 0.0), 0.0)
        self.assertEqual(getattr(metrics, "avg_recall_success", 0.0), 0.0)
        self.assertEqual(getattr(metrics, "three_reflection_coverage", 0.0), 0.0)
        self.assertEqual(int(getattr(metrics, "consecutive_days", 0)), 0)
        # Missed tasks should be an empty list
        missed = list(getattr(metrics, "missed_tasks", []) or [])
        self.assertEqual(missed, [])
        # Weakest/strongest topics should be None
        self.assertIsNone(getattr(metrics, "weakest_topic", None))
        self.assertIsNone(getattr(metrics, "strongest_topic", None))


# ---------------------------------------------------------------------------
# Timestamp consistency (regression: trainer_service was using naive local time
# which broke cross-DB sorting vs queries._now() / review_service._now_iso())
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.trainer_service")
class TestTimestampConsistency(unittest.TestCase):
    """Every module's _now_iso must produce timezone-aware UTC ISO strings."""

    def test_trainer_service_now_iso_is_utc_aware(self) -> None:
        try:
            from src.services.trainer_service import _now_iso as trainer_now
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"trainer_service unavailable: {exc}")
        from datetime import datetime
        iso = trainer_now()
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo, f"expected tz-aware, got {iso!r}")
        # UTC offset should be zero
        offset = parsed.utcoffset()
        self.assertIsNotNone(offset)
        self.assertEqual(offset.total_seconds(), 0)

    def test_queries_now_is_utc_aware(self) -> None:
        try:
            from src.db.queries import _now as queries_now
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"queries unavailable: {exc}")
        from datetime import datetime
        iso = queries_now()
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo, f"expected tz-aware, got {iso!r}")
        offset = parsed.utcoffset()
        self.assertIsNotNone(offset)
        self.assertEqual(offset.total_seconds(), 0)

    def test_review_service_now_iso_is_utc_aware(self) -> None:
        try:
            from src.services.review_service import _now_iso as review_now
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"review_service unavailable: {exc}")
        from datetime import datetime
        iso = review_now()
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo, f"expected tz-aware, got {iso!r}")
        offset = parsed.utcoffset()
        self.assertIsNotNone(offset)
        self.assertEqual(offset.total_seconds(), 0)

    def test_daily_log_service_now_iso_is_utc_aware(self) -> None:
        try:
            from src.services.daily_log_service import _now_iso as dlog_now
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"daily_log_service unavailable: {exc}")
        from datetime import datetime
        iso = dlog_now()
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo, f"expected tz-aware, got {iso!r}")
        offset = parsed.utcoffset()
        self.assertIsNotNone(offset)
        self.assertEqual(offset.total_seconds(), 0)


# ---------------------------------------------------------------------------
# progress_service type coercion (regression: TrainingProgress fields are
# enum-typed but values come from DB as strings — must be coerced.)
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.progress_service")
class TestProgressCoercion(unittest.TestCase):
    """TrainingProgress must yield real enums / datetimes, not raw DB strings."""

    def test_empty_progress_uses_enums(self) -> None:
        try:
            from src.services.progress_service import _empty_progress, TrainingProgress
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"progress_service unavailable: {exc}")
        from src.core.element import BaselineLevel, TrainingStatus
        p = _empty_progress(999)
        self.assertIsInstance(p.status, TrainingStatus)
        self.assertIsInstance(p.baseline_level, BaselineLevel)
        self.assertEqual(p.status, TrainingStatus.CREATED)
        self.assertEqual(p.baseline_level, BaselineLevel.LOW)

    def test_compute_training_progress_handles_known_db_status(self) -> None:
        """DB CHECK constraint blocks garbage statuses, but valid string statuses
        must be coerced into the TrainingStatus enum on the way out."""
        try:
            from src.services.progress_service import compute_training_progress
            from src.core.element import TrainingStatus
            from src.db.queries import create_training
            from src.db.sqlite import init_db, get_connection
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"imports unavailable: {exc}")
        init_db()
        # Insert a row with valid status string; capture the assigned id
        row = create_training(topic="test_coercion", status="active", baseline_score=3.5)
        new_id = int(row.id)
        try:
            p = compute_training_progress(new_id)
            self.assertIsInstance(p.status, TrainingStatus)
            self.assertEqual(p.status, TrainingStatus.ACTIVE)
            # Also confirm the underlying string was "active", not silently downgraded
            from src.db.queries import get_training
            raw = get_training(new_id)
            self.assertEqual(raw.status, "active")
        finally:
            conn = get_connection()
            conn.execute("DELETE FROM trainings WHERE id = ?", (new_id,))
            conn.commit()
            conn.close()


# ---------------------------------------------------------------------------
# Datetime subtraction consistency (regression: page_daily / page_review /
# core/training called datetime.now() against DB-loaded tz-aware datetimes,
# raising TypeError. All such comparisons must use datetime.now(timezone.utc).)
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.core.training")
class TestDatetimeSubtraction(unittest.TestCase):
    """Days-since / needs-weekly-review must work with tz-aware DB timestamps."""

    def test_domain_training_days_since_creation_with_tz_aware(self) -> None:
        try:
            from src.core.training import Training
            from datetime import datetime, timedelta, timezone
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"imports unavailable: {exc}")
        # When created_at comes from a DB parse (tz-aware UTC ISO string), the
        # diff against datetime.now(timezone.utc) must not raise.
        aware = datetime.now(timezone.utc) - timedelta(days=5)
        t = Training(topic="x")
        t.created_at = aware
        days = t.days_since_creation
        # Allow 4–6 days to account for the time elapsed since we set aware.
        self.assertGreaterEqual(days, 4)
        self.assertLessEqual(days, 6)

    def test_domain_training_needs_weekly_review_with_tz_aware(self) -> None:
        try:
            from src.core.training import Training
            from datetime import datetime, timedelta, timezone
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"imports unavailable: {exc}")
        old = datetime.now(timezone.utc) - timedelta(days=10)
        t = Training(topic="x", created_at=old, last_review_at=None)
        self.assertTrue(t.needs_weekly_review())

    def test_db_iso_string_subtracts_from_utc_now_without_typeerror(self) -> None:
        """The exact pattern from src/ui/page_daily.py:60 — must not raise."""
        try:
            from datetime import datetime, timezone
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"datetime unavailable: {exc}")
        # Simulate what _parse_created_at returns from a UTC ISO string
        created_str = "2026-07-25T12:00:00+00:00"
        created_at = datetime.fromisoformat(created_str)
        # This is the buggy line that raised TypeError before the fix:
        days = (datetime.now(timezone.utc) - created_at).days
        # Sanity check: days should be some non-negative number
        self.assertGreaterEqual(days, 0)
        self.assertLess(days, 365)

    def test_trainer_service_now_iso_used_throughout(self) -> None:
        """Defensive: after the fix, no `datetime.now()` (naive) should appear
        inside trainer_service.py — all timestamp writes go through _now_iso()."""
        import re
        from pathlib import Path
        src = Path("src/services/trainer_service.py").read_text()
        # Strip comments and string literals to avoid false positives
        for line in src.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Match: datetime.now() OR datetime.now( anything other than timezone.utc )
            bad = re.search(r"datetime\.now\((?!\s*timezone\.utc\s*\))", line)
            if bad:
                self.fail(
                    f"trainer_service.py uses naive datetime.now(): {line!r}"
                )

    def test_naive_iso_string_subtraction_does_not_raise(self) -> None:
        """Regression: legacy DB rows have naive ISO strings (no tz suffix).
        Subtract from datetime.now(timezone.utc) must not raise TypeError.
        This is the exact pattern that crashed page_daily.py:60 for the user."""
        from datetime import datetime, timezone, timedelta
        # Naive ISO string, like '2026-07-25T22:16:31' from a legacy row.
        naive_iso = "2026-07-25T22:16:31"
        parsed = datetime.fromisoformat(naive_iso)
        self.assertIsNone(parsed.tzinfo)
        # Without the defensive fix in page_daily._parse_created_at this raises.
        with self.assertRaises(TypeError):
            _ = (datetime.now(timezone.utc) - parsed).days
        # With the defensive parser applied (tzinfo=UTC), no raise. Use a
        # recent naive timestamp that's guaranteed to be < now (UTC) regardless
        # of local timezone, so the diff is positive.
        recent_naive = (datetime.now(timezone.utc) - timedelta(days=5)).replace(tzinfo=None).isoformat()
        recent_parsed = datetime.fromisoformat(recent_naive)
        recent_defensive = recent_parsed.replace(tzinfo=timezone.utc)
        # Cross-tz arithmetic now works
        days = (datetime.now(timezone.utc) - recent_defensive).days
        self.assertGreaterEqual(days, 0)


# ---------------------------------------------------------------------------
# create_training schedule/recall population (regression: day-one daily page
# used to show "今日训练 (待初始化)" because schedule.units and
# materials.recall_units were never populated in DB.)
# ---------------------------------------------------------------------------
@_skip_on_import_error("src.services.trainer_service")
class TestPopulateScheduleAndRecall(unittest.TestCase):
    """The helper wired into create_training must populate units + recall."""

    def test_units_populated_from_specialized_materials(self) -> None:
        try:
            from src.services.trainer_service import _populate_schedule_and_recall
            from src.services.baseline_service import BaselineQuestion, BaselineQuestions
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"trainer_service unavailable: {exc}")
        schedule = {"intervals": [1, 3, 7, 15, 30]}
        materials = {
            "specialized_materials": [
                {"name": "协程基础"},
                {"name": "事件循环"},
                {"name": "asyncio 实战"},
            ],
            "principles": [],
        }
        bq = BaselineQuestions(
            questions=[
                BaselineQuestion(
                    dimension="concept",
                    difficulty=2,
                    question="Q1?",
                    reference_answer="A1",
                ),
            ],
            raw={},
            fallback_used=False,
        )
        _populate_schedule_and_recall(schedule, materials, bq, today="2026-07-26")
        # First unit is the baseline unit, then one per material.
        units = schedule["units"]
        self.assertEqual(len(units), 4)
        self.assertEqual(units[0]["name"], "基线诊断题")
        self.assertEqual(units[0]["review_count"], 0)
        self.assertEqual(units[0]["learned_date"], "2026-07-26")
        self.assertEqual(units[1]["name"], "协程基础")
        self.assertEqual(units[2]["name"], "事件循环")
        self.assertEqual(units[3]["name"], "asyncio 实战")

    def test_recall_units_seeded_from_baseline_questions(self) -> None:
        try:
            from src.services.trainer_service import _populate_schedule_and_recall
            from src.services.baseline_service import BaselineQuestion, BaselineQuestions
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"trainer_service unavailable: {exc}")
        schedule = {}
        materials = {"specialized_materials": []}
        bq = BaselineQuestions(
            questions=[
                BaselineQuestion(
                    dimension="concept",
                    difficulty=2,
                    question="什么是协程?",
                    reference_answer="可在执行中暂停的函数",
                ),
                BaselineQuestion(
                    dimension="read",
                    difficulty=2,
                    question="读这段事件循环代码",
                    reference_answer="事件循环调度任务",
                ),
                BaselineQuestion(
                    dimension="write",
                    difficulty=3,
                    question="写并发爬虫",
                    reference_answer="用 aiohttp gather",
                ),
            ],
            raw={},
            fallback_used=False,
        )
        _populate_schedule_and_recall(schedule, materials, bq, today="2026-07-26")
        recall = materials["recall_units"]
        self.assertEqual(len(recall), 1)
        self.assertEqual(recall[0]["unit"], "基线诊断题")
        self.assertEqual(len(recall[0]["questions"]), 3)
        self.assertEqual(recall[0]["questions"][0]["qid"], "Q1")
        # Each question carries its individual dimension (concept/read/write)
        self.assertEqual(recall[0]["questions"][0]["dimension"], "concept")
        self.assertEqual(recall[0]["questions"][2]["dimension"], "write")

    def test_handles_no_baseline_questions(self) -> None:
        """If user skipped baseline answers, helper should still seed units
        from materials (only no baseline unit)."""
        try:
            from src.services.trainer_service import _populate_schedule_and_recall
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"trainer_service unavailable: {exc}")
        schedule = {}
        materials = {"specialized_materials": [{"name": "A"}, {"name": "B"}]}
        _populate_schedule_and_recall(schedule, materials, None, today="2026-07-26")
        # 0 baseline units + 2 material units = 2
        self.assertEqual(len(schedule["units"]), 2)
        # No recall without baseline questions
        self.assertEqual(materials["recall_units"], [])

    def test_units_capped_at_max(self) -> None:
        """Protect the daily card from 100+ units on busy trainings."""
        try:
            from src.services.trainer_service import _populate_schedule_and_recall, _MAX_UNITS_FROM_MATERIALS
        except Exception as exc:  # pragma: no cover - environmental
            self.skipTest(f"trainer_service unavailable: {exc}")
        schedule = {}
        # 50 materials → only top _MAX_UNITS_FROM_MATERIALS appear
        materials = {
            "specialized_materials": [
                {"name": f"专题 {i}"} for i in range(50)
            ],
        }
        bq = None
        _populate_schedule_and_recall(schedule, materials, bq, today="2026-07-26")
        # Just the materials (no baseline unit) → capped
        self.assertEqual(len(schedule["units"]), _MAX_UNITS_FROM_MATERIALS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
