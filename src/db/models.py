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
