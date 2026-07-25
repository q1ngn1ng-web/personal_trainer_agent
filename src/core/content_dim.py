from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ContentDimension(Enum):
    CONCEPT = ("concept", "概念", "📖")
    READ = ("read", "读代码", "📝")
    WRITE = ("write", "写代码", "💻")

    def __init__(self, english: str, chinese: str, icon: str) -> None:
        self.english = english
        self.chinese = chinese
        self.icon = icon


DEFAULT_DAILY_RATIO: dict[ContentDimension, float] = {
    ContentDimension.CONCEPT: 0.3,
    ContentDimension.READ: 0.4,
    ContentDimension.WRITE: 0.3,
}


def distribute_by_ratio(
    total: int,
    ratio: dict[ContentDimension, float],
) -> dict[ContentDimension, int]:
    """Distribute ``total`` items across dimensions per ``ratio``.

    The returned counts always sum to ``total``. Remainders (from flooring)
    are handed to the dimensions with the largest fractional gap, in
    descending order (largest-remainder method).
    """
    if total <= 0:
        return {dim: 0 for dim in ratio}

    floor = {dim: int(total * weight) for dim, weight in ratio.items()}
    remainder = total - sum(floor.values())

    if remainder > 0:
        fractional = {
            dim: (total * weight) - floor[dim]
            for dim, weight in ratio.items()
        }
        ordered = sorted(ratio.keys(), key=lambda d: fractional[d], reverse=True)
        for dim in ordered[:remainder]:
            floor[dim] += 1

    return floor
