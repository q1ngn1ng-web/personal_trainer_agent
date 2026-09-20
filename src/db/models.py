from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, ClassVar, Self

logger = logging.getLogger("src.db.models")


def _loads(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.warning("Could not decode JSON model field")
        return value


class RowModel:
    json_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build a model from a SQLite row and decode JSON fields."""
        values = dict(row)
        for name in cls.json_fields:
            if name in values:
                values[name] = _loads(values[name])
        allowed = set(getattr(cls, "__dataclass_fields__", {}))
        return cls(**{key: value for key, value in values.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a dictionary."""
        return asdict(self)  # type: ignore[arg-type]


@dataclass
class Training(RowModel):
    id: int
    topic: str
    status: str = "draft"
    goal_json: Any = None
    goal_confirmed_at: str | None = None
    clarification_rounds: int = 0
    keywords: Any = None
    must_cover_count: int = 2
    forbidden: Any = None
    directory: str | None = None
    baseline_score: float = 0.0
    baseline_level: str | None = None
    targets: Any = None
    review_items: Any = None
    pretrain_checklist: Any = None
    schedule: Any = None
    materials: Any = None
    current_week: int = 1
    last_review_at: str | None = None
    created_at: str = ""
    last_active_at: str | None = None

    json_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "goal_json",
            "keywords",
            "forbidden",
            "targets",
            "review_items",
            "pretrain_checklist",
            "schedule",
            "materials",
        }
    )


@dataclass
class DailyLog(RowModel):
    id: int
    training_id: int
    log_date: str
    total_tasks: int = 0
    completed_count: int = 0
    recall_questions_total: int = 0
    recall_questions_correct: int = 0
    recall_success_rate: float | None = None
    three_reflections: Any = None
    reflection_submitted_at: str | None = None
    created_at: str = ""

    json_fields: ClassVar[frozenset[str]] = frozenset({"three_reflections"})


@dataclass
class BaselineHistory(RowModel):
    id: int
    training_id: int
    baseline_score: float
    dimension_scores: Any = None
    recorded_at: str = ""

    json_fields: ClassVar[frozenset[str]] = frozenset({"dimension_scores"})


@dataclass
class LLMCall(RowModel):
    id: int
    training_id: int | None
    call_purpose: str
    prompt_name: str
    prompt_version: str
    model: str
    input_text: str
    output_text: str | None
    output_json: Any
    validation_result: str | None
    retry_count: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    failure_reason: str | None
    fallback_used: int
    created_at: str

    json_fields: ClassVar[frozenset[str]] = frozenset({"output_json"})


@dataclass
class ReviewArchive(RowModel):
    id: int
    training_id: int
    week_start: str
    metrics: Any
    llm_suggestions: Any
    user_action: str
    created_at: str

    json_fields: ClassVar[frozenset[str]] = frozenset({"metrics", "llm_suggestions"})


@dataclass
class DailyLogTask(RowModel):
    id: int
    daily_log_id: int
    task_type: str | None = None
    task_ref: str | None = None
    completed: int = 0
    completed_at: str | None = None
    is_required: int = 1


@dataclass
class Source(RowModel):
    """一条训练资料来源（AI 生成 / 上传文件 / 粘贴文本 / 网络 URL）。"""

    id: int
    training_id: int
    type: str
    title: str
    origin: str | None = None
    origin_url: str | None = None
    fetched_at: str | None = None
    snapshot_text: str | None = None
    org_id: int | None = None
    scope: str = "personal"
    enabled: int = 1
    checksum: str | None = None
    parse_status: str = "pending"
    parse_error: str | None = None
    imported_at: str = ""


@dataclass
class SourceChunk(RowModel):
    """来源解析后的一段切片。"""

    id: int
    source_id: int
    ordinal: int
    heading_path: str | None
    text: str
    char_count: int


@dataclass
class EdgeAssessment(RowModel):
    """理解边缘探测的一条结果（一个知识点一题）。"""

    id: int
    training_id: int
    knowledge_point: str
    heading_path: str | None = None
    difficulty: int = 1
    question: str = ""
    reference_answer: str | None = None
    answer: str | None = None
    verdict: str | None = None
    state: str | None = None
    created_at: str = ""


@dataclass
class TrainingItem(RowModel):
    """路径里的一个训练项。``difficulty_basis`` / ``source_chunk_ids`` 是 JSON。"""

    id: int
    stage_id: int
    ordinal: int
    title: str
    item_key: str | None = None
    item_type: str | None = None
    difficulty_tier: int | None = None
    difficulty_basis: Any = None
    knowledge_point: str | None = None
    source_chunk_ids: Any = None
    status: str = "pending"
    mastered_at: str | None = None
    created_at: str = ""

    json_fields: ClassVar[frozenset[str]] = frozenset({"difficulty_basis", "source_chunk_ids"})


@dataclass
class PracticeAttempt(RowModel):
    """一次作答记录（客观表现的原子数据）。"""

    id: int
    training_id: int
    item_key: str
    plan_id: int | None = None
    round_index: int | None = None
    result: str = "fail"
    source: str = "self"
    note: str | None = None
    created_at: str = ""


@dataclass
class Assessment(RowModel):
    """一次测验批次。"""

    id: int
    training_id: int
    plan_id: int | None = None
    trigger: str = "scheduled"
    status: str = "in_progress"
    question_count: int = 0
    score: float | None = None
    passed: int | None = None
    created_at: str = ""
    completed_at: str | None = None


@dataclass
class AssessmentItem(RowModel):
    """测验里的一道题及其作答与判分。"""

    id: int
    assessment_id: int
    ordinal: int
    item_key: str
    knowledge_point: str | None = None
    question: str = ""
    reference_answer: str | None = None
    is_variant: int = 1
    user_answer: str | None = None
    verdict: str | None = None
    reason: str | None = None
    created_at: str = ""


@dataclass
class PathStage(RowModel):
    """路径的一个阶段。"""

    id: int
    path_id: int
    ordinal: int
    title: str
    goal: str | None = None
    estimated_minutes: int = 0
    status: str = "locked"


@dataclass
class TrainingPath(RowModel):
    """一条训练路径（可有多版本，旧版本标 superseded）。"""

    id: int
    training_id: int
    version: int = 1
    status: str = "draft"
    mode: str = "mastery"
    horizon_weeks: int | None = None
    weekly_frequency: int | None = None
    daily_budget_minutes: int | None = None
    budget_minutes: int | None = None
    planned_minutes: int | None = None
    created_at: str = ""
    confirmed_at: str | None = None


@dataclass
class LearningSignal(RowModel):
    """一条学习信号（四失）。"""

    id: int
    training_id: int
    item_id: int | None = None
    signal_type: str = ""
    raw_text: str | None = None
    confidence: float | None = None
    created_at: str = ""


@dataclass
class AdjustmentLog(RowModel):
    """一次调整（含被冲突规则拦截的情形）。"""

    id: int
    training_id: int
    item_id: int | None = None
    signal_type: str | None = None
    action: str | None = None
    reason: str | None = None
    detail: Any = None
    blocked: int = 0
    created_at: str = ""

    json_fields: ClassVar[frozenset[str]] = frozenset({"detail"})


class Element(str, Enum):
    TRAINING_GOAL = "training_goal"
    BASELINE = "baseline"
    STAGED_TARGETS = "staged_targets"
    MATERIALS = "materials"
    REVIEW_ITEMS = "review_items"
    SCHEDULE = "schedule"
    RECALL_PRACTICE = "recall_practice"
    THREE_REFLECTIONS = "three_reflections"
    REWARD = "reward"
    WEEKLY_REVIEW = "weekly_review"
