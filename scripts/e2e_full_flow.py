"""End-to-end smoke test that walks the full trainer flow with no real LLM.

Usage::

    DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py

The script forces all LLM calls onto their fallback paths
(``DEEPSEEK_API_KEY=""``) so it is safe to run without API credentials. It
seeds a temporary SQLite database, creates one training, fabricates a few
days of daily logs, then runs ``prepare_weekly_review`` + ``apply_weekly_review``
and verifies every persistence side-effect.

On success the script prints a per-check summary and exits 0. On any
assertion failure it prints the actual vs. expected values and exits 1.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Environment setup — must happen BEFORE importing anything that reads env.
# ---------------------------------------------------------------------------
os.environ.setdefault("DB_PATH", "./data/test_e2e.db")
os.environ["DEEPSEEK_API_KEY"] = ""  # force LLM fallback paths
os.environ["DEEPSEEK_BASE_URL"] = "http://localhost:1"  # belt-and-braces

# Make ``src.*`` importable when this script is run from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.sqlite import init_db  # noqa: E402
from src.db.queries import (  # noqa: E402
    get_calls_by_purpose,
    get_daily_logs_in_range,
    get_or_create_daily_log,
    submit_three_reflections,
    update_daily_log_progress,
)
from src.services.calibration_service import CalibrationSuggestion  # noqa: E402
from src.services.metrics_calculator import compute_weekly_metrics  # noqa: E402
from src.services.review_service import (  # noqa: E402
    apply_weekly_review,
    prepare_weekly_review,
)
from src.services.schedule_service import extract_today_tasks  # noqa: E402
from src.services.trainer_service import create_training  # noqa: E402

logger = logging.getLogger("scripts.e2e_full_flow")

ALLOWED_PURPOSES = {
    "topic_validation",
    "keyword_generation",
    "baseline_q",
    "baseline_scoring",
    "weekly_calibration",
    "md_generation",
    "pretrain_checklist",
}


class Check:
    """Tiny pass/fail accumulator so we can print a summary at the end."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def run(self, label: str, func) -> None:
        try:
            func()
        except AssertionError as exc:
            self.results.append((label, False, f"assert: {exc}"))
            logger.error("[FAIL] %s — %s", label, exc)
        except Exception as exc:  # pragma: no cover - defensive
            self.results.append((label, False, f"{type(exc).__name__}: {exc}"))
            logger.error("[FAIL] %s — %s: %s", label, type(exc).__name__, exc)
            logger.debug("%s", traceback.format_exc())
        else:
            self.results.append((label, True, ""))
            logger.info("[OK]   %s", label)


def _die(msg: str) -> "None":
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def _baseline_answers() -> list[str]:
    """Three substantive answers that pass the heuristic mastery check.

    The fallback baseline questions are fixed Chinese strings. The scoring
    heuristic tokenises both the question and the user answer on whitespace
    and then looks for an exact overlap of tokens longer than 2 characters.
    To make every answer look ``mastered`` we keep the literal question
    fragments intact as whitespace-bounded tokens.
    """
    return [
        (
            "请用自己的话解释这个训练主题的核心概念是什么 这是 Python asyncio "
            "事件循环与协程 它要解决什么问题 是把同步阻塞 I/O 切换为协作式异步 I/O"
        ),
        (
            "该主题最关键的 3 个知识点是 async/await asyncio.gather aiohttp.ClientSession "
            "个知识点是什么 与 它们之间的联系与边界是什么 是同 event loop 调度"
        ),
        (
            "请给出一个能体现你对该主题整体掌握的实战场景或小例子 "
            "用 aiohttp + asyncio.Semaphore 并发抓 100 个 URL"
        ),
    ]


def _cleanup(workspace_root: Path, db_path: Path) -> None:
    # Remove any training_* subdirectory the script may have created.
    if workspace_root.exists():
        for child in workspace_root.iterdir():
            if child.name.startswith("training_"):
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                except OSError as exc:  # pragma: no cover - defensive
                    logger.warning("failed removing %s: %s", child, exc)
        # Remove the workspace_root itself when empty so we don't leak dirs.
        try:
            if workspace_root.exists() and not any(workspace_root.iterdir()):
                workspace_root.rmdir()
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("failed removing workspace_root %s: %s", workspace_root, exc)

    # Remove the test SQLite DB plus its WAL/SHM sidecars.
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = db_path.with_name(db_path.name + suffix)
        if candidate.exists():
            try:
                candidate.unlink()
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("failed removing %s: %s", candidate, exc)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    workspace_root = PROJECT_ROOT / "data" / "trainings_e2e"
    workspace_root.mkdir(parents=True, exist_ok=True)
    db_path = (PROJECT_ROOT / os.environ["DB_PATH"]).resolve()

    cleanup_done = False
    try:
        if db_path.exists():
            db_path.unlink()
        init_db(str(db_path))
        logger.info("using DB: %s", db_path)

        checks = Check()

        # --- Step 1: create_training ----------------------------------
        topic = "Python asyncio/aiohttp 概念与实战"
        answers = _baseline_answers()

        training = create_training(
            topic=topic,
            training_root=str(workspace_root),
            baseline_answers=answers,
            daily_minutes=60,
            total_weeks=6,
        )

        def chk_create() -> None:
            assert training.id is not None and training.id > 0, f"id={training.id!r}"
            assert training.directory.exists(), f"dir missing: {training.directory}"
            assert training.baseline_level.value != "low", (
                f"baseline_level={training.baseline_level!r} (expected != low)"
            )

        checks.run("create_training returns populated Training", chk_create)

        # Snapshot training_id for later checks
        training_id = int(training.id)
        training_dir = training.directory

        # --- Step 2: all 10 md files exist -----------------------------
        expected_files = [
            "00_对象档案.md",
            "01_基线诊断.md",
            "02_训练目标.md",
            "03_资料库.md",
            "04_复习日历.md",
            "05_主动回忆题.md",
            "06_环境配置.md",
            "07_奖励机制.md",
            "08_每日反省.md",
            "09_边界与止.md",
        ]

        def chk_files_exist() -> None:
            sizes: dict[str, int] = {}
            for name in expected_files:
                p = training_dir / name
                assert p.exists() and p.is_file(), f"missing {p}"
                sizes[name] = p.stat().st_size
            for name, size in sizes.items():
                if size == 0:
                    raise AssertionError(f"{name} is empty")
            logger.info("training files: %s", json.dumps(sizes, ensure_ascii=False))

        checks.run("10 md files exist and are non-empty", chk_files_exist)

        # --- Step 3: 01_基线诊断.md contains expected keywords --------
        baseline_md = (training_dir / "01_基线诊断.md").read_text(encoding="utf-8")

        def chk_baseline_keywords() -> None:
            for needle in ("前置拷问", "基线"):
                if needle not in baseline_md:
                    raise AssertionError(f"missing keyword {needle!r}")
            logger.info(
                "01_基线诊断.md first 80 chars: %r",
                baseline_md.splitlines()[0][:80] if baseline_md else "",
            )

        checks.run("01_基线诊断.md contains 前置拷问/基线 keywords", chk_baseline_keywords)

        # --- Step 4: 3 days of fake daily logs -------------------------
        today = date.today()

        def chk_three_days() -> None:
            for offset in (0, 1, 2):
                log_date = today - timedelta(days=offset)
                log = get_or_create_daily_log(training_id, log_date)
                update_daily_log_progress(
                    log.id,
                    completed_count=2,
                    total_tasks=3,
                    recall_correct=2,
                    recall_total=3,
                )
                submit_three_reflections(
                    log.id,
                    {
                        "loyal_to_goal": "yes",
                        "method_effective": "ok",
                        "applied_to_practice": "ok",
                    },
                )
            logs = get_daily_logs_in_range(
                training_id, today - timedelta(days=6), today
            )
            assert len(logs) >= 3, f"expected >=3 logs, got {len(logs)}"
            logger.info("inserted %d daily logs", len(logs))

        checks.run("insert 3 days of daily_logs", chk_three_days)

        # --- Step 5: extract_today_tasks returns non-empty list -------
        def chk_today_tasks() -> None:
            result = extract_today_tasks(training_id)
            review = list(result.review_items)
            new = list(result.new_items)
            assert len(review) + len(new) > 0, (
                f"empty today tasks: review={review} new={new}"
            )
            logger.info(
                "today tasks: %d review + %d new = %d total",
                len(review),
                len(new),
                len(review) + len(new),
            )

        checks.run("extract_today_tasks returns non-empty list", chk_today_tasks)

        # --- Step 6: compute_weekly_metrics returns 7+ fields ---------
        def chk_metrics() -> None:
            metrics = compute_weekly_metrics(training_id)
            assert dataclasses.is_dataclass(metrics), "not a dataclass"
            fields = {f.name for f in dataclasses.fields(metrics)}
            expected = {
                "avg_completion",
                "avg_recall_success",
                "three_reflection_coverage",
                "consecutive_days",
                "weakest_topic",
                "strongest_topic",
                "missed_tasks",
            }
            missing = expected - fields
            assert not missing, f"missing WeeklyMetrics fields: {missing}"
            logger.info(
                "weekly metrics: %s",
                json.dumps(metrics.to_plain_dict(), ensure_ascii=False, default=str),
            )

        checks.run("compute_weekly_metrics returns 7 fields", chk_metrics)

        # --- Step 7: prepare_weekly_review returns CalibrationSuggestion
        def chk_prepare() -> None:
            outcome = prepare_weekly_review(training_id)
            assert isinstance(outcome.suggestion, CalibrationSuggestion), (
                f"suggestion is {type(outcome.suggestion).__name__}"
            )
            logger.info(
                "prepare: applied=%s delta=%s fallback=%s",
                outcome.applied,
                outcome.suggestion.baseline_score_delta,
                outcome.suggestion.fallback_used,
            )

        checks.run("prepare_weekly_review returns CalibrationSuggestion", chk_prepare)

        # --- Step 8: apply_weekly_review --------------------------------
        week_before = None
        with open(training_dir / "00_对象档案.md", "r", encoding="utf-8") as fh:
            week_before = None  # not parsed; we just check DB state below

        def chk_apply() -> None:
            outcome_prepare = prepare_weekly_review(training_id)
            outcome_apply = apply_weekly_review(training_id, outcome_prepare.suggestion)
            assert outcome_apply.applied is True, (
                f"applied={outcome_apply.applied!r}"
            )
            logger.info("apply: applied=%s", outcome_apply.applied)

        checks.run("apply_weekly_review sets applied=True", chk_apply)

        # --- Step 9: verify DB side effects -----------------------------
        from src.db.queries import get_training, get_reviews_by_training  # local import
        from src.db.sqlite import get_connection

        def chk_state_changes() -> None:
            row = get_training(training_id)
            assert row is not None, "training missing"
            assert int(row.current_week or 0) >= 2, (
                f"current_week={row.current_week!r} (expected >=2)"
            )
            assert row.last_review_at, f"last_review_at={row.last_review_at!r}"
            conn = get_connection(str(db_path))
            try:
                history_count = conn.execute(
                    "SELECT COUNT(*) FROM baseline_history WHERE training_id = ?",
                    (training_id,),
                ).fetchone()[0]
            finally:
                conn.close()
            assert history_count >= 2, (
                f"baseline_history rows={history_count} (expected >=2)"
            )
            reviews = get_reviews_by_training(training_id)
            confirmed = [r for r in reviews if r.user_action == "confirmed"]
            assert confirmed, (
                f"no review_archives with user_action='confirmed' (got {len(reviews)})"
            )
            logger.info(
                "after apply: week=%s last_review_at=%s history=%d reviews=%d",
                row.current_week,
                row.last_review_at,
                history_count,
                len(reviews),
            )

        checks.run(
            "trainings.current_week/last_review_at + baseline_history + review_archives populated",
            chk_state_changes,
        )

        # --- Step 10: llm_calls integrity ------------------------------
        def chk_llm_calls() -> None:
            conn = get_connection(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT call_purpose, prompt_version FROM llm_calls"
                ).fetchall()
            finally:
                conn.close()
            purposes = {r["call_purpose"] for r in rows}
            required = {"topic_validation", "keyword_generation", "baseline_q", "baseline_scoring"}
            missing = required - purposes
            assert not missing, (
                f"missing required call_purpose rows: {missing}; got {purposes}"
            )
            bad_version = [
                (r["call_purpose"], r["prompt_version"])
                for r in rows
                if not r["prompt_version"]
            ]
            assert not bad_version, f"empty prompt_version: {bad_version}"
            logger.info("llm_calls purposes observed: %s", sorted(purposes))

        checks.run("llm_calls rows for required call_purpose values", chk_llm_calls)

        # --- Step 11: get_calls_by_purpose smoke ------------------------
        def chk_calls_by_purpose() -> None:
            for purpose in ("topic_validation", "keyword_generation", "baseline_q", "baseline_scoring"):
                calls = get_calls_by_purpose(purpose)
                assert calls, f"no llm_calls for {purpose}"
            logger.info(
                "per-purpose counts: %s",
                json.dumps(
                    {
                        p: len(get_calls_by_purpose(p))
                        for p in ("topic_validation", "keyword_generation", "baseline_q", "baseline_scoring")
                    }
                ),
            )

        checks.run("harness get_calls_by_purpose returns rows", chk_calls_by_purpose)

        # --- Summary --------------------------------------------------
        print()
        print("=" * 60)
        ok = sum(1 for _, passed, _ in checks.results if passed)
        total = len(checks.results)
        for label, passed, detail in checks.results:
            mark = "✅" if passed else "❌"
            suffix = f" — {detail}" if detail else ""
            print(f"{mark} {label}{suffix}")
        print("=" * 60)
        print(f"e2e summary: {ok}/{total} passed")

        if ok != total:
            return 1
        return 0

    finally:
        if not cleanup_done:
            try:
                _cleanup(workspace_root, db_path)
                logger.info("cleaned up %s and %s", workspace_root, db_path)
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.exception("cleanup failed")


if __name__ == "__main__":
    raise SystemExit(main())
