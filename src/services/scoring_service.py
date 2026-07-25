"""Baseline scoring of user answers via the unified LLM client."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.db.queries import record_llm_call
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY

from src.services.baseline_service import BaselineQuestion

logger = logging.getLogger("src.services.scoring_service")

_SCORE_LABEL: dict[str, str] = {
    "mastered": "mastered",
    "partial": "partial",
    "missing": "missing",
}


@dataclass
class QuestionScore:
    """Per-question mastery verdict returned by the LLM scorer."""

    idx: int
    score: str
    notes: str


@dataclass
class ScoringResult:
    """Aggregate scoring outcome across the 3 baseline questions."""

    scores: list[QuestionScore]
    overall_level: str
    partial_topics: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


def _build_input_text(topic: str, questions: list[dict[str, Any]], answers: list[str]) -> str:
    template, _ = PROMPT_REGISTRY["baseline_scoring"]
    schema = SCHEMA_REGISTRY["baseline_scoring"]
    return template.format(
        topic=topic,
        questions=questions,
        answers=answers,
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
    )


def _question_key_terms(question: BaselineQuestion) -> set[str]:
    import re
    raw = (question.question or "").lower()
    cleaned = re.sub(r"[^\w\s]+", " ", raw, flags=0)
    return {token for token in cleaned.split() if len(token) > 2}


def _heuristic_score(
    questions: list[BaselineQuestion],
    user_answers: list[str],
) -> ScoringResult:
    """Compute a coarse mastery verdict without consulting the LLM."""
    scores: list[QuestionScore] = []
    substantive_count = 0
    partial_indices: list[int] = []

    for idx, (question, raw_answer) in enumerate(zip(questions, user_answers)):
        answer = (raw_answer or "").strip()
        answer_lower = answer.lower()
        terms = _question_key_terms(question)
        overlap_terms = {token for token in answer_lower.split() if token in terms}
        is_substantive = len(answer) >= 10 and bool(overlap_terms)

        if is_substantive:
            verdict = "mastered"
            substantive_count += 1
        elif answer:
            verdict = "partial"
            partial_indices.append(idx)
        else:
            verdict = "missing"

        scores.append(
            QuestionScore(
                idx=idx,
                score=verdict,
                notes="heuristic: " + (
                    "matched key terms" if is_substantive else
                    "answered but no key-term overlap" if answer else
                    "no answer"
                ),
            )
        )

    if substantive_count == len(questions) and len(questions) > 0:
        overall = "high"
    elif substantive_count >= max(0, len(questions) - 1) and not partial_indices:
        overall = "mid"
    else:
        overall = "low"

    partial_topics = [
        (questions[i].question[:32] + ("…" if len(questions[i].question) > 32 else ""))
        for i in partial_indices[:2]
    ]

    return ScoringResult(
        scores=scores,
        overall_level=overall,
        partial_topics=partial_topics,
        raw={"source": "heuristic"},
    )


def _record(result: dict[str, Any], topic: str, questions: list[dict[str, Any]], answers: list[str]) -> None:
    validation_result = "pass" if result.get("output_json") else "fail"
    try:
        record_llm_call(
            call_purpose="baseline_scoring",
            prompt_name=result.get("prompt_name", "baseline_scoring"),
            prompt_version=result.get("prompt_version", "v0"),
            model=result.get("model", "unknown"),
            input_text=_build_input_text(topic, questions, answers),
            latency_ms=result.get("latency_ms", 0),
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            output_text=result.get("output_text"),
            output_json=result.get("output_json"),
            retry_count=result.get("retry_count", 0),
            fallback_used=0,
            validation_result=validation_result,
        )
    except Exception:
        logger.exception("score_baseline: failed to record LLM call")


def _record_failure(topic: str, questions: list[dict[str, Any]], answers: list[str], exc: Exception) -> None:
    _, version = PROMPT_REGISTRY["baseline_scoring"]
    try:
        record_llm_call(
            call_purpose="baseline_scoring",
            prompt_name="baseline_scoring",
            prompt_version=version,
            model="unknown",
            input_text=_build_input_text(topic, questions, answers),
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
        logger.exception("score_baseline: failed to persist failure record")


def score_baseline(
    topic: str,
    questions: list[BaselineQuestion],
    user_answers: list[str],
) -> ScoringResult:
    """Score the user's answers to the 3 baseline diagnostic questions."""
    question_dicts = [q.to_dict() for q in questions]
    variables = {
        "topic": topic,
        "questions": question_dicts,
        "answers": list(user_answers),
    }

    try:
        result = complete(prompt_name="baseline_scoring", variables=variables)
    except Exception as exc:
        logger.warning("score_baseline: LLM unavailable, using heuristic: %s", exc)
        _record_failure(topic, question_dicts, list(user_answers), exc)
        return _heuristic_score(questions, user_answers)

    output_json = result.get("output_json") or {}
    raw_scores = output_json.get("scores") or []
    parsed_scores: list[QuestionScore] = []
    for entry in raw_scores:
        if not isinstance(entry, dict):
            continue
        try:
            idx = int(entry.get("question_idx", len(parsed_scores)))
        except (TypeError, ValueError):
            idx = len(parsed_scores)
        score = str(entry.get("score", "missing"))
        if score not in _SCORE_LABEL:
            score = "missing"
        parsed_scores.append(
            QuestionScore(idx=idx, score=score, notes=str(entry.get("notes", "")))
        )

    if not parsed_scores:
        parsed_scores = [
            QuestionScore(idx=0, score="missing", notes="LLM returned no per-question scores")
        ]

    overall = str(output_json.get("overall", "low"))
    if overall not in {"high", "mid", "low"}:
        overall = "low"
    partial_topics = [str(t) for t in (output_json.get("partial_topics") or []) if str(t).strip()]

    _record(result, topic, question_dicts, list(user_answers))

    return ScoringResult(
        scores=parsed_scores,
        overall_level=overall,
        partial_topics=partial_topics,
        raw=output_json,
    )


__all__ = ["QuestionScore", "ScoringResult", "score_baseline"]