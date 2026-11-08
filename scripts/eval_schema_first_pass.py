"""First-pass schema-compliance experiment (schema-in-prompt fix, 2026-11-09).

Usage::

    DASHSCOPE_KEY_FILE=/home/ubuntu/py_code/PythonProject16/.env \
    uv run python scripts/eval_schema_first_pass.py

Question this answers: does showing the JSON Schema to the model in the prompt
raise **first-pass compliance** (output passes JSON Schema validation without
any retry), vs. the old templates that only said "字段见 schema" without
showing it?

Method: for the grading purpose (``quiz_grade``, the highest-frequency LLM
path), render the real stored question + answer payload with the current
v1.3.0 template (schema embedded) and with the pre-fix template text (schema
mentioned but not shown), then N direct calls each — no retry-with-feedback,
exactly one shot per call — and count schema-valid outputs.

Read-only: opens the DB with ``mode=ro``; calls go to the Alibaba Cloud
free-quota endpoint via the client's OpenAI-compatible layer.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPEATS = int(os.environ.get("EVAL_RUNS", "6"))

ANSWER = "RDB 是定时快照，AOF 是追加日志，所以持久化用 RDB 就够了，不需要 AOF。"

#: 修复前的 quiz_grade 模板（v1.2.0：只在口径里提"字段见 schema"，不展示 schema）。
PREFIX_TEMPLATE = """你是测验评分员。请依据参考答案，判定用户对每道题的作答是否正确。

判定口径：
1. 只判断"是否答到了参考答案里的关键点"，表述不同不影响判定；
2. 每道题会给出带 point_id 的要点清单，你要对**每条要点**给出四态判定：`hit`（答到且正确）/ `partial`（只答了一部分）/ `wrong`（说反了，比没提到更糟）/ `missing`（完全没提）；
3. 没有要点清单的历史题才退回整体判断：完全没答、答非所问、只重复题干 → 全部 `missing`；
4. 每道题另给一句简短理由（引用用户作答里的依据）；
4. 只输出 JSON，字段见 schema；
5. 若给出「学习者背景」（该用户的历史错因与薄弱点），仅用于理解作答语境，**不得改变上面的判定口径**。

题目与作答：
{items}
{memory_block}
"""


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

from src.llm import client as llm_client  # noqa: E402

DB_PATH = Path(os.environ["DB_PATH"])
MODEL = os.environ["DEEPSEEK_MODEL"]


def _pick_payload() -> dict:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT item_key, question, reference_answer, points FROM plan_items "
            "WHERE points IS NOT NULL AND question IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SystemExit("no plan_item with persisted points")
        return {
            "item_key": str(row["item_key"]),
            "question": str(row["question"]),
            "reference_answer": str(row["reference_answer"] or ""),
            "answer": ANSWER,
            "points": json.loads(row["points"] or "[]"),
        }
    finally:
        conn.close()


def _one_shot(template: str, variables: dict) -> tuple[bool, int, int]:
    """单发直调（无重试）：返回 (首发合规, tokens_in, latency_ms)。"""
    rendered = llm_client._render_prompt(template, variables)
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名严格的 JSON 生成助手。"
                "只能输出合法 JSON 对象，不要任何解释、markdown 围栏或前后缀文字。"
            ),
        },
        {"role": "user", "content": rendered},
    ]
    start = time.monotonic()
    content, tokens_in, _ = llm_client._call_api(messages, temperature=0.0)
    latency = int((time.monotonic() - start) * 1000)
    try:
        llm_client.parse_and_validate(content, llm_client.SCHEMA_REGISTRY["quiz_grade"])
        return True, tokens_in, latency
    except Exception:
        return False, tokens_in, latency


def main() -> int:
    item = _pick_payload()
    variables = {
        "items": json.dumps([item], ensure_ascii=False, indent=2),
        "memory_block": "",
    }
    print(f"模型 {MODEL}｜quiz_grade 真实载荷（{len(item['points'])} 条要点）｜每臂单发 {REPEATS} 次、无重试")

    template_fixed, version = llm_client.PROMPT_REGISTRY["quiz_grade"]
    arms = (
        ("修复前 v1.2.0（不展示 schema）", PREFIX_TEMPLATE),
        (f"修复后 {version}（prompt 内嵌 schema）", template_fixed),
    )
    for label, template in arms:
        vs = {**variables, "schema": llm_client._schema_dump(llm_client.SCHEMA_REGISTRY["quiz_grade"])}
        # 修复前模板没有 {schema} 占位符——format 会忽略多余的键，schema 不进 prompt（还原旧行为）
        results = [_one_shot(template, vs) for _ in range(REPEATS)]
        valid = sum(1 for r in results if r[0])
        tokens = [r[1] for r in results]
        print(
            f"\n== {label} ==\n  首发合规 {valid}/{REPEATS}"
            f"｜tokens_in {min(tokens)}-{max(tokens)}（均值 {sum(tokens) / len(tokens):.0f}）"
        )
        for i, r in enumerate(results, 1):
            print(f"  run{i}: {'✓ 合规' if r[0] else '✗ 不合规'}  in={r[1]}  {r[2]}ms")
    print(
        "\n口径：单发直调（生产链路还有错误反馈重试兜底）；"
        "首发合规率决定平均延迟是否翻倍与重试 token 是否白花。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
