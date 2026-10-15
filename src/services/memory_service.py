"""学习者记忆：错因推导、薄弱点画像与上下文渲染。

对应 OpenSpec change ``learner-memory-and-grading`` 的任务 4.1—4.8。

三层结构（见该 change 的 design D3）：

* L1 事实层：``practice_attempts``（逐次作答 + 分数 + 要点级明细 + 错因）
* L2 派生层：薄弱点画像（**纯 SQL 聚合，不调用大模型**）
* L3 上下文层：把前两层**渲染**成紧凑摘要注入提示词

核心原则：**不是压缩原始对话，而是一开始就不产生原始对话**——信息一直在库里，
用的时候按需渲染。记忆是持久化状态，不是常驻会话。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.db.sqlite import get_connection as _connect

logger = logging.getLogger("src.services.memory_service")

#: 错因枚举（固定分类，保证可聚合；见 design D7）
MEMORY_GAP = "memory_gap"          # 记忆缺失：完全没印象
CONCEPT_CONFUSION = "concept_confusion"  # 概念混淆：把 A 记成 B
INCOMPLETE_EXPRESSION = "incomplete_expression"  # 表达不完整：知道但漏点
KEY_OMISSION = "key_omission"      # 关键遗漏：必答要点没答上

MISTAKE_REASONS: tuple[str, ...] = (
    MEMORY_GAP,
    CONCEPT_CONFUSION,
    INCOMPLETE_EXPRESSION,
    KEY_OMISSION,
)

MISTAKE_REASON_LABELS: dict[str, str] = {
    MEMORY_GAP: "记忆缺失",
    CONCEPT_CONFUSION: "概念混淆",
    INCOMPLETE_EXPRESSION: "表达不完整",
    KEY_OMISSION: "关键遗漏",
}

#: 掌握度低于该值视为薄弱知识点
WEAK_SCORE_THRESHOLD: float = 0.8

#: 错题分析开关的键名（app_settings）
MISTAKE_ANALYSIS_KEY: str = "mistake_analysis_enabled"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 错因（4.5）


def derive_mistake_reasons(point_results: Mapping[str, Any] | None) -> dict[str, str]:
    """由要点级判定推导错因。**纯函数，不调用大模型。**

    推导口径（见 design D7）：
    ``missing`` 且必答 → 关键遗漏；``missing`` → 记忆缺失；
    ``wrong`` → 概念混淆；``partial`` → 表达不完整。
    """
    if not point_results:
        return {}
    detail = point_results.get("detail") or []
    reasons: dict[str, str] = {}
    for entry in detail:
        if not isinstance(entry, Mapping):
            continue
        point_id = str(entry.get("point_id") or "")
        verdict = str(entry.get("verdict") or "")
        if not point_id:
            continue
        if verdict == "missing":
            reasons[point_id] = KEY_OMISSION if entry.get("required") else MEMORY_GAP
        elif verdict == "wrong":
            reasons[point_id] = CONCEPT_CONFUSION
        elif verdict == "partial":
            reasons[point_id] = INCOMPLETE_EXPRESSION
    # 兜底：detail 缺失时退回到判分结果里的清单
    for point_id in point_results.get("required_missing") or []:
        reasons.setdefault(str(point_id), KEY_OMISSION)
    for point_id in point_results.get("incorrect") or []:
        reasons.setdefault(str(point_id), CONCEPT_CONFUSION)
    for point_id in point_results.get("missing") or []:
        reasons.setdefault(str(point_id), MEMORY_GAP)
    return reasons


def record_mistake_reasons(
    attempt_id: int,
    reasons: Mapping[str, str],
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """把错因写回 ``practice_attempts.mistake_reasons``。"""
    active = conn or _connect()
    own = conn is None
    try:
        active.execute(
            "UPDATE practice_attempts SET mistake_reasons = ? WHERE id = ?",
            (json.dumps(dict(reasons), ensure_ascii=False), int(attempt_id)),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


# ---------------------------------------------------------------- 画像（4.2 / 4.8）


@dataclass(frozen=True)
class KnowledgeStat:
    """一个知识点（按题型拆分）的客观表现。"""

    knowledge_point: str
    question_type: str
    attempts: int
    passes: int
    avg_score: float | None

    @property
    def accuracy(self) -> float:
        return self.passes / self.attempts if self.attempts else 0.0

    @property
    def is_weak(self) -> bool:
        return (self.avg_score or 0.0) < WEAK_SCORE_THRESHOLD


def knowledge_profile(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> list[KnowledgeStat]:
    """薄弱点画像：按知识点 × 题型聚合。**纯 SQL，不调用大模型。**"""
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT COALESCE(qb.knowledge_point, '未分类') AS kp, "
            "       COALESCE(qb.question_type, 'qa') AS qt, "
            "       COUNT(*) AS attempts, "
            "       SUM(CASE WHEN pa.result = 'pass' THEN 1 ELSE 0 END) AS passes, "
            "       AVG(pa.score) AS avg_score "
            "FROM practice_attempts pa "
            "LEFT JOIN question_bank qb "
            "  ON qb.training_id = pa.training_id AND qb.item_key = pa.item_key "
            "WHERE pa.training_id = ? "
            "GROUP BY kp, qt ORDER BY kp, qt",
            (int(training_id),),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [
        KnowledgeStat(
            knowledge_point=str(row["kp"]),
            question_type=str(row["qt"]),
            attempts=int(row["attempts"]),
            passes=int(row["passes"] or 0),
            avg_score=None if row["avg_score"] is None else float(row["avg_score"]),
        )
        for row in rows
    ]


def mistake_reason_counts(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> Counter[str]:
    """历史错因分布：按错因枚举聚合，能回答"这个错因出现过几次"。"""
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT mistake_reasons FROM practice_attempts "
            "WHERE training_id = ? AND mistake_reasons IS NOT NULL",
            (int(training_id),),
        ).fetchall()
    finally:
        if own:
            active.close()
    counter: Counter[str] = Counter()
    for row in rows:
        try:
            payload = json.loads(row["mistake_reasons"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            counter.update(str(value) for value in payload.values())
    return counter


def recent_mistake_notes(
    training_id: int,
    *,
    limit: int = 3,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """最近若干次错因摘要（用于给本次评价提供时间纵深）。"""
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT pa.created_at, pa.mistake_reasons, "
            "       COALESCE(qb.knowledge_point, '未分类') AS kp "
            "FROM practice_attempts pa "
            "LEFT JOIN question_bank qb "
            "  ON qb.training_id = pa.training_id AND qb.item_key = pa.item_key "
            "WHERE pa.training_id = ? AND pa.mistake_reasons IS NOT NULL "
            "ORDER BY pa.id DESC LIMIT ?",
            (int(training_id), int(limit)),
        ).fetchall()
    finally:
        if own:
            active.close()

    notes: list[str] = []
    for row in rows:
        try:
            payload = json.loads(row["mistake_reasons"] or "{}")
        except (TypeError, ValueError):
            continue
        labels = sorted(
            {MISTAKE_REASON_LABELS.get(str(v), str(v)) for v in payload.values()}
        )
        if not labels:
            continue
        day = str(row["created_at"] or "")[:10]
        notes.append(f"{day} {row['kp']}：{'、'.join(labels)}")
    return notes


# ---------------------------------------------------------------- 渲染（4.1 / 4.4 / 4.7）


@dataclass(frozen=True)
class MemoryContext:
    """渲染后的上下文，附"渲染 vs 原始"的规模对比。"""

    text: str
    approx_tokens: int
    naive_tokens: int

    @property
    def compression_ratio(self) -> float:
        if self.naive_tokens <= 0:
            return 1.0
        return self.approx_tokens / self.naive_tokens


def _approx_tokens(text: str) -> int:
    """粗略 token 估算：中文按字、拉丁按 4 字符 1 token。

    仅用于**相对规模**对比（渲染后 vs 原始），不作为计费口径。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)


def render_context(
    training_id: int,
    *,
    current_item_key: str | None = None,
    history_limit: int = 3,
    conn: sqlite3.Connection | None = None,
) -> MemoryContext:
    """把事实与统计**渲染**成紧凑上下文（四段：画像 / 题型分布 / 错因历史 / 当前题背景）。"""
    active = conn or _connect()
    own = conn is None
    try:
        profile = knowledge_profile(training_id, conn=active)
        reasons = mistake_reason_counts(training_id, conn=active)
        notes = recent_mistake_notes(training_id, limit=history_limit, conn=active)
        current = None
        if current_item_key:
            current = active.execute(
                "SELECT knowledge_point, question_type FROM question_bank "
                "WHERE training_id = ? AND item_key = ?",
                (int(training_id), str(current_item_key)),
            ).fetchone()
        naive_rows = active.execute(
            "SELECT COALESCE(SUM(LENGTH(COALESCE(user_answer, ''))), 0) AS total "
            "FROM assessment_items ai JOIN assessments a ON a.id = ai.assessment_id "
            "WHERE a.training_id = ?",
            (int(training_id),),
        ).fetchone()
        naive_chars = int(naive_rows["total"] or 0)
    finally:
        if own:
            active.close()

    lines: list[str] = []
    weak = [stat for stat in profile if stat.is_weak]
    if profile:
        summary = "；".join(
            f"{stat.knowledge_point}({stat.question_type}) {stat.passes}/{stat.attempts}"
            for stat in (weak or profile)[:5]
        )
        head = "薄弱知识点" if weak else "知识点表现"
        lines.append(f"【{head}】{summary}")

    if reasons:
        reason_text = "、".join(
            f"{MISTAKE_REASON_LABELS.get(key, key)}×{count}"
            for key, count in reasons.most_common()
        )
        lines.append(f"【错因分布】{reason_text}")

    if notes:
        lines.append("【最近错因】" + "；".join(notes))

    if current is not None:
        lines.append(
            f"【当前题背景】知识点 {current['knowledge_point'] or '未分类'}，"
            f"题型 {current['question_type'] or 'qa'}"
        )

    text = "\n".join(lines)
    return MemoryContext(
        text=text,
        approx_tokens=_approx_tokens(text),
        naive_tokens=_approx_tokens("答" * naive_chars),
    )


# ---------------------------------------------------------------- 开关与分析（4.6）


def recommended_type_mix(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, float]:
    """下一场测验的题型配比：失误越多、均分越低的题型，占比越高。

    **纯 SQL + 规则，不调用大模型**；返回 ``{题型: 占比}``，和为 1；无数据时返回空字典。
    """
    profile = knowledge_profile(training_id, conn=conn)
    if not profile:
        return {}
    pressure: dict[str, float] = {}
    for stat in profile:
        score = stat.avg_score if stat.avg_score is not None else 0.0
        gap = max(0.0, WEAK_SCORE_THRESHOLD - score)
        pressure[stat.question_type] = pressure.get(stat.question_type, 0.0) + gap * stat.attempts
    pressure = {key: value for key, value in pressure.items() if value > 0}
    total = sum(pressure.values())
    if total <= 0:
        return {}
    return {
        question_type: round(value / total, 3)
        for question_type, value in sorted(pressure.items(), key=lambda kv: -kv[1])
    }


def is_mistake_analysis_enabled(*, conn: sqlite3.Connection | None = None) -> bool:
    """错题分析开关，**默认关闭**（成本与隐私考虑）。"""
    active = conn or _connect()
    own = conn is None
    try:
        row = active.execute(
            "SELECT value FROM app_settings WHERE key = ?", (MISTAKE_ANALYSIS_KEY,)
        ).fetchone()
    finally:
        if own:
            active.close()
    return bool(row) and str(row["value"]).lower() in ("1", "true", "yes", "on")


def set_mistake_analysis_enabled(
    enabled: bool, *, conn: sqlite3.Connection | None = None
) -> None:
    active = conn or _connect()
    own = conn is None
    try:
        active.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (MISTAKE_ANALYSIS_KEY, "1" if enabled else "0", _now()),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


def save_mistake_analysis(
    training_id: int,
    item_key: str,
    analysis_text: str,
    *,
    attempt_id: int | None = None,
    prompt_name: str = "mistake_analysis",
    prompt_version: str = "v1.0.0",
    model: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """保存错题分析文本（**不覆盖**规则错因）。"""
    active = conn or _connect()
    own = conn is None
    try:
        cursor = active.execute(
            "INSERT INTO mistake_analysis "
            "(training_id, item_key, attempt_id, analysis_text, prompt_name, prompt_version, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(training_id),
                str(item_key),
                attempt_id,
                str(analysis_text),
                prompt_name,
                prompt_version,
                model,
                _now(),
            ),
        )
        if own:
            active.commit()
        return int(cursor.lastrowid or 0)
    finally:
        if own:
            active.close()


def list_mistake_analysis(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> Sequence[str]:
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT analysis_text FROM mistake_analysis "
            "WHERE training_id = ? AND item_key = ? ORDER BY id",
            (int(training_id), str(item_key)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [str(row["analysis_text"]) for row in rows]


__all__ = [
    "CONCEPT_CONFUSION",
    "INCOMPLETE_EXPRESSION",
    "KEY_OMISSION",
    "KnowledgeStat",
    "MEMORY_GAP",
    "MISTAKE_ANALYSIS_KEY",
    "MISTAKE_REASONS",
    "MISTAKE_REASON_LABELS",
    "MemoryContext",
    "WEAK_SCORE_THRESHOLD",
    "derive_mistake_reasons",
    "is_mistake_analysis_enabled",
    "knowledge_profile",
    "list_mistake_analysis",
    "mistake_reason_counts",
    "recent_mistake_notes",
    "record_mistake_reasons",
    "recommended_type_mix",
    "render_context",
    "save_mistake_analysis",
    "set_mistake_analysis_enabled",
]
