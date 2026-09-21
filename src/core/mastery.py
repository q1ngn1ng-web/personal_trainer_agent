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


#: 阶段达标的两种模式（ADR-0011）
COVERAGE_MODE: str = "coverage"
MASTERY_MODE: str = "mastery"


@dataclass(frozen=True)
class StageVerdict:
    """阶段达标判定结果。"""

    mastered: bool
    reason: str
    mode: str


def coverage_satisfied(statuses: Sequence[str]) -> bool:
    """覆盖口径：本阶段**全部**训练项都达标（`passed`）。"""
    values = list(statuses)
    return bool(values) and all(status == "passed" for status in values)


def acceptance_satisfied(
    acceptance: object,
    *,
    accuracy: float | None = None,
    practiced: int = 0,
    streak: int = 0,
) -> tuple[bool | None, str]:
    """按验收判据判断是否达标。返回 ``(是否满足, 说明)``；``None`` 表示现有数据判不了。

    支持的判据（`goal_json.acceptance`）：

    * 量化 `accuracy` → 训练准确率 ≥ target
    * 量化 `volume` → 已练次数 ≥ target
    * 量化 `streak` → 任一训练项的最大连续通过次数 ≥ target
    * 量化 `speed` → **没有耗时数据**，判不了（返回 None，由调用方退回覆盖口径）
    * 质性 → 需要人判断，判不了（返回 None）
    """
    if not isinstance(acceptance, dict):
        return None, "验收判据不是结构化量化判据"
    if str(acceptance.get("type")) != "quantitative":
        return None, "质性判据需要人工判断"
    metric = str(acceptance.get("metric") or "")
    try:
        target = float(acceptance.get("target"))
    except (TypeError, ValueError):
        return None, "验收判据缺少可比较的目标值"
    if metric == "accuracy":
        if accuracy is None:
            return None, "还没有准确率数据"
        return accuracy >= target, f"准确率 {accuracy:.2f} vs 目标 {target:.2f}"
    if metric == "volume":
        return practiced >= target, f"已练 {practiced} 次 vs 目标 {int(target)} 次"
    if metric == "streak":
        return streak >= target, f"最长连续通过 {streak} 次 vs 目标 {int(target)} 次"
    if metric == "speed":
        return None, "没有耗时数据，无法用速度判据"
    return None, f"未知口径 {metric!r}"


def stage_mastered(
    mode: str,
    statuses: Sequence[str],
    *,
    acceptance: object = None,
    accuracy: float | None = None,
    practiced: int = 0,
    streak: int = 0,
) -> StageVerdict:
    """阶段达标判定（ADR-0011）：

    * **覆盖模式**：本阶段全部必修项都 `passed`
    * **达成模式**：本阶段全部练过（`practiced`/`passed`），且验收判据满足；
      判据无法用现有数据判定时**退回覆盖口径**（宁可严，不放水）
    """
    values = list(statuses)
    if not values:
        return StageVerdict(False, "阶段里没有训练项", mode)
    if str(mode) == COVERAGE_MODE:
        done = coverage_satisfied(values)
        return StageVerdict(done, "覆盖模式：全部必修项达标" if done else "覆盖模式：还有必修项未达标", mode)
    practiced_all = all(status in ("practiced", "passed") for status in values)
    if not practiced_all:
        return StageVerdict(False, "达成模式：还有训练项没练过", mode)
    satisfied, why = acceptance_satisfied(
        acceptance, accuracy=accuracy, practiced=practiced, streak=streak
    )
    if satisfied is None:
        done = coverage_satisfied(values)
        return StageVerdict(
            done, f"达成模式：{why}，退回覆盖口径（{'已全部达标' if done else '仍有未达标项'}）", mode
        )
    return StageVerdict(satisfied, f"达成模式：{why}", mode)


__all__ = [
    "ACCURACY_HIGH",
    "ACCURACY_LOW",
    "COVERAGE_MODE",
    "MASTERY_STREAK",
    "MASTERY_MODE",
    "MIN_ATTEMPTS_FOR_OBJECTIVE",
    "MasteryState",
    "StageVerdict",
    "accuracy",
    "acceptance_satisfied",
    "consecutive_passes",
    "coverage_satisfied",
    "difficulty_delta",
    "evaluate",
    "objective_state",
    "stage_mastered",
]
