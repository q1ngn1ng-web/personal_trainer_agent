"""训练排期的领域逻辑：固定 5 轮阶梯、当日取数、冷却期、测验日期。

纯函数，不依赖数据库与 LLM。对应 ADR-0021 与 OpenSpec change
``training-plan-and-daily-view``：

* 整条路径固定 **5 轮**，锚点是**训练创建日**，到期日为 +1 / +3 / +7 / +15 / +30 天
* 每一轮覆盖路径中的**全部**训练项（一轮 = 把所有题过一遍）
* 未完成的项**累计到次日**（查询语义：``due_date <= 今天`` 且未完成）
* 同一训练项只取**最早未完成的那一轮**（轮次顺序是硬约束）
* 题库冷却期 = 最近练过日 + 14 天（ADR-0016 要求测验排除刚练过的原题）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

#: 5 轮的到期日偏移（相对训练创建日）
ROUND_OFFSETS: tuple[int, ...] = (1, 3, 7, 15, 30)

#: 测验节奏：每 14 天一次（锚点同创建日）
QUIZ_INTERVAL_DAYS: int = 14

#: 题库冷却期：练过之后多少天内不得被抽为测验题
COOLDOWN_DAYS: int = 14

#: 本地时区（可用环境变量覆盖，默认东八区——用户与部署都在国内）
LOCAL_TZ_NAME: str = os.environ.get("TRAINER_TZ", "Asia/Shanghai")

_WS_RE = re.compile(r"\s+")


def local_tz() -> ZoneInfo:
    """返回本地时区对象。"""
    try:
        return ZoneInfo(LOCAL_TZ_NAME)
    except Exception:  # pragma: no cover - 时区库缺数据时退回 UTC
        return ZoneInfo("UTC")


def local_today(now: datetime | None = None) -> date:
    """本地时区下的"今天"。

    所有与"今天"相关的判断（排期、打卡、信号限频）都必须走这里，
    避免出现"限频按 UTC、打卡按本地"的分叉。
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(local_tz()).date()


def parse_local_date(value: object, fallback: date | None = None) -> date:
    """把库里的时间戳/日期字符串解析成本地日期。"""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(local_tz()).date()
    text = str(value or "").strip()
    if not text:
        return fallback or local_today()
    text = text.replace("Z", "+00:00")
    try:
        return parse_local_date(datetime.fromisoformat(text), fallback=fallback)
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return fallback or local_today()


def round_due_dates(
    anchor: date, offsets: Sequence[int] = ROUND_OFFSETS
) -> dict[int, date]:
    """给定锚点日，返回 {轮次: 到期日}（轮次从 1 开始）。"""
    return {index: anchor + timedelta(days=offset) for index, offset in enumerate(offsets, start=1)}


def quiz_due_dates(anchor: date, until: date, interval: int = QUIZ_INTERVAL_DAYS) -> list[date]:
    """从锚点起每 ``interval`` 天一个测验日，直到 ``until``（含）。"""
    dates: list[date] = []
    current = anchor + timedelta(days=interval)
    while current <= until:
        dates.append(current)
        current = current + timedelta(days=interval)
    return dates


def cooldown_until(practiced_on: date, days: int = COOLDOWN_DAYS) -> date:
    """题库冷却期结束日 = 最近练过日 + ``days``。"""
    return practiced_on + timedelta(days=days)


def item_key_for(training_id: int, knowledge_point: str | None, title: str) -> str:
    """稳定题目键：走 `training_items.id` 会在路径重生成后失效（见 ADR-0021 关联的 D7）。

    取 `training_id + 知识点 + 规范化标题` 的 sha1 前 12 位；
    重新生成路径时，只要知识点与标题没变，键就不变，题库与计划因此不会悬空。
    """
    point = _WS_RE.sub("", str(knowledge_point or ""))
    name = _WS_RE.sub("", str(title or "")).lower()
    raw = f"{int(training_id)}|{point}|{name}"
    import hashlib

    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class PlannedTask:
    """一条待做的计划项（当日取数的结果）。"""

    plan_id: int
    training_id: int
    item_key: str
    round_index: int
    kind: str
    due_date: date
    original_date: date
    status: str
    planned_minutes: int
    title: str = ""
    knowledge_point: str = ""
    item_type: str = ""
    difficulty_tier: int | None = None
    training_topic: str = ""
    ordinal: int = 0
    question: str = ""
    reference_answer: str = ""
    answer_text: str = ""
    verdict: str | None = None
    graded_by: str | None = None

    def is_overdue(self, today: date) -> bool:
        """原定到期日早于今天 = 这一项是"累计到今天"的（原定日期可在 ``original_date`` 里看到）。"""
        return self.due_date < today


@dataclass(frozen=True)
class PlanSlot:
    """用于纯函数取数的计划项视图。"""

    item_key: str
    round_index: int
    due_date: date
    status: str


def select_today_slots(slots: Iterable[PlanSlot], today: date) -> list[PlanSlot]:
    """从计划项里选出"今天该练的"：到期日 ≤ 今天、未完成，且每个题目只取最早未完成的那一轮。

    这是"累计到下一天"的实现口径——不去改数据库里的 ``due_date``，而是把
    所有已经到期但没做的项都算作今天该做的。
    """
    pending = [slot for slot in slots if slot.status == "planned" and slot.due_date <= today]
    earliest: dict[str, PlanSlot] = {}
    for slot in pending:
        current = earliest.get(slot.item_key)
        if current is None or slot.round_index < current.round_index:
            earliest[slot.item_key] = slot
    return [earliest[key] for key in sorted(earliest)]


def total_minutes(slots: Iterable[PlannedTask]) -> int:
    """当日任务的预计总时长。"""
    return sum(int(slot.planned_minutes or 0) for slot in slots)


__all__ = [
    "COOLDOWN_DAYS",
    "LOCAL_TZ_NAME",
    "QUIZ_INTERVAL_DAYS",
    "ROUND_OFFSETS",
    "PlanSlot",
    "PlannedTask",
    "cooldown_until",
    "item_key_for",
    "local_today",
    "local_tz",
    "parse_local_date",
    "quiz_due_dates",
    "round_due_dates",
    "select_today_slots",
    "total_minutes",
]
