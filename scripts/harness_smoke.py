"""Smoke-test the harness queries against the seed data.

Usage::

    DB_PATH=./data/test_seed.db uv run python scripts/harness_smoke.py

Calls :func:`seed_test_data.seed` programmatically (so the script is
self-contained) then exercises the harness queries exposed by
``src/db/queries.py``. Prints every query result and asserts minimum
row counts so a future regression fails loudly.

Cleaned-up test DB rows can be re-seeded by re-running the script — it
wipes its own tables.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Force DB override BEFORE any import.
os.environ.setdefault("DB_PATH", "./data/test_seed.db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.queries import (  # noqa: E402
    get_avg_latency_by_model,
    get_calls_by_prompt_version,
    get_calls_by_purpose,
    get_daily_logs_in_range,
    get_reviews_by_training,
    get_success_rate_by_prompt_version,
)
from scripts.seed_test_data import seed  # noqa: E402

logger = logging.getLogger("scripts.harness_smoke")


class Check:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def run(self, label: str, func) -> None:
        try:
            func()
        except AssertionError as exc:
            self.results.append((label, False, f"assert: {exc}"))
            logger.error("[FAIL] %s — %s", label, exc)
        except Exception as exc:
            self.results.append((label, False, f"{type(exc).__name__}: {exc}"))
            logger.error("[FAIL] %s — %s: %s", label, type(exc).__name__, exc)
        else:
            self.results.append((label, True, ""))
            logger.info("[OK]   %s", label)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    db_path = os.environ["DB_PATH"]
    summary = seed(db_path)
    logger.info("seed summary: %s", summary.render())

    checks = Check()

    # --- 1: get_calls_by_purpose(topic_validation) -------------------
    def chk_calls_by_purpose() -> None:
        calls = get_calls_by_purpose("topic_validation")
        assert calls, f"no calls for topic_validation: {calls}"
        logger.info(
            "topic_validation rows: %d (first model=%s v=%s)",
            len(calls),
            calls[0].model,
            calls[0].prompt_version,
        )

    checks.run("get_calls_by_purpose(topic_validation) returns rows", chk_calls_by_purpose)

    # --- 2: get_calls_by_prompt_version("topic_validation", "v1.0.0")
    def chk_calls_by_version() -> None:
        rows = get_calls_by_prompt_version("topic_validation", "v1.0.0")
        assert rows, "no rows for (topic_validation, v1.0.0)"
        logger.info(
            "(topic_validation, v1.0.0) rows: %d",
            len(rows),
        )

    checks.run(
        "get_calls_by_prompt_version('topic_validation', 'v1.0.0') returns rows",
        chk_calls_by_version,
    )

    # --- 3: get_success_rate_by_prompt_version ----------------------
    def chk_success_rates() -> None:
        rates: dict[str, dict[str, float]] = get_success_rate_by_prompt_version()
        print()
        print("success rate by prompt version:")
        print(json.dumps(rates, ensure_ascii=False, indent=2, default=str))
        # At least one (prompt_name, version) pair must be present.
        all_keys = [
            (name, version)
            for name, versions in rates.items()
            for version in versions
        ]
        assert all_keys, f"no prompt-version keys in result: {all_keys}"

    checks.run("get_success_rate_by_prompt_version returns keys", chk_success_rates)

    # --- 4: get_avg_latency_by_model ---------------------------------
    def chk_latency() -> None:
        latency: dict[str, float] = get_avg_latency_by_model()
        print()
        print("avg latency by model:")
        print(json.dumps(latency, ensure_ascii=False, indent=2, default=str))
        # The seed data uses 'deepseek-chat' — assert at least one model
        assert latency, "empty latency dict"

    checks.run("get_avg_latency_by_model returns rows", chk_latency)

    # --- 5: get_reviews_by_training(1) returns 2 rows ----------------
    def chk_reviews() -> None:
        rows = get_reviews_by_training(1)
        assert len(rows) == 2, f"expected 2 reviews, got {len(rows)}"
        actions = {r.user_action for r in rows}
        assert actions == {"confirmed", "skipped"}, f"actions={actions}"
        logger.info("training 1 reviews: actions=%s", sorted(actions))

    checks.run("get_reviews_by_training(1) returns 2 rows", chk_reviews)

    # --- 6: get_daily_logs_in_range(1, ...) returns >=5 rows ---------
    def chk_logs_range() -> None:
        # Use a generous range so the assertion holds regardless of calendar
        from datetime import date, timedelta

        today = date.today()
        start = today - timedelta(days=20)
        end = today + timedelta(days=1)
        rows = get_daily_logs_in_range(1, start, end)
        assert len(rows) >= 5, f"expected >=5 logs for training 1, got {len(rows)}"
        logger.info("training 1 logs in window: %d", len(rows))

    checks.run("get_daily_logs_in_range returns >=5 rows", chk_logs_range)

    # --- Summary -----------------------------------------------------
    print()
    print("=" * 60)
    ok = sum(1 for _, passed, _ in checks.results if passed)
    total = len(checks.results)
    for label, passed, detail in checks.results:
        mark = "✅" if passed else "❌"
        suffix = f" — {detail}" if detail else ""
        print(f"{mark} {label}{suffix}")
    print("=" * 60)
    print(f"harness smoke summary: {ok}/{total} passed")

    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
