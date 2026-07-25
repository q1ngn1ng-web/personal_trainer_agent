"""Validators: JSON extraction/schema validation and keyword coverage check."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

logger = logging.getLogger("src.llm.validators")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty LLM output")
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_and_validate(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Extract JSON from LLM text (handles ```json fences) and validate against schema.

    Raises ValueError on extraction failure, json.JSONDecodeError on invalid JSON,
    jsonschema.ValidationError on schema mismatch.
    """
    extracted = _extract_json(text)
    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError as exc:
        logger.warning("parse_and_validate: JSON decode failed: %s", exc)
        raise
    if not isinstance(parsed, dict):
        raise ValidationError(f"top-level JSON is not an object: {type(parsed).__name__}")
    Draft202012Validator(schema).validate(parsed)
    return parsed


def keyword_coverage_check(questions: list[dict[str, Any]], keywords: list[str]) -> bool:
    """Return True iff every question's 'question' field contains at least one keyword (case-insensitive)."""
    if not questions:
        return False
    if not keywords:
        return False
    needles = [str(k).lower() for k in keywords if str(k).strip()]
    if not needles:
        return False
    for q in questions:
        if not isinstance(q, dict):
            return False
        text = str(q.get("question", "")).lower()
        if not any(needle in text for needle in needles):
            return False
    return True