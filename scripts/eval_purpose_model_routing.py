"""Per-purpose model-routing experiment (cost governance, 2026-11-09).

Usage::

    DASHSCOPE_KEY_FILE=/home/ubuntu/py_code/PythonProject16/.env \
    uv run python scripts/eval_purpose_model_routing.py

Question this answers: for the two light-semantic purposes (``topic_validation``,
``keyword_generation``), can a cheaper/lighter model (``qwen-flash``) replace the
main model without losing first-pass schema compliance or output quality?

Method: render each purpose's real prompt shape, call BOTH models N times each
(single shot, temperature as production: default 0.2), count schema-valid
outputs, record latency/tokens, and dump the outputs for quality eyeballing.
Quality gates for these two purposes are structural (valid JSON, non-empty
keywords / boolean + reasons), not semantic — that's exactly why they are
routing candidates.

Read-only; nothing is written to any DB. Uses the Alibaba Cloud free-quota
endpoint (both models have free quota there).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPEATS = int(os.environ.get("EVAL_RUNS", "4"))

#: 两个轻用途的真实载荷形状（来自生产 variables）
CASES = {
    "topic_validation": {
        "topic": "Redis 八股冲刺",
        "description": "三周内备完后端面试中 Redis 的高频考点：持久化、过期策略、缓存三件套",
    },
    "keyword_generation": {
        "topic": "Redis 八股冲刺",
        "description": "三周内备完后端面试中 Redis 的高频考点：持久化、过期策略、缓存三件套",
    },
}


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
    os.environ["DEEPSEEK_MODEL"] = os.environ.get("EVAL_MAIN_MODEL", "deepseek-v4.1-flash")
    globals()["LIGHT_MODEL"] = values.get("DASHSCOPE_MODEL_ID") or os.environ.get(
        "EVAL_LIGHT_MODEL", "qwen-flash"
    )


_load_dashscope_env()

from src.llm import client as llm_client  # noqa: E402

MAIN_MODEL = os.environ["DEEPSEEK_MODEL"]
LIGHT_MODEL = globals()["LIGHT_MODEL"]


def _one_shot(purpose: str, model: str) -> tuple[bool, int, int, dict | None]:
    template, _ = llm_client.PROMPT_REGISTRY[purpose]
    variables = {
        **CASES[purpose],
        "schema": llm_client._schema_dump(llm_client.SCHEMA_REGISTRY[purpose]),
    }
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
    content, tokens_in, tokens_out = llm_client._call_api(
        messages, temperature=llm_client.temperature_for(purpose), model=model
    )
    latency = int((time.monotonic() - start) * 1000)
    try:
        payload = llm_client.parse_and_validate(content, llm_client.SCHEMA_REGISTRY[purpose])
        return True, tokens_in, latency, payload
    except Exception:
        return False, tokens_in, latency, None


def main() -> int:
    print(f"主力 {MAIN_MODEL} vs 轻模型 {LIGHT_MODEL}｜每用途每模型单发 {REPEATS} 次（生产温度）")
    for purpose in CASES:
        print(f"\n== {purpose} ==")
        for label, model in (("主力", MAIN_MODEL), ("轻模型", LIGHT_MODEL)):
            results = [_one_shot(purpose, model) for _ in range(REPEATS)]
            valid = sum(1 for r in results if r[0])
            lat = [r[2] for r in results]
            tok_in = [r[1] for r in results]
            print(
                f"  [{label} {model}] 首发合规 {valid}/{REPEATS}｜"
                f"in {min(tok_in)}-{max(tok_in)}｜延迟 {min(lat)}-{max(lat)}ms（中位 {statistics.median(lat):.0f}）"
            )
            sample = next((r[3] for r in results if r[3]), None)
            if sample is not None:
                print(f"    输出示例: {json.dumps(sample, ensure_ascii=False)[:180]}")
    print(
        "\n口径：两用途的质量闸门是结构性的（合规 JSON + 非空字段），这正是它们可路由的原因；"
        "判分不参与路由（人工一致率标注未完成前的护栏）。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
