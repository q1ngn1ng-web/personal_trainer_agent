"""会话配比控制器（change ``user-defined-training-plan``，任务 2.1/2.2）。

**纯函数，零 LLM**：相同输入必得相同分配（spec 硬性要求）。

模型（用户拍板 + design D2/D3）：
- 硬约束：跨会话并集 = 100% 覆盖（每个训练项至少 1 次）；
- 单次占比随会话数递减、会话间重叠递增（占比表【待校准】）；
- 重叠池的「已知巩固 : 错题回炉」构成由**正确率恒稳控制器**动态分配
  （目标带 80%±10%）；桶内入选按五星「值得复习率」排序。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

#: 会话次数边界（与 goal.PACE 校验一致）
SESSION_COUNT_MIN: int = 2
SESSION_COUNT_MAX: int = 6
HORIZON_DAYS_MIN: int = 1
HORIZON_DAYS_MAX: int = 56

#: 正确率目标带 80%±10%
ACCURACY_BAND: tuple[float, float] = (0.70, 0.90)

#: 单次覆盖占比表【待校准】：N 次训练时每次覆盖的训练项比例；
#: N=2 时 70%+70%−40% 重叠 = 100% 并集 ✓；N≥3 由构造算法保证并集（新增优先填满）
COVERAGE_SHARES: dict[int, float] = {
    1: 1.00,
    2: 0.70,
    3: 0.60,
    4: 0.50,
    5: 0.45,
    6: 0.40,
}

#: 恒稳控制器【待校准】：最近会话正确率 → 重叠池的（已知巩固占比, 错题回炉占比）。
#: 目标带 50:50（对应 N=2 的 20%:20%）；偏难多巩固已知；太容易镜像外推（降已知升错题）。
_CONTROLLER_TABLE: tuple[tuple[float, float, float], ...] = (
    # (正确率下界, known_share, wrong_share)——按下界从大到小匹配
    (0.90, 0.375, 0.625),   # >90% 太容易：镜像外推
    (0.70, 0.50, 0.50),     # 70-90% 目标带：维持（20%:20%）
    (0.60, 0.625, 0.375),   # 60-70% 偏难：25%:15%
    (0.0, 0.75, 0.25),      # <60% 太难：30%:10%
)

#: 五星「值得复习率」映射【待校准】：错题 5★；回归（先对后错）3★（评审注：不稳定信号，
#: 积累证据后可再校准排序）；不稳定答对 2★；稳定答对 1★（连续 pass 越多越靠后）。
STAR_WRONG: int = 5
STAR_REGRESSION: int = 3
STAR_UNSTABLE_PASS: int = 2
STAR_STABLE_PASS: int = 1


@dataclass
class ItemStat:
    """配比输入：一个训练项的客观表现快照（由 plan_service 从 attempts 聚合）。"""

    item_key: str
    knowledge_point: str = ""
    minutes: int = 15
    ordinal: int = 0
    attempts: int = 0
    ever_passed: bool = False
    ever_failed: bool = False
    last_result: str | None = None  # "pass" / "fail" / None（未接触）
    consecutive_passes: int = 0
    last_practiced: str | None = None


@dataclass
class Composition:
    """一次分配结果：会话清单（并集=全部 item_key）+ 元信息。"""

    sessions: list[list[str]] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    known_share: float = 0.5
    wrong_share: float = 0.5
    share: float = 1.0


def controller_ratio(accuracy: float | None) -> tuple[float, float]:
    """正确率 → 重叠池（已知巩固占比, 错题回炉占比）。无数据按目标带 50:50。"""
    if accuracy is None:
        return (0.50, 0.50)
    for lower, known, wrong in _CONTROLLER_TABLE:
        if accuracy >= lower:
            return (known, wrong)
    return (0.50, 0.50)


def star_value(stat: ItemStat) -> int:
    """五星「值得复习率」：不是难度，是"该不该再练"。"""
    if stat.last_result == "fail":
        if stat.ever_passed:
            return STAR_REGRESSION  # 回归：先对后错（不稳定信号）
        return STAR_WRONG
    if stat.ever_failed:
        return STAR_UNSTABLE_PASS  # 答对但不稳定
    if stat.attempts:
        return STAR_STABLE_PASS  # 稳定答对
    return 0  # 未接触（不在任何复习池里，由并集新增覆盖）


def _overlap_pool_order(stats: dict[str, ItemStat], covered_keys: list[str]) -> list[str]:
    """桶内入选顺序：星序降序 → 稳定答对按连续 pass 升序（越稳越靠后）→ 键名稳定序。"""
    def sort_key(key: str) -> tuple[int, int, str]:
        stat = stats[key]
        star = star_value(stat)
        stability_rank = stat.consecutive_passes if star == STAR_STABLE_PASS else 0
        return (-star, stability_rank, key)

    return sorted(covered_keys, key=sort_key)


def _stable_keys(stats: dict[str, ItemStat], keys: list[str]) -> list[str]:
    """已知巩固桶：稳定答对 + 不稳定答对（1-2★）。"""
    return [key for key in keys if star_value(stats[key]) in (STAR_STABLE_PASS, STAR_UNSTABLE_PASS)]


def _wrong_keys(stats: dict[str, ItemStat], keys: list[str]) -> list[str]:
    """错题回炉桶：错题（5★）优先，回归（3★）次之。"""
    return [key for key in keys if star_value(stats[key]) in (STAR_WRONG, STAR_REGRESSION)]


def compose_sessions(
    stats: list[ItemStat],
    session_count: int,
    *,
    anchor: date,
    horizon_days: int,
    accuracy: float | None = None,
    stable_keys: list[str] | None = None,
    pre_covered: list[str] | None = None,
    fixed_dates: list[date] | None = None,
) -> Composition:
    """把训练项分配到 N 次会话（纯函数）。

    - 并集硬约束：未覆盖项优先进入后续会话（容量不足时以覆盖为先，会话变大）；
    - 重叠池构成：controller_ratio(accuracy) 分「已知巩固 : 错题回炉」；
    - 桶内入选：五星排序（错题 > 回归 > 不稳定 > 稳定）；
    - ``stable_keys``：追加周期时"已稳定项"强制进入已知巩固池（design D4）；
    - ``pre_covered``：重组未来会话时已覆盖项（design D5：不改变已发生会话的覆盖）；
    - ``fixed_dates``：重组时保持既有会话日期不变（design D5：只换清单不挪排期）；
    - 日期缺省：horizon 内近似均匀摊开（design D5）。
    """
    if not (SESSION_COUNT_MIN <= session_count <= SESSION_COUNT_MAX):
        raise ValueError(f"session_count 取值范围 {SESSION_COUNT_MIN}-{SESSION_COUNT_MAX}")
    if not (HORIZON_DAYS_MIN <= horizon_days <= HORIZON_DAYS_MAX):
        raise ValueError(f"horizon_days 取值范围 {HORIZON_DAYS_MIN}-{HORIZON_DAYS_MAX}")

    stat_map: dict[str, ItemStat] = {}
    for stat in sorted(stats, key=lambda s: (s.ordinal, s.item_key)):
        stat_map[stat.item_key] = stat

    all_keys = [stat.item_key for stat in stat_map.values()]
    total = len(all_keys)
    known_share, wrong_share = controller_ratio(accuracy)
    share = COVERAGE_SHARES.get(session_count, 0.5)
    per_session = max(1, round(total * share)) if session_count > 1 else total

    stable_hint = set(stable_keys or [])

    sessions: list[list[str]] = []
    assigned: set[str] = set(pre_covered or [])  # 已覆盖项（并集口径）不算新增
    for index in range(session_count):
        session_keys: list[str] = []
        session_set: set[str] = set()

        # 1) 并集硬约束：还没出现过的项先进入（按路径顺序）；
        #    首个会话最多 per_session；后续会话未覆盖项全收（硬约束优先，会话允许变大）
        uncovered = [key for key in all_keys if key not in assigned]
        take_new = uncovered[:per_session] if index == 0 else uncovered
        for key in take_new:
            session_keys.append(key)
            session_set.add(key)
            assigned.add(key)

        # 2) 重叠池：从已出现过的项里按控制器构成选（从第 2 个会话开始）
        overlap_capacity = max(0, per_session - len(session_keys))
        if overlap_capacity and index > 0:
            prior_keys = [key for key in all_keys if key in assigned and key not in session_set]
            ordered = _overlap_pool_order(stat_map, prior_keys)
            known_pool = [key for key in ordered if key in stable_hint or key in _stable_keys(stat_map, ordered)]
            wrong_pool = [key for key in ordered if key not in known_pool]
            # 比例分桶；某桶不足时另一桶回填（不浪费巩固容量）
            want_known = round(overlap_capacity * known_share)
            want_wrong = overlap_capacity - want_known
            picks_known = known_pool[:want_known]
            picks_wrong = wrong_pool[:want_wrong]
            if len(picks_known) < want_known:
                picks_known.extend(wrong_pool[len(picks_wrong): len(picks_wrong) + want_known - len(picks_known)])
            if len(picks_wrong) < want_wrong:
                picks_wrong.extend(known_pool[len(picks_known): len(picks_known) + want_wrong - len(picks_wrong)])
            remainder = [key for key in ordered if key not in picks_known and key not in picks_wrong]
            for key in picks_known + picks_wrong + remainder:
                if overlap_capacity <= 0:
                    break
                if key in session_set:
                    continue
                session_keys.append(key)
                session_set.add(key)
                overlap_capacity -= 1

        sessions.append(session_keys)

    # 兜底：并集兜不住时（容量极端不足）把剩余项塞进最后一个会话——硬约束优先
    missing = [key for key in all_keys if key not in assigned]
    if missing:
        sessions[-1].extend(missing)

    # 会话内展示顺序：五星降序（错题在前）→ 路径顺序；确定性稳定排序
    position = {key: index for index, key in enumerate(all_keys)}
    sessions = [
        sorted(
            keys,
            key=lambda key: (-star_value(stat_map.get(key, ItemStat(item_key=key))), position.get(key, 0)),
        )
        for keys in sessions
    ]

    dates = list(fixed_dates) if fixed_dates is not None else session_dates(anchor, horizon_days, session_count)
    return Composition(
        sessions=sessions,
        dates=dates,
        known_share=known_share,
        wrong_share=wrong_share,
        share=share,
    )


def session_dates(anchor: date, horizon_days: int, session_count: int) -> list[date]:
    """N 个会话日在 horizon 内近似均匀摊开：anchor + floor(horizon × i / N)，i=1..N。"""
    dates: list[date] = []
    for index in range(1, session_count + 1):
        offset = max(1, (horizon_days * index) // session_count)
        dates.append(anchor + timedelta(days=offset))
    return dates


__all__ = [
    "ACCURACY_BAND",
    "COVERAGE_SHARES",
    "Composition",
    "HORIZON_DAYS_MAX",
    "HORIZON_DAYS_MIN",
    "ItemStat",
    "SESSION_COUNT_MAX",
    "SESSION_COUNT_MIN",
    "STAR_REGRESSION",
    "STAR_STABLE_PASS",
    "STAR_UNSTABLE_PASS",
    "STAR_WRONG",
    "compose_sessions",
    "controller_ratio",
    "session_dates",
    "star_value",
]
