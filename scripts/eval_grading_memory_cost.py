"""Grading & learner-memory cost evaluation against an OpenAI-compatible endpoint.

Usage::

    DASHSCOPE_KEY_FILE=/home/ubuntu/py_code/PythonProject16/.env \
    EVAL_MODEL=deepseek-v4.1-flash \
    uv run python scripts/eval_grading_memory_cost.py

Env contract:

* ``DASHSCOPE_KEY_FILE`` — .env file providing ``DASHSCOPE_API_KEY`` /
  ``DASHSCOPE_BASE_URL`` (Alibaba Cloud free-quota endpoint). The key is read,
  never printed.
* ``EVAL_MODEL`` — model id billed against free quota (default ``deepseek-v4.1-flash``).
* ``EVAL_RUNS`` — repeats per arm (default 3).
* The Trainer LLM client reads ``DEEPSEEK_*`` at import time; this script sets
  those from the DashScope file BEFORE importing ``src.llm.client`` so the real
  project code path (``complete()``) runs against the free-quota endpoint.

What it measures (read-only; nothing is written to any database):

1. **Project-path grading**: ``complete("quiz_grade", ...)`` on a real stored
   question with its persisted point list — tokens, latency, verdict validity.
2. **Memory-injection delta**: the same rendered prompt with vs without the
   ``render_context`` learner-memory section appended — the intended memory
   injection, which is implemented + tested but not yet wired into the live
   grading path, so this quantifies what wiring it would cost per call.
3. **Memory storage/retrieval latency**: pure-SQL aggregations on the real DB
   (small sample) and on a seeded in-memory DB (300 attempts) — plus the
   ``render_context`` compression ratio (compact context vs naive raw history).
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- env wiring must happen BEFORE importing src.llm.client -----------------


def _load_dashscope_env() -> None:
    key_file = Path(
        os.environ.get(
            "DASHSCOPE_KEY_FILE",
            "/home/ubuntu/py_code/PythonProject16/.env",
        )
    )
    values: dict[str, str] = {}
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    api_key = values.get("DASHSCOPE_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = values.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY not found; set DASHSCOPE_KEY_FILE")
    os.environ["DEEPSEEK_API_KEY"] = api_key
    os.environ["DEEPSEEK_BASE_URL"] = base_url.rstrip("/")
    os.environ["DEEPSEEK_MODEL"] = os.environ.get("EVAL_MODEL", "deepseek-v4.1-flash")
    os.environ.setdefault(
        "DB_PATH", str(PROJECT_ROOT / "data" / "trainer.db")
    )


_load_dashscope_env()

from src.llm import client as llm_client  # noqa: E402
from src.services import memory_service as ms  # noqa: E402

DB_PATH = Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "trainer.db"))

RUNS = int(os.environ.get("EVAL_RUNS", "3"))
GRADER_MODEL = os.environ["DEEPSEEK_MODEL"]


def _open_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pick_case(conn: sqlite3.Connection) -> tuple[sqlite3.Row, dict]:
    """A real plan item carrying its persisted point list, plus its training id."""
    row = conn.execute(
        "SELECT id, training_id, item_key, question, reference_answer, points "
        "FROM plan_items WHERE points IS NOT NULL AND question IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise SystemExit("no plan_item with persisted points; run the 2026-10-26 chain first")
    from src.services.answer_service import _parse_points_json

    return row, _parse_points_json(row["points"])


def _grade_variables(row: sqlite3.Row, points: list[dict]) -> dict:
    payload = [
        {
            "item_key": str(row["item_key"]),
            "question": str(row["question"]),
            "reference_answer": str(row["reference_answer"] or ""),
            "answer": "RDB 是定时快照，AOF 是追加日志，所以持久化用 RDB 就够了，不需要 AOF。",
            "points": [
                {
                    "point_id": p["point_id"],
                    "text": p["text"],
                    "weight": p["weight"],
                    "is_required": p["is_required"],
                }
                for p in points
            ],
        }
    ]
    return {"items": json.dumps(payload, ensure_ascii=False, indent=2), "memory_block": ""}


def arm_a_project_path(variables: dict) -> list[dict]:
    rows = []
    for i in range(RUNS):
        result = llm_client.complete("quiz_grade", variables)
        output = result.get("output_json") or {}
        entries = output.get("results") or []
        verdicts = entries[0].get("point_verdicts") or [] if entries else []
        rows.append(
            {
                "run": i + 1,
                "tokens_in": result["tokens_in"],
                "tokens_out": result["tokens_out"],
                "latency_ms": result["latency_ms"],
                "points_judged": len(verdicts),
                "retries": result.get("retry_count", 0),
            }
        )
    return rows


def _direct_call(prompt_text: str) -> tuple[int, int, int, bool, str]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名严格的 JSON 生成助手。"
                "只能输出合法 JSON 对象，不要任何解释、markdown 围栏或前后缀文字。"
            ),
        },
        {"role": "user", "content": prompt_text},
    ]
    start = time.monotonic()
    content, tin, tout = llm_client._call_api(messages)
    latency = int((time.monotonic() - start) * 1000)
    schema = llm_client.SCHEMA_REGISTRY["quiz_grade"]
    valid, note = True, ""
    try:
        llm_client.parse_and_validate(content, schema)
    except Exception as exc:
        valid, note = False, str(exc).splitlines()[0][:120]
    return tin, tout, latency, valid, note


def arm_b_memory_delta(conn: sqlite3.Connection, row: sqlite3.Row, variables: dict) -> dict:
    template, _ = llm_client.PROMPT_REGISTRY["quiz_grade"]
    schema = llm_client.SCHEMA_REGISTRY["quiz_grade"]
    base_prompt = llm_client._render_prompt(
        template, {**variables, "schema": llm_client._schema_dump(schema)}
    )
    block = ms.grade_memory_block(
        int(row["training_id"]), str(row["item_key"]), conn=conn
    )
    injected_prompt = llm_client._render_prompt(
        template,
        {
            **variables,
            "schema": llm_client._schema_dump(schema),
            "memory_block": block,
        },
    )

    base_runs = [_direct_call(base_prompt) for _ in range(RUNS)]
    inj_runs = [_direct_call(injected_prompt) for _ in range(RUNS)]
    return {
        "ctx_block": block,
        "ctx_approx_tokens": ms._approx_tokens(block),
        "base": base_runs,
        "injected": inj_runs,
    }


def arm_c_production_path(row: sqlite3.Row) -> tuple[dict, dict]:
    """真实生产路径：answer_service._grade_answer（内含记忆注入与 Schema 重试）。

    通过替换 ``answer_service.complete`` 记录每次调用的 tokens/延迟与注入块；
    DB 用副本（DB_PATH 指向副本），真实库零写入。
    """
    from src.services import answer_service

    captured: dict[str, list] = {"blocks": [], "usage": []}
    orig_complete = answer_service.complete

    def spy(prompt_name, variables, **kwargs):  # noqa: ANN001, ANN003
        result = orig_complete(prompt_name, variables, **kwargs)
        captured["blocks"].append(str(variables.get("memory_block", "")))
        captured["usage"].append(
            {
                "tokens_in": result["tokens_in"],
                "tokens_out": result["tokens_out"],
                "latency_ms": result["latency_ms"],
                "retries": result.get("retry_count", 0),
            }
        )
        return result

    answer_service.complete = spy
    try:
        context = {
            "training_id": int(row["training_id"]),
            "item_key": str(row["item_key"]),
            "question": str(row["question"]),
            "reference_answer": str(row["reference_answer"] or ""),
            "points": row["points"],
        }
        outcome = answer_service._grade_answer(
            context,
            "RDB 是定时快照，AOF 是追加日志，所以持久化用 RDB 就够了，不需要 AOF。",
        )
    finally:
        answer_service.complete = orig_complete
    return outcome, captured


def _timed(fn, repeat: int = 200) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def real_db_sql_timings(conn: sqlite3.Connection, training_id: int) -> dict:
    return {
        "knowledge_profile": _timed(lambda: ms.knowledge_profile(training_id, conn=conn)),
        "mistake_reason_counts": _timed(lambda: ms.mistake_reason_counts(training_id, conn=conn)),
        "recent_mistake_notes": _timed(lambda: ms.recent_mistake_notes(training_id, conn=conn)),
        "recommended_type_mix": _timed(lambda: ms.recommended_type_mix(training_id, conn=conn)),
        "render_context": _timed(lambda: ms.render_context(training_id, conn=conn)),
    }


def seeded_db_demo() -> dict:
    rng = random.Random(42)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((PROJECT_ROOT / "src" / "db" / "tables.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO trainings (topic, status, created_at) VALUES (?, 'active', datetime('now'))",
        ("种子：记忆模块规模演示",),
    )
    training_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    reasons = list(ms.MISTAKE_REASON_LABELS.keys())
    types = ("choice", "fill", "qa")
    item_keys = []
    for kp in range(12):
        for qt in types:
            key = f"kp{kp:02d}-{qt}"
            item_keys.append((key, f"知识点{kp}", qt))
            conn.execute(
                "INSERT INTO question_bank (training_id, item_key, knowledge_point, "
                "question_type, question_text, banked_at) VALUES (?, ?, ?, ?, '题干', datetime('now'))",
                (training_id, key, f"知识点{kp}", qt),
            )
    for _ in range(300):
        key, _, qt = item_keys[rng.randrange(len(item_keys))]
        score = round(rng.uniform(0.3, 1.0), 2)
        result = "pass" if score >= 0.8 else "fail"
        mistake = json.dumps({key: rng.choice(reasons)}, ensure_ascii=False) if result == "fail" else None
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, round_index, result, "
            "score, mistake_reasons, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (training_id, key, rng.randint(1, 5), result, score, mistake, "quiz"),
        )
    conn.execute(
        "INSERT INTO assessments (training_id, trigger, status, question_count, created_at) "
        "VALUES (?, 'scheduled', 'completed', 30, datetime('now'))",
        (training_id,),
    )
    assessment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i in range(30):
        conn.execute(
            "INSERT INTO assessment_items (assessment_id, ordinal, item_key, knowledge_point, "
            "question_type, question, user_answer, verdict, created_at) "
            "VALUES (?, ?, ?, '知识点', 'qa', '题干', ?, 'pass', datetime('now'))",
            (assessment_id, i + 1, item_keys[i][0], "这是一段约两百字的原始作答文本。" * 15),
        )
    conn.commit()

    ctx = ms.render_context(training_id, conn=conn)
    return {
        "attempts": 300,
        "knowledge_points": 12,
        "timings": {
            "knowledge_profile": _timed(lambda: ms.knowledge_profile(training_id, conn=conn)),
            "recommended_type_mix": _timed(lambda: ms.recommended_type_mix(training_id, conn=conn)),
            "render_context": _timed(lambda: ms.render_context(training_id, conn=conn)),
        },
        "ctx_text": ctx.text,
        "approx_tokens": ctx.approx_tokens,
        "naive_tokens": ctx.naive_tokens,
        "compression_ratio": ctx.compression_ratio,
    }


def _stats(runs: list[tuple[int, int, int, bool]] | list[dict]) -> str:
    if runs and isinstance(runs[0], dict):
        tins = [r["tokens_in"] for r in runs]
        outs = [r["tokens_out"] for r in runs]
        lats = [r["latency_ms"] for r in runs]
    else:
        tins = [r[0] for r in runs]
        outs = [r[1] for r in runs]
        lats = [r[2] for r in runs]
    return (
        f"tokens_in {min(tins)}-{max(tins)}（均值 {statistics.mean(tins):.0f}）｜ "
        f"tokens_out {min(outs)}-{max(outs)}（均值 {statistics.mean(outs):.0f}）｜ "
        f"延迟 {min(lats)}-{max(lats)}ms（均值 {statistics.mean(lats):.0f}）"
    )


def main() -> int:
    print(f"模型：{GRADER_MODEL}（阿里云兼容端点，免费额度）｜每臂 RUNS={RUNS}")
    conn = _open_ro()
    row, points = _pick_case(conn)
    training_id = int(row["training_id"])
    print(
        f"样本：plan_item #{row['id']}（training={training_id}, item={row['item_key']}），"
        f"固化要点 {len(points)} 条"
    )

    variables = _grade_variables(row, points)
    print("\n== 臂 A｜项目真实路径 complete('quiz_grade') ==")
    a_rows = arm_a_project_path(variables)
    for r in a_rows:
        print(
            f"  run{r['run']}: tokens_in={r['tokens_in']} tokens_out={r['tokens_out']} "
            f"latency={r['latency_ms']}ms 重试 {r['retries']} 次 逐条判定 {r['points_judged']} 条"
        )

    print("\n== 臂 B｜同 prompt 注入/不注入学习者记忆上下文 ==")
    b = arm_b_memory_delta(conn, row, variables)
    base_mean = statistics.mean([r[0] for r in b["base"]])
    inj_mean = statistics.mean([r[0] for r in b["injected"]])
    all_runs = list(b["base"]) + list(b["injected"])
    invalid = [r for r in all_runs if not r[3]]
    for label, runs in (("不注入", b["base"]), ("注入", b["injected"])):
        for idx, r in enumerate(runs, 1):
            mark = "✓" if r[3] else f"✗ {r[4]}"
            print(f"  [{label} run{idx}] in={r[0]} out={r[1]} {r[2]}ms 校验 {mark}")
    print(f"  → 直调 {len(all_runs)} 次中未过 Schema 校验 {len(invalid)} 次（直调不带重试，项目路径由重试兜底）")
    print(f"  记忆块实测注入 ≈{b['ctx_approx_tokens']} tokens；tokens_in 均值增量 ≈{inj_mean - base_mean:.0f}")

    print("\n== 臂 C｜生产路径 answer_service._grade_answer（含记忆注入与 Schema 重试）==")
    outcome, captured = arm_c_production_path(row)
    injected_into_prompt = any("【学习者背景】" in blk for blk in captured["blocks"])
    print(f"  prompt 注入记忆块：{injected_into_prompt}（共 {len(captured['blocks'])} 次调用）")
    for i, u in enumerate(captured["usage"], 1):
        print(
            f"  call{i}: tokens_in={u['tokens_in']} tokens_out={u['tokens_out']} "
            f"latency={u['latency_ms']}ms 重试 {u['retries']} 次"
        )
    print(
        f"  判分结果：graded={outcome['graded']} verdict={outcome['verdict']} "
        f"score={outcome['score']} reason={outcome['reason'][:60]}"
    )

    print("\n== 记忆模块存取（真实库，中位耗时/次）==")
    for name, ms_time in real_db_sql_timings(conn, training_id).items():
        print(f"  {name:<22} {ms_time:.3f} ms")

    print("\n== 记忆模块存取（种子库 300 次作答 × 12 知识点 × 3 题型）==")
    demo = seeded_db_demo()
    for name, ms_time in demo["timings"].items():
        print(f"  {name:<22} {ms_time:.3f} ms")
    print(
        f"  紧凑上下文 ≈{demo['approx_tokens']} tokens vs 原始作答基线 ≈{demo['naive_tokens']} tokens"
        f"（压缩比 {demo['compression_ratio']:.3f}）"
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
