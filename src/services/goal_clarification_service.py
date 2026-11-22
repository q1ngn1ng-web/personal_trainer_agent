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
    DEFAULT_HORIZON_DAYS,
    DEFAULT_SESSION_COUNT,
    GOAL_SCHEMA_VERSION,
    GoalDraft,
    GoalFieldSource,
    SESSION_COUNT_MAX,
    TrainingStatus,
    assert_transition,
    build_inferred_acceptance,
    merge_goal,
    next_action,
    normalize_status,
    suggested_level,
    validate_horizon_days,
    validate_session_count,
)
from src.db import queries
from src.db.models import Training
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY

logger = logging.getLogger("src.services.goal_clarification_service")

_PURPOSE = "goal_clarification"

#: 用户自定义节奏的训练排期模式（user-defined-training-plan 2.5；存量默认 legacy_v21）
SESSION_SCHEDULE_MODE: str = "session_ratio"

#: 等级 → 节奏推荐【待校准】：澄清步知识点未知，先按等级给建议
_LEVEL_SESSION_RECOMMEND: dict[str, int] = {"了解": 2, "会用": 3, "熟练": 3, "能讲清": 4}
_LEVEL_HORIZON_RECOMMEND: dict[str, int] = {"了解": 14, "会用": 14, "熟练": 21, "能讲清": 21}


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
    title: str = ""
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
    # 调用审计（成功/降级/失败）由统一客户端写入 llm_calls
    return complete(_PURPOSE, variables, schema=SCHEMA_REGISTRY[_PURPOSE])


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
        elif name == "horizon_days":
            # 节奏默认值（UI 卡片预填同一组）：无 UI 的流程在建议阶段自动补全
            draft.horizon_days = DEFAULT_HORIZON_DAYS
            draft.field_sources["horizon_days"] = GoalFieldSource.INFERRED.value
            filled.append(name)
        elif name == "session_count":
            draft.session_count = DEFAULT_SESSION_COUNT
            draft.field_sources["session_count"] = GoalFieldSource.INFERRED.value
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
    locked: dict[str, Any] | None = None,
    locked_sources: dict[str, str] | None = None,
) -> ClarificationSession:
    llm_draft = output.get("draft") if isinstance(output.get("draft"), dict) else {}
    merged = merge_goal(
        llm_draft,
        locked={"content": topic, **(locked or {})},
        locked_sources={"content": GoalFieldSource.USER_INPUT.value, **(locked_sources or {})},
    )

    # 用户回答过的字段：来源仍是推断（或缺失）时归为 user_reply；
    # 用户已显式编辑过的（user_input）不得降级（card 编辑与对话补充不互相覆盖）
    if rounds > 0:
        for name in previous_missing:
            if merged.value_of(name) not in (None, "") and merged.field_sources.get(
                name, GoalFieldSource.INFERRED.value
            ) == GoalFieldSource.INFERRED.value:
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

    # AI 生成的训练标题（schema 顶层 title）；缺省回落描述前 12 字
    suggested_title = str(output.get("title") or "").strip()
    if not suggested_title and topic:
        suggested_title = topic.strip()[:12]

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
        title=suggested_title,
        notes=notes,
    )


def _default_question(field_name: str) -> str:
    return {
        "content": "你想训练的具体内容是什么？",
        "level": "你希望达到什么程度？（了解 / 会用 / 熟练 / 能讲清）",
        "acceptance": "怎样才算学会？给一个能验证的说法，比如正确率、完成量或能讲出来。",
        # 节奏字段由 UI 控件收集（提示词第 6/7 条），对话不追问——兜底文案引导卡片
        "horizon_days": "请在「训练节奏」卡片选择训练总时长（无需文字回答）。",
        "session_count": "请在「训练节奏」卡片选择训练次数（无需文字回答）。",
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


def _user_locked_fields(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """从持久化状态里取出「用户显式给过值」的字段（user_input/user_reply 来源）。

    这些字段在重建草案时作为 locked 传入——**LLM 输出 MUST NOT 覆盖用户显式值**
    （ADR-0004 铁律）。修复：此前 continue_session 只锁 content，用户设过的节奏/
    等级/验收标准每轮被 LLM 草案冲掉（用户感知为"没改的内容也在变"）。
    推断（inferred）来源的字段不锁——留给 LLM 在下一轮继续完善。
    """
    sources = dict(state.get("field_sources") or {})
    locked: dict[str, Any] = {}
    locked_sources: dict[str, str] = {}
    for name in ("content", "level", "acceptance", "horizon_days", "session_count"):
        value = state.get(name)
        if value in (None, "", 0):
            continue
        source = sources.get(name, GoalFieldSource.INFERRED.value)
        if source == GoalFieldSource.INFERRED.value and name not in ("horizon_days", "session_count"):
            continue
        locked[name] = value
        locked_sources[name] = source if source != GoalFieldSource.INFERRED.value else GoalFieldSource.USER_INPUT.value
    return locked, locked_sources


def continue_session(training_id: int, answer: str) -> ClarificationSession:
    """把用户回答并入会话，进入下一轮澄清。

    用户已显式给值的字段（含节奏卡片设置）全程锁定，不随 LLM 草案重置。
    """
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
    locked, locked_sources = _user_locked_fields(state)
    session = _build_session(
        training,
        training.topic,
        output,
        rounds=rounds,
        history=history,
        previous_missing=previous_missing,
        fallback_used=not output,
        locked=locked,
        locked_sources=locked_sources,
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

    locked = {
        name: state.get(name)
        for name in ("content", "level", "acceptance", "horizon_days", "session_count")
        if state.get(name) not in (None, "")
    }
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


def _draft_view_of_state(state: dict[str, Any]) -> dict[str, Any]:
    """把持久化状态包成 merge_goal 认识的 LLM 输出形状（保住 inferred 字段）。

    _build_session 只读 ``output["draft"]``——直接传 state 会让 AI 推断的
    level/acceptance 被当作"无草案"清空（用户报"填完了还是不能确认"的根因）。
    """
    return {
        "draft": {
            name: state.get(name)
            for name in ("content", "level", "acceptance")
            if state.get(name) not in (None, "")
        },
        "field_sources": dict(state.get("field_sources") or {}),
    }


def set_pace(training_id: int, horizon_days: int, session_count: int) -> ClarificationSession:
    """UI 节奏卡片提交（change user-defined-training-plan 1.1/1.3）。

    值以 user_input 来源写入草案并落库；同时把训练标记为 session_ratio 排期模式。
    重建会话但不调 LLM（state 即草案输入）。
    """
    training = queries.get_training(training_id)
    if training is None:
        raise ValueError(f"training not found: {training_id}")
    if str(normalize_status(training.status)) not in (
        TrainingStatus.DRAFT.value,
        TrainingStatus.PENDING_CONFIRM.value,
    ):
        raise ValueError("澄清会话已结束，不能再修改训练节奏")

    days = validate_horizon_days(horizon_days)
    count = validate_session_count(session_count)

    state = _load_state(training)
    state["horizon_days"] = days
    state["session_count"] = count
    sources = dict(state.get("field_sources") or {})
    sources["horizon_days"] = GoalFieldSource.USER_INPUT.value
    sources["session_count"] = GoalFieldSource.USER_INPUT.value
    state["field_sources"] = sources

    # 语义字段以 state 为「AI/既有草案」传入（保住 inferred 的 level/acceptance），
    # 节奏以 locked 传入——此前直接传 state 会被 _build_session 当作无 draft 而清空
    draft_view = _draft_view_of_state(state)
    session = _build_session(
        training,
        training.topic,
        draft_view,
        rounds=int(training.clarification_rounds or 0),
        history=list(state.get("history") or []),
        previous_missing=(),
        fallback_used=False,
        locked={"horizon_days": days, "session_count": count},
        locked_sources={
            "horizon_days": GoalFieldSource.USER_INPUT.value,
            "session_count": GoalFieldSource.USER_INPUT.value,
        },
    )
    _persist(training_id, session)
    queries.update_training(training_id, schedule_mode=SESSION_SCHEDULE_MODE)
    return session


def update_draft_fields(training_id: int, values: dict[str, Any]) -> ClarificationSession:
    """用户在澄清卡片直接编辑语义字段（content/level/acceptance）——**不走 LLM**。

    校验通过的字段以 user_input 来源写入草案，重算 missing_fields/can_confirm；
    任一字段非法整批拒绝。节奏字段仍走 set_pace（含 schedule_mode 切换）。
    """
    from src.core.goal import LEVELS, validate_acceptance

    training = queries.get_training(training_id)
    if training is None:
        raise ValueError(f"training not found: {training_id}")
    if str(normalize_status(training.status)) not in (
        TrainingStatus.DRAFT.value,
        TrainingStatus.PENDING_CONFIRM.value,
    ):
        raise ValueError("澄清会话已结束，不能再修改目标草案")

    updates: dict[str, Any] = {}
    if values.get("content") is not None:
        content = str(values["content"]).strip()
        if len(content) < 4:
            raise ValueError("学习内容太短——多用一句话完整描述")
        updates["content"] = content
    if values.get("level") is not None:
        level = str(values["level"]).strip()
        if level not in LEVELS:
            raise ValueError("目标等级只能是「了解 / 会用 / 熟练 / 能讲清」之一")
        updates["level"] = level
    if values.get("acceptance") is not None:
        check = validate_acceptance(values["acceptance"])
        if not check.ok:
            raise ValueError(f"验收标准不可判定：{check.reason}")
        updates["acceptance"] = check.normalized if check.normalized is not None else values["acceptance"]
    if not updates:
        raise ValueError("没有提供任何可更新的字段")

    state = _load_state(training)
    sources = dict(state.get("field_sources") or {})
    for name, value in updates.items():
        state[name] = value
        sources[name] = GoalFieldSource.USER_INPUT.value
    state["field_sources"] = sources

    locked = {"content": training.topic}
    locked_sources = {"content": GoalFieldSource.USER_INPUT.value}
    user_locked, user_locked_sources = _user_locked_fields(state)
    # 本次编辑的字段必须以新值锁定（覆盖 state 里的旧值）
    locked.update(user_locked)
    locked_sources.update(user_locked_sources)
    locked.update(updates)
    for name in updates:
        locked_sources[name] = GoalFieldSource.USER_INPUT.value

    # 同 set_pace：语义字段走 draft 视图（inferred 不丢），编辑值走 locked
    draft_view = _draft_view_of_state(state)
    session = _build_session(
        training,
        training.topic,
        draft_view,
        rounds=int(training.clarification_rounds or 0),
        history=list(state.get("history") or []),
        previous_missing=(),
        fallback_used=False,
        locked=locked,
        locked_sources=locked_sources,
    )
    _persist(training_id, session)
    return session


def recommend_pace(level: str, knowledge_point_count: int | None = None) -> dict[str, int]:
    """按等级（与可选的知识点数量）给节奏推荐值【待校准】：澄清步知识点未知，先按等级。"""
    sessions = _LEVEL_SESSION_RECOMMEND.get(str(level or "").strip(), DEFAULT_SESSION_COUNT)
    horizon = _LEVEL_HORIZON_RECOMMEND.get(str(level or "").strip(), DEFAULT_HORIZON_DAYS)
    if knowledge_point_count and knowledge_point_count > 10:
        sessions = min(sessions + 1, SESSION_COUNT_MAX)
    return {"horizon_days": horizon, "session_count": sessions}


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
        title=str(training.topic or ""),
    )


__all__ = [
    "CLARIFY_HARD_LIMIT",
    "CLARIFY_SOFT_LIMIT",
    "GOAL_SCHEMA_VERSION",
    "SESSION_SCHEDULE_MODE",
    "ClarificationSession",
    "confirm",
    "continue_session",
    "load_session",
    "recommend_pace",
    "set_pace",
    "update_draft_fields",
    "start_session",
]
