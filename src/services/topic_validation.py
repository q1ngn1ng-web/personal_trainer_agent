"""Topic specificity validation via the unified LLM client."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.llm.client import complete

logger = logging.getLogger("src.services.topic_validation")


@dataclass
class TopicValidationResult:
    """Outcome of validating whether a topic is concrete enough to train on."""

    is_valid: bool
    suggestions: list[str]
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)


def validate_topic(topic: str, *, training_root: str = ".") -> TopicValidationResult:
    """Validate that ``topic`` is concrete enough to be trained.

    Fails open: if the LLM call raises, returns ``is_valid=True`` with empty
    suggestions so the user's flow is never blocked by the validator itself.
    调用审计（成功/失败）由统一客户端写入 ``llm_calls``，这里不再手写。
    """
    variables = {"topic": topic, "description": ""}

    try:
        result = complete(prompt_name="topic_validation", variables=variables)
    except Exception as exc:
        logger.warning("validate_topic: LLM unavailable, failing open: %s", exc)
        return TopicValidationResult(
            is_valid=True,
            suggestions=[],
            reason="LLM unavailable, skipping validation",
            raw={},
        )

    output_json = result.get("output_json") or {}
    return TopicValidationResult(
        is_valid=bool(output_json.get("is_valid", True)),
        suggestions=[str(s) for s in (output_json.get("suggestions") or [])],
        reason=str(output_json.get("reason", "")),
        raw=output_json,
    )


__all__ = ["TopicValidationResult", "validate_topic"]
