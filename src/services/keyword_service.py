"""Keyword whitelist generation via the unified LLM client."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.db.queries import record_llm_call
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY

logger = logging.getLogger("src.services.keyword_service")


@dataclass
class KeywordResult:
    """Generated keyword whitelist plus coverage constraints."""

    keywords: list[str]
    must_cover_count: int
    forbidden: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


def _fallback_topic(topic: str) -> str:
    first = topic.split()
    return first[0] if first else "topic"


def _build_input_text(topic: str) -> str:
    template, _ = PROMPT_REGISTRY["keyword_generation"]
    schema = SCHEMA_REGISTRY["keyword_generation"]
    return template.format(topic=topic, description="", schema=json.dumps(schema, ensure_ascii=False, indent=2))


def _record_failure(topic: str, exc: Exception) -> None:
    _, version = PROMPT_REGISTRY["keyword_generation"]
    try:
        record_llm_call(
            call_purpose="keyword_generation",
            prompt_name="keyword_generation",
            prompt_version=version,
            model="unknown",
            input_text=_build_input_text(topic),
            latency_ms=0,
            tokens_in=0,
            tokens_out=0,
            output_text=None,
            output_json=None,
            retry_count=0,
            fallback_used=0,
            validation_result="fail",
            failure_reason=str(exc),
        )
    except Exception:
        logger.exception("generate_keywords: failed to persist failure record")


def generate_keywords(topic: str, *, training_root: str = ".") -> KeywordResult:
    """Generate a keyword whitelist for ``topic`` via the LLM."""
    variables = {"topic": topic, "description": ""}
    fallback_seed = _fallback_topic(topic)

    try:
        result = complete(prompt_name="keyword_generation", variables=variables)
    except Exception as exc:
        logger.warning("generate_keywords: LLM unavailable, using fallback seed: %s", exc)
        _record_failure(topic, exc)
        return KeywordResult(
            keywords=[fallback_seed],
            must_cover_count=2,
            forbidden=[],
            raw={},
        )

    output_json = result.get("output_json") or {}
    keywords = [str(k) for k in (output_json.get("keywords") or []) if str(k).strip()]
    if not keywords:
        keywords = [fallback_seed]
    must_cover_count = int(output_json.get("must_cover_count") or 2)
    forbidden = [str(f) for f in (output_json.get("forbidden") or []) if str(f).strip()]
    validation_result = "pass" if result.get("output_json") else "fail"

    try:
        record_llm_call(
            call_purpose="keyword_generation",
            prompt_name=result["prompt_name"],
            prompt_version=result["prompt_version"],
            model=result["model"],
            input_text=_build_input_text(topic),
            latency_ms=result["latency_ms"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            output_text=result.get("output_text"),
            output_json=output_json,
            retry_count=result["retry_count"],
            fallback_used=0,
            validation_result=validation_result,
        )
    except Exception:
        logger.exception("generate_keywords: failed to record LLM call")

    return KeywordResult(
        keywords=keywords,
        must_cover_count=must_cover_count,
        forbidden=forbidden,
        raw=output_json,
    )


__all__ = ["KeywordResult", "generate_keywords"]