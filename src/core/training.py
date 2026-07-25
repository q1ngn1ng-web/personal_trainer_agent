from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.core.element import BaselineLevel, TrainingStatus

logger = logging.getLogger(__name__)


@dataclass
class Training:
    id: int | None = None
    topic: str = ""
    status: TrainingStatus = TrainingStatus.CREATED
    keywords: list[str] = field(default_factory=list)
    must_cover_count: int = 2
    forbidden: list[str] = field(default_factory=list)
    directory: Path = field(default_factory=Path)
    baseline_score: float = 0.0
    baseline_level: BaselineLevel = BaselineLevel.LOW
    targets: dict = field(default_factory=dict)
    review_items: list[str] = field(default_factory=list)
    pretrain_checklist: list[dict] = field(default_factory=list)
    schedule: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)
    current_week: int = 1
    last_review_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_active_at: datetime = field(default_factory=datetime.now)

    @property
    def is_active(self) -> bool:
        return self.status == TrainingStatus.ACTIVE

    @property
    def days_since_creation(self) -> int:
        return (datetime.now(timezone.utc) - self.created_at).days

    def needs_weekly_review(self, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        baseline = self.last_review_at or self.created_at
        return (reference - baseline).days >= 7

    @classmethod
    def empty(cls, topic: str) -> Training:
        """Create a Training in its initial CREATED state for a new topic."""
        return cls(
            topic=topic,
            status=TrainingStatus.CREATED,
            keywords=[],
            directory=Path(),
        )
