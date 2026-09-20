"""客观表现与达标判定的领域逻辑（纯函数）。

对应 ADR-0015（客观数据不足 3 次只做轻微调整）、ADR-0010（难度用真实数据校准）
与 change ``training-execution-feedback`` 的任务 5.1（训练项达标 = 判据满足且**连续 2 次**达标）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: 连续多少次通过才算该训练项达标
MASTERY_STREAK: int = 2

#: 客观数据不足多少次时不参与结构性裁决（ADR-0015 决策 2）
MIN_ATTEMPTS_FOR_OBJECTIVE: int = 3

#: 准确率口径（ADR-0015 决策 2）
ACCURACY_LOW: float = 0.6
ACCURACY_HIGH: float = 0.9


@dataclass(frozen=True)
class MasteryState:
    """一个训练项的客观表现摘要。"""

    attempts: int
    passes: int
    accuracy: float | None
    streak: int
    mastered: bool

    @property
    def has_enough_data(self) -> bool:
        return self.attempts >= MIN_ATTEMPTS_FOR_OBJECTIVE


def consecutive_passes(results: Sequence[str]) -> int:
    """从最近一次往前数，连续通过了多少次。"""
    streak = 0
    for result in reversed(list(results)):
        if result == "pass":
            streak += 1
        else:
            break
    return streak


def accuracy(results: Sequence[str]) -> float | None:
    """准确率；没有作答记录时返回 ``None``（不要用 0 冒充数据）。"""
    total = len(results)
    if total == 0:
        return None
    passed = sum(1 for result in results if result == "pass")
    return passed / total


def evaluate(results: Sequence[str], *, streak_needed: int = MASTERY_STREAK) -> MasteryState:
    """把作答序列折算成客观表现摘要与达标判定。"""
    values = list(results)
    metric = accuracy(values)
    streak = consecutive_passes(values)
    return MasteryState(
        attempts=len(values),
        passes=sum(1 for value in values if value == "pass"),
        accuracy=metric,
        streak=streak,
        mastered=streak >= streak_needed,
    )


def objective_state(results: Sequence[str]) -> str:
    """双通道裁决里的"客观"一侧（ADR-0015）：

    * 作答少于 3 次 → ``unknown``（只允许轻微调整）
    * 准确率 < 0.6 → ``low``；> 0.9 → ``high``；中间 → ``mid``
    """
    values = list(results)
    if len(values) < MIN_ATTEMPTS_FOR_OBJECTIVE:
        return "unknown"
    metric = accuracy(values)
    if metric is None:
        return "unknown"
    if metric < ACCURACY_LOW:
        return "low"
    if metric > ACCURACY_HIGH:
        return "high"
    return "mid"


def difficulty_delta(objective: str, signal_type: str) -> int:
    """难度调整档位：由规则决定，不由 LLM 决定。

    * ``too_easy`` 且客观不低 → 升一档
    * ``too_hard`` 且客观不高 → 降一档
    * 其余（含客观数据不足）→ 不动
    """
    if signal_type == "too_easy" and objective in ("mid", "high"):
        return 1
    if signal_type == "too_hard" and objective in ("low", "mid"):
        return -1
    return 0


__all__ = [
    "ACCURACY_HIGH",
    "ACCURACY_LOW",
    "MASTERY_STREAK",
    "MIN_ATTEMPTS_FOR_OBJECTIVE",
    "MasteryState",
    "accuracy",
    "consecutive_passes",
    "difficulty_delta",
    "evaluate",
    "objective_state",
]
