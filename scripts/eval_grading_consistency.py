"""Grading self-consistency experiment (change ``grading-consistency``).

Usage::

    DASHSCOPE_KEY_FILE=/home/ubuntu/py_code/PythonProject16/.env \
    DB_PATH=/tmp/trainer_eval_copy.db \
    uv run python scripts/eval_grading_consistency.py

Grades the SAME stored question + answer N times at the legacy temperature
(0.2) and at the new deterministic temperature (0.0), then reports:

* how many distinct point-verdict combinations came out (flip count);
* the rule-layer score spread (min/max) and pass/fail outcomes per temperature;
* the production guarantee: with ``grading_cache`` warm, repeat grading is
  byte-identical by construction (cache hit = zero model call).

Read-only against the DB (opens ``mode=ro``); nothing is written anywhere.
Calls go to the Alibaba Cloud free-quota endpoint via the client's OpenAI
compatibility layer (same env contract as ``eval_grading_memory_cost.py``).
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPEATS = int(os.environ.get("EVAL_RUNS", "5"))


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
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY not found; set DASHSCOPE_KEY_FILE")
    os.environ["DEEPSEEK_API_KEY"] = api_key
    os.environ["DEEPSEEK_BASE_URL"] = (
        values.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    os.environ["DEEPSEEK_MODEL"] = os.environ.get("EVAL_MODEL", "deepseek-v4.1-flash")
    os.environ.setdefault("DB_PATH", str(PROJECT_ROOT / "data" / "trainer.db"))


_load_dashscope_env()

import sqlite3  # noqa: E402

from src.llm import client as llm_client  # noqa: E402
from src.services.grading_service import PointSpec, grade_question  # noqa: E402

DB_PATH = Path(os.environ["DB_PATH"])
MODEL = os.environ["DEEPSEEK_MODEL"]
ANSWER = "RDB 是定时快照，AOF 是追加日志，所以持久化用 RDB 就够了，不需要 AOF。"


def _pick_case() -> tuple[sqlite3.Row, list[PointSpec]]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, training_id, item_key, question, reference_answer, points "
            "FROM plan_items WHERE points IS NOT NULL AND question IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SystemExit("no plan_item with persisted points")
        specs = [
            PointSpec(
                point_id=str(p["point_id"]),
                text=str(p["text"]),
                weight=float(p["weight"]),
                required=bool(p["is_required"]),
            )
            for p in json.loads(row["points"] or "[]")
        ]
        return row, specs
    finally:
        conn.close()


def _grade_once(row: sqlite3.Row, specs: list[PointSpec], temperature: float) -> tuple[str, float | None]:
    from src.services.answer_service import _parse_points_json

    points = _parse_points_json(row["points"])
    payload = [
        {
            "item_key": str(row["item_key"]),
            "question": str(row["question"]),
            "reference_answer": str(row["reference_answer"] or ""),
            "answer": ANSWER,
            "points": points,
        }
    ]
    variables = {
        "items": json.dumps(payload, ensure_ascii=False, indent=2),
        "memory_block": "",
        "schema": llm_client._schema_dump(llm_client.SCHEMA_REGISTRY["quiz_grade"]),
    }
    template, _ = llm_client.PROMPT_REGISTRY["quiz_grade"]
    prompt = llm_client._render_prompt(template, variables)
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名严格的 JSON 生成助手。"
                "只能输出合法 JSON 对象，不要任何解释、markdown 围栏或前后缀文字。"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    for _ in range(3):  # 与生产重试口径一致：Schema 失败带错误反馈重试
        content, _, _ = llm_client._call_api(messages, temperature=temperature)
        try:
            output = llm_client.parse_and_validate(
                content, llm_client.SCHEMA_REGISTRY["quiz_grade"]
            )
        except Exception as exc:  # noqa: BLE001
            variables["__feedback__"] = str(exc)[:400]
            prompt = llm_client._render_prompt(template, variables)
            messages[1]["content"] = prompt
            continue
        results = output.get("results") or []
        verdicts = {
            str(v.get("point_id")): str(v.get("verdict"))
            for v in ((results[0].get("point_verdicts") if results else None) or [])
        }
        graded = grade_question("qa", answer=ANSWER, points=specs, point_verdicts=verdicts)
        combo = ",".join(f"{sid}:{verdicts.get(spec.point_id, '?')}" for sid, spec in ((s.point_id, s) for s in specs))
        return combo, round(float(graded.score), 4), graded.passed  # type: ignore[return-value]
    raise SystemExit("grading never produced schema-valid output in 3 attempts")


def main() -> int:
    row, specs = _pick_case()
    print(
        f"模型 {MODEL}｜样本 plan_item #{row['id']}（{len(specs)} 条固化要点）｜"
        f"同一作答重判 {REPEATS} 次/温度"
    )
    for label, temperature in (("温度 0.2（旧行为）", 0.2), ("温度 0.0（判分用途）", 0.0)):
        outcomes = [_grade_once(row, specs, temperature) for _ in range(REPEATS)]
        combos = Counter(o[0] for o in outcomes)
        scores = [o[1] for o in outcomes]
        passed = Counter("pass" if o[2] else "fail" for o in outcomes)
        print(f"\n== {label} ==")
        for combo, count in combos.most_common():
            print(f"  判定组合 ×{count}: {combo}")
        print(
            f"  得分 {min(scores)}-{max(scores)}"
            f"（{'稳定' if max(scores) == min(scores) else '波动'}）｜"
            f"通过判定 {'/'.join(f'{k}×{v}' for k, v in passed.items())}"
        )
    print("\n生产口径：grading_cache 命中后重判 = 逐字复现（零模型调用），由测试钉死。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
