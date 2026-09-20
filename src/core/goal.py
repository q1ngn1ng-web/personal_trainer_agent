"""目标澄清的领域逻辑：状态机、字段来源、验收判据校验、合并与追问控制。

本模块只包含纯函数与数据结构，不依赖数据库与 LLM，便于单测。
对应 OpenSpec change ``goal-clarification-confirm`` 与 ADR-0004 / ADR-0005。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

GOAL_SCHEMA_VERSION: str = "1.0.0"

#: 目标草案的必填字段
GOAL_FIELDS: tuple[str, ...] = ("content", "level", "acceptance")

#: 追问软限：到达后给出建议值，并提示可直接采用
CLARIFY_SOFT_LIMIT: int = 2
#: 追问硬限：到达后强制收口，缺失字段标记为系统推断
CLARIFY_HARD_LIMIT: int = 3

#: 目标等级枚举
LEVELS: tuple[str, ...] = ("了解", "会用", "熟练", "能讲清")

#: 验收判据的量化口径
ACCEPTANCE_METRICS: tuple[str, ...] = ("accuracy", "volume", "speed", "streak")

#: 纯主观形容词：出现即判定判据不成立
VAGUE_MARKERS: tuple[str, ...] = (
    "比较熟练", "差不多", "感觉还行", "还行", "基本会", "大概会",
    "随便", "都可以", "了解一下就行", "看得懂就行",
)

#: 可观察行为的标志词：用于识别质性判据
OBSERVABLE_MARKERS: tuple[str, ...] = (
    "能讲", "会说", "能说", "能写", "能做", "能用", "能复述", "能解释", "能自己",
    "复述", "解释", "不看稿", "做出", "完成", "写出来", "讲出来",
    "讲清", "说清", "写清", "用自己的话",
)

_DIGIT_RE = re.compile(r"\d")


class GoalFieldSource(str, Enum):
    """目标字段的来源，决定界面上是否标注"系统建议"。"""

    USER_INPUT = "user_input"
    USER_REPLY = "user_reply"
    INFERRED = "inferred"


class TrainingStatus(str, Enum):
    """训练状态。``created`` 为历史数据兼容，读取时按 ``draft`` 处理。"""

    CREATED = "created"
    DRAFT = "draft"
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    FAILED = "failed"


#: 允许的状态迁移。``pending_confirm -> pending_confirm`` 表示用户改动草案后重新生成。
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    TrainingStatus.CREATED.value: frozenset({TrainingStatus.DRAFT.value, TrainingStatus.ARCHIVED.value}),
    TrainingStatus.DRAFT.value: frozenset({TrainingStatus.PENDING_CONFIRM.value, TrainingStatus.ARCHIVED.value}),
    TrainingStatus.PENDING_CONFIRM.value: frozenset(
        {TrainingStatus.PENDING_CONFIRM.value, TrainingStatus.CONFIRMED.value, TrainingStatus.ARCHIVED.value}
    ),
    TrainingStatus.CONFIRMED.value: frozenset(
        {TrainingStatus.ACTIVE.value, TrainingStatus.PENDING_CONFIRM.value, TrainingStatus.ARCHIVED.value}
    ),
    TrainingStatus.ACTIVE.value: frozenset({TrainingStatus.PAUSED.value, TrainingStatus.ARCHIVED.value}),
    TrainingStatus.PAUSED.value: frozenset({TrainingStatus.ACTIVE.value, TrainingStatus.ARCHIVED.value}),
    TrainingStatus.FAILED.value: frozenset({TrainingStatus.DRAFT.value, TrainingStatus.ARCHIVED.value}),
    TrainingStatus.ARCHIVED.value: frozenset(),
}

#: 允许进入生成阶段的状态
GENERATION_READY_STATUSES: frozenset[str] = frozenset({TrainingStatus.CONFIRMED.value})


class InvalidTransitionError(ValueError):
    """状态迁移非法时抛出。"""


def normalize_status(status: str | None) -> str:
    """把历史状态 ``created`` 归一化为 ``draft``。"""
    value = (status or "").strip() or TrainingStatus.DRAFT.value
    return TrainingStatus.DRAFT.value if value == TrainingStatus.CREATED.value else value


def can_transition(current: str | None, target: str) -> bool:
    """判断从 ``current`` 迁移到 ``target`` 是否合法。

    迁移到同一状态视为合法的幂等操作（例如历史状态 ``created`` 归一化后就是 ``draft``）。
    """
    normalized = normalize_status(current)
    if normalized == target:
        return True
    return target in STATUS_TRANSITIONS.get(normalized, frozenset())


def assert_transition(current: str | None, target: str) -> str:
    """校验状态迁移，非法时抛 :class:`InvalidTransitionError`。"""
    if not can_transition(current, target):
        raise InvalidTransitionError(f"illegal status transition: {normalize_status(current)} -> {target}")
    return target


def is_generation_ready(status: str | None) -> bool:
    """当前状态是否允许进入生成阶段（仅 ``confirmed``）。"""
    return normalize_status(status) in GENERATION_READY_STATUSES


@dataclass
class AcceptanceCheck:
    """验收判据的校验结果。"""

    ok: bool
    kind: str = "invalid"  # quantitative | qualitative | invalid
    reason: str = ""
    normalized: dict[str, Any] | None = None
    needs_check: bool = False


def _target_is_valid(metric: str, target: Any) -> bool:
    if isinstance(target, bool) or not isinstance(target, (int, float)):
        return False
    value = float(target)
    if metric == "accuracy":
        # 同时接受比例（0-1）与百分比（0-100）：模型和用户都习惯写 80%
        return 0.0 < value <= 1.0 or 1.0 < value <= 100.0
    return value > 0.0


def normalize_acceptance_target(metric: str, target: Any) -> Any:
    """把百分比统一成比例：accuracy 的 80 → 0.8。其它口径原样返回。"""
    if metric == "accuracy" and not isinstance(target, bool) and isinstance(target, (int, float)):
        value = float(target)
        if 1.0 < value <= 100.0:
            return round(value / 100.0, 6)
    return target


def is_vague(text: str) -> bool:
    """纯主观形容词（或过短）判定为不可用。"""
    stripped = (text or "").strip()
    if len(stripped) < 4:
        return True
    return any(marker in stripped for marker in VAGUE_MARKERS)


def validate_acceptance(value: Any) -> AcceptanceCheck:
    """校验验收标准是否可判定。

    接受两种形状：

    * 量化判据：``{"type": "quantitative", "metric": ..., "target": ...}``
    * 质性判据：``{"type": "qualitative", "statement": ..., "check": ...}``

    纯字符串按自由文本粗判：含数字视为量化候选；含可观察行为词视为质性候选
    （``needs_check=True``，由系统补充检查方式）；纯主观形容词一律不通过。
    """
    if isinstance(value, dict):
        kind = str(value.get("type", "")).strip()
        if kind == "quantitative":
            metric = str(value.get("metric", "")).strip()
            target = value.get("target")
            if metric not in ACCEPTANCE_METRICS:
                return AcceptanceCheck(False, "invalid", f"unknown metric: {metric!r}")
            if not _target_is_valid(metric, target):
                return AcceptanceCheck(False, "invalid", "target out of range")
            normalized = dict(value)
            normalized["target"] = normalize_acceptance_target(metric, target)
            return AcceptanceCheck(True, "quantitative", "", normalized)
        if kind == "qualitative":
            statement = str(value.get("statement", "")).strip()
            check = str(value.get("check", "")).strip()
            if is_vague(statement):
                return AcceptanceCheck(False, "invalid", "statement is too vague")
            if not check:
                return AcceptanceCheck(
                    True, "qualitative", "missing check method", dict(value), needs_check=True
                )
            return AcceptanceCheck(True, "qualitative", "", dict(value))
        return AcceptanceCheck(False, "invalid", f"unknown acceptance type: {kind!r}")

    text = str(value or "").strip()
    if is_vague(text):
        return AcceptanceCheck(False, "invalid", "vague acceptance criteria")
    if _DIGIT_RE.search(text):
        return AcceptanceCheck(True, "quantitative", "free text with numbers")
    if any(marker in text for marker in OBSERVABLE_MARKERS):
        return AcceptanceCheck(
            True,
            "qualitative",
            "observable behaviour, check method required",
            {"type": "qualitative", "statement": text, "check": ""},
            needs_check=True,
        )
    return AcceptanceCheck(False, "invalid", "acceptance criteria is not judgeable")


@dataclass
class GoalDraft:
    """结构化目标草案。三个字段都是值，不是布尔标记。"""

    content: str = ""
    level: str = ""
    acceptance: Any = None
    field_sources: dict[str, str] = field(default_factory=dict)

    def value_of(self, name: str) -> Any:
        return getattr(self, name, None)

    def missing_fields(self) -> tuple[str, ...]:
        """返回缺失或不合格的必填字段。"""
        missing: list[str] = []
        if not str(self.content or "").strip():
            missing.append("content")
        if not str(self.level or "").strip():
            missing.append("level")
        elif str(self.level).strip() not in LEVELS:
            missing.append("level")
        if self.acceptance is None or not validate_acceptance(self.acceptance).ok:
            missing.append("acceptance")
        return tuple(missing)

    def is_complete(self) -> bool:
        return not self.missing_fields()

    def to_snapshot(self, clarification_rounds: int = 0) -> dict[str, Any]:
        """生成落库快照，含字段来源与 schema 版本。"""
        return {
            "content": str(self.content or "").strip(),
            "level": str(self.level or "").strip(),
            "acceptance": self.acceptance,
            "field_sources": dict(self.field_sources),
            "schema_version": GOAL_SCHEMA_VERSION,
            "clarification_rounds": int(clarification_rounds),
        }


def merge_goal(
    llm_draft: dict[str, Any] | None,
    locked: dict[str, Any] | None = None,
    locked_sources: dict[str, str] | None = None,
) -> GoalDraft:
    """合并 LLM 草案与用户给出的值。

    优先级铁律：**用户显式值 > LLM 输出**。AI 不得覆盖用户已给出或已确认的字段。
    """
    payload = dict(llm_draft or {})
    # 允许直接传入 LLM 的整体输出（形如 {"draft": {...}}），也允许只传 draft 本身
    if isinstance(payload.get("draft"), dict):
        payload = dict(payload["draft"])
    draft = payload
    locked = {key: value for key, value in (locked or {}).items() if value not in (None, "")}
    locked_sources = dict(locked_sources or {})

    field_sources: dict[str, str] = {}
    resolved: dict[str, Any] = {}
    for name in GOAL_FIELDS:
        if name in locked:
            resolved[name] = locked[name]
            field_sources[name] = locked_sources.get(name, GoalFieldSource.USER_REPLY.value)
        else:
            value = draft.get(name)
            resolved[name] = value
            if value not in (None, ""):
                source = str(draft.get("field_sources", {}).get(name, "") or "")
                field_sources[name] = source or GoalFieldSource.INFERRED.value
            else:
                field_sources[name] = GoalFieldSource.INFERRED.value

    # 用户原始描述永远算 user_input
    if "content" in locked and locked_sources.get("content") is None:
        field_sources["content"] = GoalFieldSource.USER_INPUT.value

    return GoalDraft(
        content=resolved.get("content") or "",
        level=resolved.get("level") or "",
        acceptance=resolved.get("acceptance"),
        field_sources=field_sources,
    )


def next_action(rounds: int, missing: tuple[str, ...]) -> str:
    """决定下一步：``ask`` 继续追问 / ``suggest`` 给建议值 / ``close`` 收口。"""
    if not missing:
        return "close"
    if rounds >= CLARIFY_HARD_LIMIT:
        return "close"
    if rounds >= CLARIFY_SOFT_LIMIT:
        return "suggest"
    return "ask"


def suggested_level(theme: str = "") -> str:
    """LLM 不可用时的档位建议。"""
    return "会用"


def build_inferred_acceptance(theme: str = "") -> dict[str, Any]:
    """达到硬限仍缺失验收判据时，给出一条可观察的质性建议。"""
    statement = f"能不看稿讲清「{theme}」的核心内容" if theme else "能不看稿讲清这个主题的核心内容"
    return {"type": "qualitative", "statement": statement, "check": "口头讲一遍并录音回听"}


__all__ = [
    "ACCEPTANCE_METRICS",
    "CLARIFY_HARD_LIMIT",
    "CLARIFY_SOFT_LIMIT",
    "GENERATION_READY_STATUSES",
    "GOAL_FIELDS",
    "GOAL_SCHEMA_VERSION",
    "GoalDraft",
    "GoalFieldSource",
    "InvalidTransitionError",
    "LEVELS",
    "STATUS_TRANSITIONS",
    "TrainingStatus",
    "AcceptanceCheck",
    "assert_transition",
    "build_inferred_acceptance",
    "can_transition",
    "is_generation_ready",
    "is_vague",
    "merge_goal",
    "next_action",
    "normalize_status",
    "suggested_level",
    "validate_acceptance",
]
