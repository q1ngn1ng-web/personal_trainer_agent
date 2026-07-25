from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.core.element import BaselineLevel

logger = logging.getLogger(__name__)


def compute_level(score: float) -> BaselineLevel:
    """Map a 0–5 score to a level: high (>=4.0), mid (>=2.5), low."""
    if score >= 4.0:
        return BaselineLevel.HIGH
    if score >= 2.5:
        return BaselineLevel.MID
    return BaselineLevel.LOW


def score_delta_to_level(delta: float) -> BaselineLevel:
    """Translate an LLM-emitted score delta into a directional level."""
    if delta >= 0.5:
        return BaselineLevel.HIGH
    if delta <= -0.5:
        return BaselineLevel.LOW
    return BaselineLevel.MID


def merge_baseline_history(history: list[BaselineScore]) -> BaselineScore:
    """Return the most recent BaselineScore from a history list."""
    if not history:
        raise ValueError("merge_baseline_history requires a non-empty history")
    return max(history, key=lambda b: b.recorded_at)


@dataclass
class BaselineScore:
    score: float
    dimension_scores: dict[str, float]
    partial_topics: list[str]
    level: BaselineLevel
    recorded_at: datetime

    @property
    def score_5_scale(self) -> float:
        return round(self.score, 1)
