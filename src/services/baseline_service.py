"""Baseline diagnostic question generation with keyword-coverage retry."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.db.queries import record_llm_call
from src.llm.client import complete
from src.llm.fallback import fallback_for
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY
from src.llm.validators import keyword_coverage_check

logger = logging.getLogger("src.services.baseline_service")

_MAX_ATTEMPTS: int = 3


@dataclass
class BaselineQuestion:
    """A single baseline diagnostic question."""

    dimension: str
    difficulty: int
    question: str
    reference_answer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "difficulty": self.difficulty,
            "question": self.question,
            "reference_answer": self.reference_answer,
        }


@dataclass
class BaselineQuestions:
    """Three baseline diagnostic questions plus provenance metadata."""

    questions: list[BaselineQuestion]
    raw: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False


def _build_input_text(topic: str, keywords: list[str], forbidden: list[str]) -> str:
    template, _ = PROMPT_REGISTRY["baseline_q"]
    schema = SCHEMA_REGISTRY["baseline_q"]
    return template.format(
        topic=topic,
        description="",
        keywords=keywords,
        forbidden=forbidden,
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
    )


def _parse_questions(payload: dict[str, Any]) -> list[BaselineQuestion]:
    parsed: list[BaselineQuestion] = []
    for entry in payload.get("questions") or []:
        if not isinstance(entry, dict):
            continue
        try:
            parsed.append(
                BaselineQuestion(
                    dimension=str(entry.get("dimension", "concept")),
                    difficulty=int(entry.get("difficulty", 1)),
                    question=str(entry.get("question", "")),
                    reference_answer=str(entry.get("reference_answer", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    return parsed


def _fallback_result() -> dict[str, Any]:
    _, version = PROMPT_REGISTRY["baseline_q"]
    fb = fallback_for("baseline_q") or {"questions": []}
    return {
        "output_text": json.dumps(fb, ensure_ascii=False),
        "output_json": fb,
        "latency_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "retry_count": _MAX_ATTEMPTS,
        "model": "fallback",
        "prompt_name": "baseline_q",
        "prompt_version": version,
    }


def _record(result: dict[str, Any], topic: str, keywords: list[str], forbidden: list[str], fallback_used: int) -> None:
    validation_result = "pass" if result.get("output_json") else "fail"
    try:
        record_llm_call(
            call_purpose="baseline_q",
            prompt_name=result.get("prompt_name", "baseline_q"),
            prompt_version=result.get("prompt_version", "v0"),
            model=result.get("model", "unknown"),
            input_text=_build_input_text(topic, keywords, forbidden),
            latency_ms=result.get("latency_ms", 0),
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            output_text=result.get("output_text"),
            output_json=result.get("output_json"),
            retry_count=result.get("retry_count", 0),
            fallback_used=fallback_used,
            validation_result=validation_result,
        )
    except Exception:
        logger.exception("baseline_service: failed to record LLM call")


def generate_baseline_questions(
    topic: str,
    keywords: list[str],
    must_cover_count: int,
    forbidden: list[str],
) -> BaselineQuestions:
    """Generate 3 baseline diagnostic questions honoring the keyword whitelist.

    Up to ``_MAX_ATTEMPTS`` LLM calls are made; each is followed by a
    ``keyword_coverage_check``. On exhaustion the preset ``baseline_q`` fallback
    is served and ``fallback_used`` is set to True.
    """
    variables = {
        "topic": topic,
        "description": "",
        "keywords": keywords,
        "must_cover_count": must_cover_count,
        "forbidden": forbidden,
    }

    fallback_used = 0
    accepted: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            candidate = complete(
                prompt_name="baseline_q",
                variables=variables,
                max_attempts=1,
            )
        except Exception as exc:
            logger.warning(
                "generate_baseline_questions: attempt %d/%d failed: %s",
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
            last_result = None
            continue

        last_result = candidate
        payload = candidate.get("output_json") or {}
        question_dicts = payload.get("questions") or []
        if question_dicts and keyword_coverage_check(question_dicts, keywords):
            accepted = candidate
            accepted["retry_count"] = attempt - 1
            break
        logger.warning(
            "generate_baseline_questions: attempt %d/%d failed coverage check",
            attempt,
            _MAX_ATTEMPTS,
        )

    if accepted is None:
        accepted = _fallback_result()
        fallback_used = 1

    _record(accepted, topic, keywords, forbidden, fallback_used)

    payload = accepted.get("output_json") or {}
    questions = _parse_questions(payload)
    return BaselineQuestions(
        questions=questions,
        raw=payload,
        fallback_used=bool(fallback_used),
    )


__all__ = ["BaselineQuestion", "BaselineQuestions", "generate_baseline_questions"]