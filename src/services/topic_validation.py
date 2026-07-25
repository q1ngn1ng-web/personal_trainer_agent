"""Topic specificity validation via the unified LLM client."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.db.queries import record_llm_call
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY

logger = logging.getLogger("src.services.topic_validation")


@dataclass
class TopicValidationResult:
    """Outcome of validating whether a topic is concrete enough to train on."""

    is_valid: bool
    suggestions: list[str]
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)


def _build_input_text(topic: str) -> str:
    template, _ = PROMPT_REGISTRY["topic_validation"]
    schema = SCHEMA_REGISTRY["topic_validation"]
    return template.format(topic=topic, description="", schema=json.dumps(schema, ensure_ascii=False, indent=2))


def _record_failure(topic: str, exc: Exception) -> None:
    _, version = PROMPT_REGISTRY["topic_validation"]
    try:
        record_llm_call(
            call_purpose="topic_validation",
            prompt_name="topic_validation",
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
        logger.exception("validate_topic: failed to persist failure record")


def validate_topic(topic: str, *, training_root: str = ".") -> TopicValidationResult:
    """Validate that ``topic`` is concrete enough to be trained.

    Fails open: if the LLM call raises, returns ``is_valid=True`` with empty
    suggestions so the user's flow is never blocked by the validator itself.
    """
    variables = {"topic": topic, "description": ""}

    try:
        result = complete(prompt_name="topic_validation", variables=variables)
    except Exception as exc:
        logger.warning("validate_topic: LLM unavailable, failing open: %s", exc)
        _record_failure(topic, exc)
        return TopicValidationResult(
            is_valid=True,
            suggestions=[],
            reason="LLM unavailable, skipping validation",
            raw={},
        )

    output_json = result.get("output_json") or {}
    is_valid = bool(output_json.get("is_valid", True))
    suggestions = [str(s) for s in (output_json.get("suggestions") or [])]
    reason = str(output_json.get("reason", ""))
    validation_result = "pass" if result.get("output_json") else "fail"

    try:
        record_llm_call(
            call_purpose="topic_validation",
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
        logger.exception("validate_topic: failed to record LLM call")

    return TopicValidationResult(
        is_valid=is_valid,
        suggestions=suggestions,
        reason=reason,
        raw=output_json,
    )


__all__ = ["TopicValidationResult", "validate_topic"]