from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class Element(Enum):
    """十要素。Each member corresponds to one of the ten training files."""

    OBJECT = ("00_对象档案", "对象", "对象档案")
    BASELINE = ("01_基线诊断", "基", "基线诊断")
    GOAL = ("02_训练目标", "的", "训练目标")
    MATERIAL = ("03_资料库", "器", "资料库")
    SCHEDULE = ("04_复习日历", "序", "复习日历")
    METHOD = ("05_主动回忆", "术", "主动回忆")
    ENVIRONMENT = ("06_环境心流", "境", "环境心流")
    REWARD = ("07_奖励机制", "奖", "奖励机制")
    REFLECTION = ("08_三省吾身", "省", "三省吾身")
    BOUNDARY = ("09_边界与止", "止", "边界与止")

    def __init__(self, file_prefix: str, chinese_name: str, description: str) -> None:
        self.file_prefix = file_prefix
        self.chinese_name = chinese_name
        self.description = description

    @classmethod
    def from_prefix(cls, prefix: str) -> Element:
        """Reverse lookup by ``file_prefix`` (e.g. ``"03_资料库"``)."""
        for member in cls:
            if member.file_prefix == prefix:
                return member
        raise ValueError(f"No Element with file_prefix: {prefix!r}")

    @classmethod
    def ten(cls) -> list[Element]:
        """Return all ten elements in canonical order."""
        return list(cls)


class TrainingStatus(Enum):
    CREATED = "created"
    DRAFT = "draft"
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    FAILED = "failed"


class BaselineLevel(Enum):
    HIGH = "high"
    MID = "mid"
    LOW = "low"
