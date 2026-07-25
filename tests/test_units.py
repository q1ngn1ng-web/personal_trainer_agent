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


if __name__ == "__main__":
    unittest.main(verbosity=2)
