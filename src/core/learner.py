"""学习者模型的纯函数层：掌握度递推、时间衰减、活跃误解提炼。

对应 change ``layered-learner-memory``。全部确定性、零 LLM、可单测——
学习者模型是 ``practice_attempts`` 的派生层，任何时刻可全量重放重建。
"""
from __future__ import annotations

from typing import Any, Mapping

#: 掌握度递推步长：约三次一致表现收敛（0.5 → 0.675 → 0.789 → 0.86）
MASTERY_K: float = 0.35

#: 掌握度默认起点（无任何作答时的先验）
MASTERY_START: float = 0.5

#: 衰减半衰期（天）：与五轮排期的最长间隔（+30 天）呼应——30 天不练，掌握度减半
MASTERY_HALF_LIFE_DAYS: float = 30.0

#: 误解清单的错因码（与 memory_service 的错因枚举一致）
_REASON_CONFUSION = "concept_confusion"
_REASON_OMISSION = "key_omission"


def update_mastery(current: float | None, outcome: float) -> float:
    """Elo 式递推：``m += K × (outcome − m)``，结果 clamp 到 [0, 1]。

    ``outcome`` 取要点得分（0-1）；无分数的二元作答传 1.0（pass）或 0.0（fail）。
    """
    base = MASTERY_START if current is None else float(current)
    updated = base + MASTERY_K * (float(outcome) - base)
    return min(1.0, max(0.0, updated))


def decay_mastery(mastery: float, days_since_seen: float) -> float:
    """读时衰减：``mastery × 0.5^(days / 半衰期)``。负的天数按 0 处理（面向未来不算遗忘）。"""
    days = max(0.0, float(days_since_seen))
    return float(mastery) * (0.5 ** (days / MASTERY_HALF_LIFE_DAYS))


def misconceptions_from_detail(point_results: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """从最近一次判分的要点明细提炼**活跃误解清单**（整体替换语义）。

    口径：``wrong`` → 概念混淆（说反了，最值得纠正）；必答 ``missing`` → 关键遗漏。
    普通缺失（记忆 gap）不进清单——那是遗忘不是误解，交给衰减与调度表达。
    依赖 grading-rubric-hardening 的 detail 快照（含 text）；无明细返回空表。
    """
    if not point_results:
        return []
    detail = point_results.get("detail") or []
    entries: list[dict[str, str]] = []
    for item in detail:
        if not isinstance(item, Mapping):
            continue
        verdict = str(item.get("verdict") or "")
        required = bool(item.get("required"))
        if verdict == "wrong":
            reason = _REASON_CONFUSION
        elif verdict == "missing" and required:
            reason = _REASON_OMISSION
        else:
            continue
        pid = str(item.get("point_id") or "")
        text = str(item.get("text") or "")
        if not pid or not text:
            continue
        entries.append({"point_id": pid, "text": text, "reason": reason})
    return entries


__all__ = [
    "MASTERY_K",
    "MASTERY_START",
    "MASTERY_HALF_LIFE_DAYS",
    "update_mastery",
    "decay_mastery",
    "misconceptions_from_detail",
]
