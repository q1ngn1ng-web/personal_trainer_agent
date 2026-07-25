"""Seed a temporary SQLite DB with realistic-looking trainer data.

Usage::

    DB_PATH=./data/test_seed.db uv run python scripts/seed_test_data.py

Produces:

* 2 trainings — one ``active`` (Python asyncio) and one ``paused`` (Piano)
* 5 ``daily_logs`` with mixed completion / recall / reflection profiles
* 3 ``baseline_history`` rows showing a 1.5 → 2.5 baseline progression
* 2 ``review_archives`` (one ``confirmed``, one ``skipped``)
* 4 ``llm_calls`` rows covering different ``call_purpose`` and
  ``prompt_version`` values (incl. one "older" v0.9.0 version row to make
  per-version filtering non-trivial)

The script is idempotent: if ``DB_PATH`` already points to an initialised DB
the rows are wiped first. It does NOT call real LLMs — the fake ``llm_calls``
rows mirror the schema contract from ``src/llm/prompts.py``.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Force DB override BEFORE any import that might touch the env path.
os.environ.setdefault("DB_PATH", "./data/test_seed.db")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.sqlite import get_connection, init_db  # noqa: E402

logger = logging.getLogger("scripts.seed_test_data")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SeedSummary:
    trainings: int = 0
    daily_logs: int = 0
    baseline_history: int = 0
    review_archives: int = 0
    llm_calls: int = 0

    def render(self) -> str:
        return json.dumps(
            {
                "trainings": self.trainings,
                "daily_logs": self.daily_logs,
                "baseline_history": self.baseline_history,
                "review_archives": self.review_archives,
                "llm_calls": self.llm_calls,
            },
            ensure_ascii=False,
            indent=2,
        )


def _reset_db(conn: sqlite3.Connection) -> None:
    """Wipe every business table so the seed run is deterministic."""
    conn.execute("DELETE FROM daily_log_tasks")
    conn.execute("DELETE FROM daily_logs")
    conn.execute("DELETE FROM baseline_history")
    conn.execute("DELETE FROM review_archives")
    conn.execute("DELETE FROM llm_calls")
    conn.execute("DELETE FROM trainings")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('trainings','daily_logs','baseline_history','review_archives','llm_calls','daily_log_tasks')")


def _insert_training(
    conn: sqlite3.Connection,
    *,
    topic: str,
    status: str,
    baseline_score: float,
    baseline_level: str,
    current_week: int,
    last_active_at: str,
    created_at: str,
    last_review_at: str | None = None,
    directory: str | None = None,
    schedule: dict[str, Any] | None = None,
    materials: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO trainings
           (topic, status, keywords, must_cover_count, forbidden, directory,
            baseline_score, baseline_level, targets, review_items,
            pretrain_checklist, schedule, materials, current_week,
            last_review_at, created_at, last_active_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            topic,
            status,
            json.dumps(["kw1", "kw2"], ensure_ascii=False),
            2,
            json.dumps([], ensure_ascii=False),
            directory,
            baseline_score,
            baseline_level,
            json.dumps({"end_goal": f"end goal of {topic}"}, ensure_ascii=False),
            json.dumps(["partial-topic-1"], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            json.dumps(schedule or {}, ensure_ascii=False),
            json.dumps(materials or {}, ensure_ascii=False),
            current_week,
            last_review_at,
            created_at,
            last_active_at,
        ),
    )
    if cur.lastrowid is None:  # pragma: no cover - sqlite invariant
        raise RuntimeError("INSERT trainings did not return an id")
    return int(cur.lastrowid)


def _insert_daily_log(
    conn: sqlite3.Connection,
    *,
    training_id: int,
    log_date: date,
    completed_count: int,
    total_tasks: int,
    recall_correct: int,
    recall_total: int,
    reflections: dict[str, str] | None,
) -> int:
    rate = (recall_correct / recall_total) if recall_total else None
    submitted = _now_iso() if reflections else None
    cur = conn.execute(
        """INSERT INTO daily_logs
           (training_id, log_date, total_tasks, completed_count,
            recall_questions_total, recall_questions_correct, recall_success_rate,
            three_reflections, reflection_submitted_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            training_id,
            log_date.isoformat(),
            total_tasks,
            completed_count,
            recall_total,
            recall_correct,
            rate,
            json.dumps(reflections, ensure_ascii=False) if reflections else None,
            submitted,
            _now_iso(),
        ),
    )
    if cur.lastrowid is None:  # pragma: no cover - sqlite invariant
        raise RuntimeError("INSERT daily_logs did not return an id")
    return int(cur.lastrowid)


def _insert_baseline_history(
    conn: sqlite3.Connection,
    *,
    training_id: int,
    score: float,
    dimension_scores: dict[str, Any],
) -> int:
    cur = conn.execute(
        """INSERT INTO baseline_history
           (training_id, baseline_score, dimension_scores, recorded_at)
           VALUES (?, ?, ?, ?)""",
        (
            training_id,
            score,
            json.dumps(dimension_scores, ensure_ascii=False),
            _now_iso(),
        ),
    )
    return int(cur.lastrowid or 0)


def _insert_review_archive(
    conn: sqlite3.Connection,
    *,
    training_id: int,
    week_start: date,
    metrics: dict[str, Any],
    llm_suggestions: dict[str, Any],
    user_action: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO review_archives
           (training_id, week_start, metrics, llm_suggestions, user_action, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            training_id,
            week_start.isoformat(),
            json.dumps(metrics, ensure_ascii=False, default=str),
            json.dumps(llm_suggestions, ensure_ascii=False, default=str),
            user_action,
            _now_iso(),
        ),
    )
    return int(cur.lastrowid or 0)


def _insert_llm_call(
    conn: sqlite3.Connection,
    *,
    call_purpose: str,
    prompt_name: str,
    prompt_version: str,
    model: str,
    input_text: str,
    output_text: str | None,
    output_json: dict[str, Any] | None,
    validation_result: str,
    latency_ms: int,
    tokens_in: int,
    tokens_out: int,
    training_id: int | None = None,
    retry_count: int = 0,
    fallback_used: int = 0,
    failure_reason: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO llm_calls
           (training_id, call_purpose, prompt_name, prompt_version, model,
            input_text, output_text, output_json, validation_result,
            retry_count, latency_ms, tokens_in, tokens_out,
            failure_reason, fallback_used, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            training_id,
            call_purpose,
            prompt_name,
            prompt_version,
            model,
            input_text,
            output_text,
            json.dumps(output_json, ensure_ascii=False) if output_json else None,
            validation_result,
            retry_count,
            latency_ms,
            tokens_in,
            tokens_out,
            failure_reason,
            fallback_used,
            _now_iso(),
        ),
    )
    return int(cur.lastrowid or 0)


def seed(db_path: str = os.environ["DB_PATH"]) -> SeedSummary:
    """(Re-)create the seed DB and insert deterministic fake data."""
    init_db(db_path)
    conn = get_connection(db_path)
    summary = SeedSummary()

    try:
        _reset_db(conn)
        conn.commit()

        today = date.today()

        # ------------------------------------------------------------------
        # Trainings
        # ------------------------------------------------------------------
        active_id = _insert_training(
            conn,
            topic="Python asyncio/aiohttp 概念与实战",
            status="active",
            baseline_score=3.0,
            baseline_level="mid",
            current_week=3,
            last_active_at=_now_iso(),
            last_review_at=(today - timedelta(days=2)).isoformat(),
            created_at=(today - timedelta(days=20)).isoformat() + "T00:00:00+00:00",
            directory="training_Python_asyncio_aiohttp",
            schedule={
                "schedule_template": [
                    {"slot": "早", "task": "回忆题", "duration": "10 min", "source": "05_主动回忆题.md"}
                ],
                "intervals": [1, 3, 7, 15, 30],
            },
            materials={
                "universal_materials": [
                    {"name": "《asyncio 实战》", "type": "书", "difficulty": "⭐⭐", "hours": "20 h"}
                ],
                "specialized_materials": [
                    {"name": "Python 官方 asyncio 文档", "type": "文章", "difficulty": "⭐⭐"}
                ],
            },
        )
        paused_id = _insert_training(
            conn,
            topic="钢琴基础入门",
            status="paused",
            baseline_score=1.5,
            baseline_level="low",
            current_week=1,
            last_active_at=(today - timedelta(days=10)).isoformat() + "T00:00:00+00:00",
            created_at=(today - timedelta(days=12)).isoformat() + "T00:00:00+00:00",
            directory="training_piano_basics",
        )
        summary.trainings = 2
        logger.info("seeded trainings: active_id=%s paused_id=%s", active_id, paused_id)

        # ------------------------------------------------------------------
        # Daily logs (5 of them, varying completion)
        # ------------------------------------------------------------------
        log_specs = [
            (0, 5, 5, 5, 5, {"loyal_to_goal": "yes", "method_effective": "ok", "applied_to_practice": "ok"}),  # perfect
            (1, 4, 5, 4, 5, {"loyal_to_goal": "yes", "method_effective": "ok", "applied_to_practice": "ok"}),
            (2, 3, 4, 2, 4, {"loyal_to_goal": "ok", "method_effective": "ok", "applied_to_practice": "ok"}),
            (3, 2, 5, 3, 5, None),  # no reflections
            (4, 0, 3, 0, 2, None),  # most empty
        ]
        for offset, total, completed, recall_total, recall_correct, reflections in log_specs:
            _insert_daily_log(
                conn,
                training_id=active_id,
                log_date=today - timedelta(days=offset),
                completed_count=completed,
                total_tasks=total,
                recall_correct=recall_correct,
                recall_total=recall_total,
                reflections=reflections,
            )
            summary.daily_logs += 1

        # Paused training also gets 1 sparse log to avoid empty windows
        _insert_daily_log(
            conn,
            training_id=paused_id,
            log_date=today - timedelta(days=10),
            completed_count=1,
            total_tasks=3,
            recall_correct=1,
            recall_total=2,
            reflections=None,
        )
        summary.daily_logs += 1

        # ------------------------------------------------------------------
        # Baseline history (1.5 → 2.0 → 2.5 over three weeks)
        # ------------------------------------------------------------------
        for idx, score in enumerate([1.5, 2.0, 2.5]):
            _insert_baseline_history(
                conn,
                training_id=active_id,
                score=score,
                dimension_scores={
                    "scores": [
                        {"idx": i, "score": "mastered" if i % 2 == 0 else "partial", "notes": ""}
                        for i in range(3)
                    ],
                    "overall_level": "mid" if score >= 2.5 else "low",
                },
            )
            summary.baseline_history += 1

        # ------------------------------------------------------------------
        # Review archives (1 confirmed, 1 skipped)
        # ------------------------------------------------------------------
        _insert_review_archive(
            conn,
            training_id=active_id,
            week_start=today - timedelta(days=14),
            metrics={
                "training_id": active_id,
                "week_start": (today - timedelta(days=14)).isoformat(),
                "week_end": (today - timedelta(days=8)).isoformat(),
                "avg_completion": 0.7,
                "avg_recall_success": 0.8,
                "three_reflection_coverage": 0.5,
                "consecutive_days": 3,
                "missed_tasks": [],
                "days_logged": 5,
            },
            llm_suggestions={
                "source": "heuristic_fallback",
                "delta_seed": 0.8,
            },
            user_action="confirmed",
        )
        summary.review_archives += 1

        _insert_review_archive(
            conn,
            training_id=active_id,
            week_start=today - timedelta(days=7),
            metrics={
                "training_id": active_id,
                "week_start": (today - timedelta(days=7)).isoformat(),
                "week_end": today.isoformat(),
                "avg_completion": 0.6,
                "avg_recall_success": 0.7,
                "three_reflection_coverage": 0.4,
                "consecutive_days": 2,
                "missed_tasks": [],
                "days_logged": 4,
            },
            llm_suggestions={
                "source": "heuristic_fallback",
                "delta_seed": 0.7,
            },
            user_action="skipped",
        )
        summary.review_archives += 1

        # ------------------------------------------------------------------
        # LLM calls — 4 rows, different purposes + an older prompt version
        # ------------------------------------------------------------------
        fake_input = json.dumps(
            {"topic": "Python asyncio", "stub": True}, ensure_ascii=False
        )
        _insert_llm_call(
            conn,
            call_purpose="topic_validation",
            prompt_name="topic_validation",
            prompt_version="v1.0.0",
            model="deepseek-chat",
            input_text=fake_input,
            output_text='{"is_valid": true}',
            output_json={"is_valid": True},
            validation_result="pass",
            latency_ms=320,
            tokens_in=128,
            tokens_out=24,
            training_id=active_id,
        )
        summary.llm_calls += 1

        _insert_llm_call(
            conn,
            call_purpose="baseline_q",
            prompt_name="baseline_q",
            prompt_version="v1.0.0",
            model="deepseek-chat",
            input_text=fake_input,
            output_text='{"questions": []}',
            output_json={"questions": []},
            validation_result="pass",
            latency_ms=580,
            tokens_in=256,
            tokens_out=144,
            training_id=active_id,
        )
        summary.llm_calls += 1

        # An "older" version entry so get_calls_by_prompt_version can return two
        # different versions for the same prompt_name.
        _insert_llm_call(
            conn,
            call_purpose="weekly_calibration",
            prompt_name="weekly_calibration",
            prompt_version="v0.9.0",
            model="deepseek-chat",
            input_text=fake_input,
            output_text='{"baseline_score_delta": 0.0}',
            output_json={"baseline_score_delta": 0.0},
            validation_result="pass",
            latency_ms=420,
            tokens_in=180,
            tokens_out=60,
            training_id=active_id,
        )
        summary.llm_calls += 1

        _insert_llm_call(
            conn,
            call_purpose="weekly_calibration",
            prompt_name="weekly_calibration",
            prompt_version="v1.0.0",
            model="deepseek-chat",
            input_text=fake_input,
            output_text='{"baseline_score_delta": 0.1}',
            output_json={"baseline_score_delta": 0.1, "schedule_adjustment": {}, "material_recommendations": [], "reward_refresh": "", "next_week_focus": ""},
            validation_result="pass",
            latency_ms=410,
            tokens_in=190,
            tokens_out=64,
            training_id=active_id,
        )
        summary.llm_calls += 1

        conn.commit()
        return summary

    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    db_path = os.environ["DB_PATH"]
    summary = seed(db_path)
    print("\nSeed summary:")
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
