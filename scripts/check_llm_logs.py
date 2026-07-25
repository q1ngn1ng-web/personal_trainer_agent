"""Integrity check for the ``llm_calls`` table.

Usage::

    DB_PATH=./data/trainer.db uv run python scripts/check_llm_logs.py

Reads every row in ``llm_calls`` and validates the schema invariants:

* ``prompt_version`` is non-null and non-empty
* ``call_purpose`` is in the allowed enum
* ``latency_ms``, ``tokens_in``, ``tokens_out`` are non-negative integers

Prints a per-``call_purpose`` count table at the end. Exits 0 on success,
1 if any row fails the invariants (the failing rows are printed first).

This script is read-only — it does not modify the DB.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.sqlite import get_connection  # noqa: E402

logger = logging.getLogger("scripts.check_llm_logs")

ALLOWED_PURPOSES = {
    "topic_validation",
    "keyword_generation",
    "baseline_q",
    "baseline_scoring",
    "weekly_calibration",
    "md_generation",
    "pretrain_checklist",
}


def _fetch_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, training_id, call_purpose, prompt_name, prompt_version, "
            "model, input_text, output_text, output_json, validation_result, "
            "retry_count, latency_ms, tokens_in, tokens_out, failure_reason, "
            "fallback_used, created_at FROM llm_calls"
        ).fetchall()
    )


def _print_summary(by_purpose: dict[str, int], total: int) -> None:
    print()
    print("=" * 50)
    print(f"llm_calls integrity check — {total} row(s) total")
    print("=" * 50)
    if total == 0:
        print("(no rows in llm_calls)")
        return
    width = max((len(p) for p in by_purpose.keys()), default=10)
    print(f"{'call_purpose'.ljust(width)}  count")
    print(f"{'-' * width}  -----")
    for purpose in sorted(by_purpose):
        print(f"{purpose.ljust(width)}  {by_purpose[purpose]:>5}")
    print()
    print(f"Total: {total} rows across {len(by_purpose)} call_purpose value(s)")
    if by_purpose.keys() - ALLOWED_PURPOSES:
        # Tolerate non-canonical purposes defensively (don't fail the script)
        extras = sorted(by_purpose.keys() - ALLOWED_PURPOSES)
        print(f"WARNING: unexpected call_purpose values: {extras}")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    db_path = os.environ.get("DB_PATH", "./data/trainer.db")
    logger.info("checking llm_calls in DB: %s", db_path)

    # If the DB does not yet exist, init it (we're a smoke script — don't fail
    # just because the user hasn't run the app).
    if not Path(db_path).exists():
        logger.info("DB %s does not exist yet — initialising empty schema", db_path)
        from src.db.sqlite import init_db

        init_db(db_path)

    conn = get_connection(db_path)
    try:
        rows = _fetch_all(conn)
    finally:
        conn.close()

    failures: list[tuple[int, str]] = []
    by_purpose: dict[str, int] = defaultdict(int)

    for row in rows:
        row_id = int(row["id"] or 0)
        purpose = str(row["call_purpose"] or "")
        version = str(row["prompt_version"] or "")
        latency = row["latency_ms"]
        tokens_in = row["tokens_in"]
        tokens_out = row["tokens_out"]

        by_purpose[purpose] += 1

        if not version:
            failures.append((row_id, f"empty prompt_version: {version!r}"))

        if purpose not in ALLOWED_PURPOSES:
            failures.append((row_id, f"unknown call_purpose: {purpose!r}"))

        if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
            failures.append((row_id, f"invalid latency_ms: {latency!r}"))
        if not isinstance(tokens_in, int) or isinstance(tokens_in, bool) or tokens_in < 0:
            failures.append((row_id, f"invalid tokens_in: {tokens_in!r}"))
        if not isinstance(tokens_out, int) or isinstance(tokens_out, bool) or tokens_out < 0:
            failures.append((row_id, f"invalid tokens_out: {tokens_out!r}"))

    total = sum(by_purpose.values())
    _print_summary(by_purpose, total)

    if failures:
        print()
        print(f"❌ {len(failures)} integrity failure(s):")
        for row_id, reason in failures:
            print(f"  row id={row_id}: {reason}")
        return 1

    print("✅ all rows pass integrity checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
