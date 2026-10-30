"""Keyword whitelist generation via the unified LLM client."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.llm.client import complete

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


def generate_keywords(topic: str, *, training_root: str = ".") -> KeywordResult:
    """Generate a keyword whitelist for ``topic`` via the LLM.

    调用审计（成功/失败）由统一客户端写入 ``llm_calls``，这里不再手写。
    """
    variables = {"topic": topic, "description": ""}
    fallback_seed = _fallback_topic(topic)

    try:
        result = complete(prompt_name="keyword_generation", variables=variables)
    except Exception as exc:
        logger.warning("generate_keywords: LLM unavailable, using fallback seed: %s", exc)
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

    return KeywordResult(
        keywords=keywords,
        must_cover_count=int(output_json.get("must_cover_count") or 2),
        forbidden=[str(f) for f in (output_json.get("forbidden") or []) if str(f).strip()],
        raw=output_json,
    )


__all__ = ["KeywordResult", "generate_keywords"]
