"""Time/cost benchmark for the grading and retrieval hot paths.

Usage::

    DB_PATH=./data/trainer.db uv run python scripts/benchmark_time_cost.py

Measures, without any LLM/API calls:

* rule-based grading latency (``grade_choice`` / ``grade_fill`` / ``score_points``),
  the deterministic path taken by objective questions — zero model calls;
* SQLite FTS5 (trigram) chunk search latency against the real database;
* LLM call latency/token profile aggregated from the ``llm_calls`` audit table
  (historical records, dev-phase data — use as an order-of-magnitude reference);
* question idempotency readiness: plan items that already carry a persisted
  question, i.e. rounds after the first open cost zero generation time.

Interpreting results: the rule-vs-LLM comparison is an order-of-magnitude
contrast (microseconds vs seconds). ``llm_calls`` rows are setup-phase dev
records, not a production sample — do not quote percentages from them.

This script is read-only — it opens the DB with ``mode=ro`` and writes nothing.
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.grading_service import (  # noqa: E402
    PointSpec,
    grade_choice,
    grade_fill,
    score_points,
)

DB_PATH = Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "trainer.db"))
BENCH_ITERATIONS = 10_000
FTS_QUERIES = ("持久化 RDB", "索引优化", "拥塞控制", "消息可靠性")
FTS_REPEATS = 20


def bench_rule_grading() -> list[tuple[str, float]]:
    """Time the three deterministic grading entry points, ms per call."""
    points = [
        PointSpec("p1", "触发时机", 1.0, True),
        PointSpec("p2", "重写流程", 1.0, False),
        PointSpec("p3", "数据安全性", 1.0, False),
    ]
    verdicts = {"p1": "hit", "p2": "partial", "p3": "missing"}
    cases = [
        (
            "grade_choice（选择题）",
            lambda: grade_choice(
                "A", correct_key="A", options=[{"key": "A", "text": "RDB 快照"}, {"key": "B", "text": "AOF 日志"}]
            ),
        ),
        ("grade_fill（填空题）", lambda: grade_fill("RDB", expected="RDB", accepted=["rdb 快照"])),
        ("score_points（主观题要点聚合）", lambda: score_points(points, verdicts)),
    ]
    rows: list[tuple[str, float]] = []
    for name, fn in cases:
        start = time.perf_counter()
        for _ in range(BENCH_ITERATIONS):
            fn()
        rows.append((name, 1000 * (time.perf_counter() - start) / BENCH_ITERATIONS))
    return rows


def bench_fts(conn: sqlite3.Connection) -> tuple[float, float, int]:
    """Time FTS5 searches on the real chunks index; return (p50, p95, hits)."""
    latencies: list[float] = []
    hits = 0
    for query in FTS_QUERIES:
        for _ in range(FTS_REPEATS):
            start = time.perf_counter()
            rows = conn.execute(
                "SELECT rowid FROM source_chunks_fts WHERE source_chunks_fts MATCH ? LIMIT 10",
                (query,),
            ).fetchall()
            latencies.append((time.perf_counter() - start) * 1000)
            hits = max(hits, len(rows))
    latencies.sort()
    return (
        statistics.median(latencies),
        latencies[int(0.95 * len(latencies)) - 1],
        hits,
    )


def llm_profile(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT call_purpose, COUNT(*) AS n, AVG(latency_ms) AS avg_ms, "
            "MIN(latency_ms) AS min_ms, MAX(latency_ms) AS max_ms, "
            "AVG(tokens_in + tokens_out) AS avg_tokens "
            "FROM llm_calls GROUP BY call_purpose ORDER BY avg_ms DESC"
        )
    )


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print(f"== 规则判分（确定性路径，零模型调用，N={BENCH_ITERATIONS}）==")
    for name, ms in bench_rule_grading():
        print(f"  {name:<24} {ms:.4f} ms/次")

    p50, p95, hits = bench_fts(conn)
    total = conn.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0]
    print(f"\n== FTS5 本地检索（真实库 {total} 条切片）==")
    print(f"  p50 {p50:.3f} ms / p95 {p95:.3f} ms（单查询最多 {hits} 命中）")

    print("\n== LLM 调用画像（llm_calls 历史记录，开发期数据，仅作量级参考）==")
    profile = llm_profile(conn)
    if not profile:
        print("  （无记录）")
    for row in profile:
        print(
            f"  {row['call_purpose']:<20} n={row['n']:<3} "
            f"平均 {row['avg_ms'] / 1000:.1f}s  范围 {row['min_ms'] / 1000:.1f}-{row['max_ms'] / 1000:.1f}s  "
            f"{row['avg_tokens']:.0f} tok/次"
        )

    ready = conn.execute(
        "SELECT COUNT(*) FROM plan_items WHERE question IS NOT NULL"
    ).fetchone()[0]
    total_items = conn.execute("SELECT COUNT(*) FROM training_items").fetchone()[0]
    print(f"\n== 题目幂等落库 ==")
    print(f"  已带题计划项 {ready} 个（首轮生成后，后续轮次打开零生成等待）；训练项共 {total_items} 个")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
