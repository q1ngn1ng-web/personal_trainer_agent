"""目标澄清服务：自由文本 → 多轮追问 → 结构化目标草案 → 用户确认。

对应 OpenSpec change ``goal-clarification-confirm``。
约束（ADR-0001 / ADR-0004）：**LLM 只产出草案与追问，状态迁移由规则层执行。**
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.goal import (
    CLARIFY_HARD_LIMIT,
    CLARIFY_SOFT_LIMIT,
    GOAL_SCHEMA_VERSION,
    GoalDraft,
    GoalFieldSource,
    TrainingStatus,
    assert_transition,
    build_inferred_acceptance,
    merge_goal,
    next_action,
    suggested_level,
)
from src.db import queries
from src.db.models import Training
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY

logger = logging.getLogger("src.services.goal_clarification_service")

_PURPOSE = "goal_clarification"


@dataclass
class ClarificationSession:
    """一次澄清会话的可展示状态。"""

    training_id: int
    topic: str
    draft: GoalDraft
    missing_fields: tuple[str, ...] = ()
    rounds: int = 0
    action: str = "ask"  # ask | suggest | close
    question: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def can_confirm(self) -> bool:
        return self.draft.is_complete()

    @property
    def inferred_fields(self) -> list[str]:
        return [
            name
            for name, source in self.draft.field_sources.items()
            if source == GoalFieldSource.INFERRED.value
        ]


def _load_state(training: Training) -> dict[str, Any]:
    payload = training.goal_json
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            logger.warning("goal_clarification: could not decode goal_json")
    return {}


def _history_to_text(history: list[dict[str, str]]) -> str:
    if not history:
        return "（暂无）"
    return "\n".join(
        f"第 {index + 1} 轮追问: {item.get('question', '')}\n用户回答: {item.get('answer', '')}"
        for index, item in enumerate(history)
    )


def _call_llm(topic: str, known: dict[str, Any], history: list[dict[str, str]], rounds: int) -> dict[str, Any]:
    variables = {
        "description": topic,
        "known": json.dumps(known, ensure_ascii=False),
        "history": _history_to_text(history),
        "rounds": rounds,
    }
    result = complete(_PURPOSE, variables, schema=SCHEMA_REGISTRY[_PURPOSE])
    output_json = result.get("output_json") or {}
    try:
        queries.record_llm_call(
            call_purpose=_PURPOSE,
            prompt_name=result["prompt_name"],
            prompt_version=result["prompt_version"],
            model=result["model"],
            input_text=json.dumps(variables, ensure_ascii=False),
            latency_ms=result["latency_ms"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            output_text=result.get("output_text"),
            output_json=output_json,
            retry_count=result["retry_count"],
            fallback_used=1 if result["retry_count"] >= 3 else 0,
            validation_result="pass" if output_json else "fail",
        )
    except Exception:  # pragma: no cover - 审计失败不阻塞主流程
        logger.exception("goal_clarification: failed to record LLM call")
    return result


def _apply_suggestions(draft: GoalDraft, missing: tuple[str, ...]) -> list[str]:
    """软限 / 硬限到达后，用建议值补全仍然缺失的字段，返回被补的字段名。"""
    filled: list[str] = []
    for name in missing:
        if name == "level":
            draft.level = suggested_level(draft.content)
            draft.field_sources["level"] = GoalFieldSource.INFERRED.value
            filled.append(name)
        elif name == "acceptance":
            draft.acceptance = build_inferred_acceptance(draft.content)
            draft.field_sources["acceptance"] = GoalFieldSource.INFERRED.value
            filled.append(name)
    return filled


def _build_session(
    training: Training,
    topic: str,
    output: dict[str, Any],
    rounds: int,
    history: list[dict[str, str]],
    previous_missing: tuple[str, ...],
    fallback_used: bool,
) -> ClarificationSession:
    llm_draft = output.get("draft") if isinstance(output.get("draft"), dict) else {}
    merged = merge_goal(llm_draft, locked={"content": topic}, locked_sources={"content": GoalFieldSource.USER_INPUT.value})

    # 用户回答过的字段：LLM 未标 inferred 时视为 user_reply
    if rounds > 0:
        for name in previous_missing:
            if merged.value_of(name) not in (None, "") and merged.field_sources.get(name) != GoalFieldSource.INFERRED.value:
                merged.field_sources[name] = GoalFieldSource.USER_REPLY.value

    missing = merged.missing_fields()
    action = next_action(rounds, missing)
    notes: list[str] = []

    if action == "suggest":
        filled = _apply_suggestions(merged, missing)
        if filled:
            notes.append(
                "以下字段用了系统建议，可以直接采用，也可以自己改：" + "、".join(filled)
            )
            missing = merged.missing_fields()
    elif action == "close":
        filled = _apply_suggestions(merged, missing)
        if filled:
            notes.append(
                "已达到追问上限，以下字段由系统给出建议值（可修改）：" + "、".join(filled)
            )
            missing = merged.missing_fields()

    question = ""
    if action == "ask" and missing:
        question = str(output.get("follow_up_question") or "").strip()
        if not question:
            question = f"请补充「{missing[0]}」：{_default_question(missing[0])}"
    elif action == "suggest":
        question = "以上建议值如有不合适的地方，直接告诉我即可。"

    return ClarificationSession(
        training_id=training.id,
        topic=topic,
        draft=merged,
        missing_fields=missing,
        rounds=rounds,
        action=action,
        question=question,
        history=history,
        confidence=float(output.get("confidence") or 0.0),
        fallback_used=fallback_used,
        notes=notes,
    )


def _default_question(field_name: str) -> str:
    return {
        "content": "你想训练的具体内容是什么？",
        "level": "你希望达到什么程度？（了解 / 会用 / 熟练 / 能讲清）",
        "acceptance": "怎样才算学会？给一个能验证的说法，比如正确率、完成量或能讲出来。",
    }.get(field_name, "请补充这一项。")


def _persist(training_id: int, session: ClarificationSession) -> None:
    payload: dict[str, Any] = session.draft.to_snapshot(session.rounds)
    payload["history"] = session.history
    payload["confirmed"] = False
    queries.update_training(
        training_id,
        goal_json=payload,
        clarification_rounds=session.rounds,
        status=TrainingStatus.PENDING_CONFIRM.value,
    )


def start_session(topic: str) -> ClarificationSession:
    """创建 draft 训练并发起第一轮澄清。"""
    text = (topic or "").strip()
    if not text:
        raise ValueError("描述不能为空")

    training = queries.create_training(topic=text, status=TrainingStatus.DRAFT.value)
    assert_transition(TrainingStatus.DRAFT.value, TrainingStatus.PENDING_CONFIRM.value)

    result = _call_llm(text, {"topic": text}, [], 0)
    output = result.get("output_json") or {}
    session = _build_session(
        training,
        text,
        output,
        rounds=0,
        history=[],
        previous_missing=(),
        fallback_used=not output,
    )
    _persist(training.id, session)
    return session


def continue_session(training_id: int, answer: str) -> ClarificationSession:
    """把用户回答并入会话，进入下一轮澄清。"""
    training = queries.get_training(training_id)
    if training is None:
        raise ValueError(f"training not found: {training_id}")

    state = _load_state(training)
    history = list(state.get("history") or [])
    previous_missing = tuple(session_field for session_field in ("level", "acceptance"))

    rounds = int(training.clarification_rounds or 0) + 1
    history.append({"question": "", "answer": (answer or "").strip()})

    known = {name: state.get(name) for name in ("content", "level", "acceptance") if state.get(name)}
    result = _call_llm(training.topic, known, history, rounds)
    output = result.get("output_json") or {}
    session = _build_session(
        training,
        training.topic,
        output,
        rounds=rounds,
        history=history,
        previous_missing=previous_missing,
        fallback_used=not output,
    )
    _persist(training_id, session)
    return session


def confirm(
    training_id: int,
    override: dict[str, Any] | None = None,
) -> Training:
    """用户确认目标：写快照 + 状态迁移到 confirmed。"""
    training = queries.get_training(training_id)
    if training is None:
        raise ValueError(f"training not found: {training_id}")

    state = _load_state(training)
    rounds = int(training.clarification_rounds or 0)

    locked = {name: state.get(name) for name in ("content", "level", "acceptance") if state.get(name)}
    locked_sources = dict(state.get("field_sources") or {})
    if override:
        for name, value in override.items():
            if value not in (None, ""):
                locked[name] = value
                locked_sources[name] = GoalFieldSource.USER_REPLY.value

    draft = merge_goal(state, locked=locked, locked_sources=locked_sources)
    if not draft.is_complete():
        raise ValueError(f"目标仍有缺失字段：{draft.missing_fields()}")

    snapshot = draft.to_snapshot(rounds)
    snapshot["confirmed"] = True

    assert_transition(training.status, TrainingStatus.CONFIRMED.value)
    updated = queries.update_training(
        training_id,
        status=TrainingStatus.CONFIRMED.value,
        goal_json=snapshot,
        goal_confirmed_at=queries._now(),
    )
    if updated is None:  # pragma: no cover - update returns None only when row missing
        raise ValueError(f"training not found: {training_id}")
    return updated


def load_session(training_id: int) -> ClarificationSession | None:
    """从库里恢复会话状态（用于页面刷新后继续澄清）。"""
    training = queries.get_training(training_id)
    if training is None:
        return None
    state = _load_state(training)
    if not state:
        return None
    draft = merge_goal(state, locked=state, locked_sources=dict(state.get("field_sources") or {}))
    missing = draft.missing_fields()
    rounds = int(training.clarification_rounds or 0)
    return ClarificationSession(
        training_id=training.id,
        topic=training.topic,
        draft=draft,
        missing_fields=missing,
        rounds=rounds,
        action=next_action(rounds, missing),
        question="",
        history=list(state.get("history") or []),
    )


__all__ = [
    "CLARIFY_HARD_LIMIT",
    "CLARIFY_SOFT_LIMIT",
    "GOAL_SCHEMA_VERSION",
    "ClarificationSession",
    "confirm",
    "continue_session",
    "load_session",
    "start_session",
]
