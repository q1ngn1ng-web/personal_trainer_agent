"""Unified LLM client. All DeepSeek calls MUST go through ``complete``."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests
from dotenv import load_dotenv

from src.llm.fallback import fallback_for
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.retry import retry_with_feedback
from src.llm.schema import SCHEMA_REGISTRY
from src.llm.validators import keyword_coverage_check, parse_and_validate

load_dotenv()

logger = logging.getLogger("src.llm.client")

DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

DEFAULT_TEMPERATURE: float = 0.2
DEFAULT_MAX_TOKENS: int = 4096
REQUEST_TIMEOUT_S: int = 60
KEYWORD_COVERAGE_PURPOSES: frozenset[str] = frozenset({"baseline_q"})


class LLMError(Exception):
    """Raised when the underlying DeepSeek call fails or returns unusable output."""


class LLMValidationError(LLMError):
    """Raised when the LLM output fails JSON Schema or semantic checks."""


def _schema_dump(schema: dict[str, Any] | None) -> str:
    if schema is None:
        return ""
    return json.dumps(schema, ensure_ascii=False, indent=2)


def _render_prompt(template: str, variables: dict[str, Any]) -> str:
    rendered = template.format(**variables)
    feedback = variables.get("__feedback__")
    if feedback:
        rendered += (
            "\n\n[上一次尝试错误反馈] " + str(feedback)
            + "\n请根据错误反馈修正后，重新输出严格 JSON。"
        )
    return rendered


def _call_api(messages: list[dict[str, str]]) -> tuple[str, int, int]:
    if not DEEPSEEK_API_KEY:
        raise LLMError("DEEPSEEK_API_KEY is not set")
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": DEFAULT_TEMPERATURE,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        raise LLMError(f"DeepSeek request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise LLMError(f"DeepSeek API error {resp.status_code}: {resp.text[:500]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"DeepSeek returned non-JSON body: {resp.text[:200]}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"DeepSeek returned no choices: {data}")
    content = choices[0].get("message", {}).get("content", "") or ""
    usage = data.get("usage") or {}
    return content, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def _coerce_keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[,\n;]+", value) if p.strip()]
    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p).strip()]
    return []


def _semantic_check(prompt_name: str, output_json: dict[str, Any], variables: dict[str, Any]) -> None:
    if prompt_name in KEYWORD_COVERAGE_PURPOSES:
        keywords = _coerce_keywords(variables.get("keywords"))
        questions = output_json.get("questions") or []
        if keywords and not keyword_coverage_check(questions, keywords):
            raise LLMValidationError(
                f"keyword_coverage_check failed for {prompt_name}: "
                f"every question must contain at least one keyword from {keywords}"
            )


def _run_once(prompt_name: str, variables: dict[str, Any]) -> dict[str, Any]:
    template, version = PROMPT_REGISTRY[prompt_name]
    schema = SCHEMA_REGISTRY.get(prompt_name)
    if schema is not None and "schema" not in variables:
        variables = {**variables, "schema": _schema_dump(schema)}

    rendered = _render_prompt(template, variables)
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
    output_text, tokens_in, tokens_out = _call_api(messages)
    latency_ms = int((time.monotonic() - start) * 1000)

    output_json: dict[str, Any] | None = None
    if schema is not None:
        output_json = parse_and_validate(output_text, schema)
        _semantic_check(prompt_name, output_json, variables)

    return {
        "output_text": output_text,
        "output_json": output_json,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "retry_count": 0,
        "model": DEEPSEEK_MODEL,
        "prompt_name": prompt_name,
        "prompt_version": version,
    }


def _audit_training_id(training_id: int | None) -> int | None:
    """训练 id 守卫：0 或负数（老流程的占位值）不写 FK，记 NULL。"""
    try:
        value = int(training_id) if training_id is not None else None
    except (TypeError, ValueError):
        return None
    return value if value and value > 0 else None


def _record_audit(
    *,
    purpose: str,
    prompt_name: str,
    prompt_version: str,
    training_id: int | None,
    input_text: str,
    result: dict[str, Any] | None,
    fallback_used: int,
    failure: Exception | None,
) -> None:
    """统一审计：每次 ``complete``（成功 / 降级 / 彻底失败）都写一行 ``llm_calls``。

    记账下沉在客户端，业务层不再手写；审计本身失败只打日志，绝不阻塞主流程。
    """
    try:
        from src.db.queries import record_llm_call

        owner_id = _audit_training_id(training_id)
        if result is not None:
            record_llm_call(
                call_purpose=purpose,
                prompt_name=result["prompt_name"],
                prompt_version=result["prompt_version"],
                model=result["model"],
                input_text=input_text[:4000],
                latency_ms=result["latency_ms"],
                tokens_in=result["tokens_in"],
                tokens_out=result["tokens_out"],
                output_text=result.get("output_text"),
                output_json=result.get("output_json"),
                retry_count=result["retry_count"],
                fallback_used=fallback_used,
                validation_result="pass" if result.get("output_json") is not None else "fail",
                training_id=owner_id,
                failure_reason=None,
            )
        else:
            record_llm_call(
                call_purpose=purpose,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                model=DEEPSEEK_MODEL,
                input_text=input_text[:4000],
                latency_ms=0,
                tokens_in=0,
                tokens_out=0,
                retry_count=3,
                fallback_used=0,
                validation_result="fail",
                failure_reason=f"{type(failure).__name__}: {failure}"[:500] if failure else "unknown",
                training_id=owner_id,
            )
    except Exception:  # pragma: no cover - 审计失败不能影响主流程
        logger.exception("llm audit: could not persist record for %s", prompt_name)


def complete(
    prompt_name: str,
    variables: dict[str, Any],
    schema: dict[str, Any] | None = None,
    max_attempts: int = 3,
    training_id: int | None = None,
    call_purpose: str | None = None,
) -> dict[str, Any]:
    """Call the LLM with retry-with-feedback; return dict with all observability fields.

    On exhaustion, if a fallback exists for ``prompt_name`` it is served and returned with
    retry_count reflecting actual attempts; otherwise the underlying exception is re-raised.

    每次调用（成功 / fallback / 彻底失败）都会在客户端写一行 ``llm_calls``：
    ``call_purpose`` 默认取 ``prompt_name``，``training_id`` 由调用方传入（可为空）。
    """
    if prompt_name not in PROMPT_REGISTRY:
        raise ValueError(f"unknown prompt_name: {prompt_name}")
    if schema is not None and "schema" not in variables:
        variables = {**variables, "schema": _schema_dump(schema)}

    purpose = call_purpose or prompt_name
    audit_input = json.dumps(
        {k: v for k, v in variables.items() if k not in ("schema", "__feedback__")},
        ensure_ascii=False,
    )
    _, fallback_version = PROMPT_REGISTRY[prompt_name]

    attempt_count = {"n": 0}

    def call_with_count(name: str, vars_: dict[str, Any]) -> dict[str, Any]:
        attempt_count["n"] += 1
        return _run_once(name, vars_)

    try:
        result = retry_with_feedback(
            call_with_count, prompt_name, variables, max_attempts=max_attempts
        )
        result["retry_count"] = max(0, attempt_count["n"] - 1)
        _record_audit(
            purpose=purpose,
            prompt_name=prompt_name,
            prompt_version=result["prompt_version"],
            training_id=training_id,
            input_text=audit_input,
            result=result,
            fallback_used=0,
            failure=None,
        )
        return result
    except Exception as exc:
        logger.error(
            "complete: %s failed after %d attempt(s): %s",
            prompt_name,
            attempt_count["n"],
            exc,
        )
        fb = fallback_for(prompt_name)
        if fb is not None:
            fb_result = {
                "output_text": json.dumps(fb, ensure_ascii=False),
                "output_json": fb,
                "latency_ms": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "retry_count": attempt_count["n"],
                "model": DEEPSEEK_MODEL,
                "prompt_name": prompt_name,
                "prompt_version": fallback_version,
            }
            _record_audit(
                purpose=purpose,
                prompt_name=prompt_name,
                prompt_version=fallback_version,
                training_id=training_id,
                input_text=audit_input,
                result=fb_result,
                fallback_used=1,
                failure=None,
            )
            return fb_result
        _record_audit(
            purpose=purpose,
            prompt_name=prompt_name,
            prompt_version=fallback_version,
            training_id=training_id,
            input_text=audit_input,
            result=None,
            fallback_used=0,
            failure=exc,
        )
        raise
