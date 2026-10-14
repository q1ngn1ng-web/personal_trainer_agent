"""判分服务：按题型分流 + 可解释的要点评分。

对应 OpenSpec change ``learner-memory-and-grading`` 的任务 2.1—2.4。

硬约束（见该 change 的 HANDOFF 第 2 节）：

* 选择题 / 填空题走**确定性判分**，MUST NOT 调用大模型；
* 要点清单随题固化（``question_points`` 表），MUST NOT 在判分时临时生成；
* 判分结果必须**可解释**：给出缺失要点与错误要点，而不只是对错。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.db.sqlite import get_connection as _connect_sqlite

logger = logging.getLogger("src.services.grading_service")

#: 题型枚举。``qa`` 是历史数据的默认值（填空题、选择题是本 change 新增）。
QUESTION_TYPES: tuple[str, ...] = ("choice", "fill", "qa")
DEFAULT_QUESTION_TYPE: str = "qa"

#: 要点四态
HIT = "hit"
PARTIAL = "partial"
WRONG = "wrong"
MISSING = "missing"
POINT_VERDICTS: tuple[str, ...] = (HIT, PARTIAL, WRONG, MISSING)

#: 每条要点对覆盖率的贡献系数
_VERDICT_FACTOR: dict[str, float] = {HIT: 1.0, PARTIAL: 0.5, WRONG: 0.0, MISSING: 0.0}

#: 主观题达标阈值。
#: 2026-10-15 用户决策：取 0.8。仍需用人工标注样本校准（见 ADR-0022 的"后果与验证"）。
DEFAULT_PASS_THRESHOLD: float = 0.8

#: 整场评分的题型权重：客观题（选择 / 填空）0.6，主观题 0.4。
#: 2026-10-15 用户决策。理由：选择题容易满分、区分度低，主观题更能反映真实掌握程度。
OBJECTIVE_WEIGHT: float = 0.6
SUBJECTIVE_WEIGHT: float = 0.4

#: 客观题题型
OBJECTIVE_TYPES: tuple[str, ...] = ("choice", "fill")

_PUNCT_PATTERN = re.compile(r"[\s，。、；：！？,.;:!?\"'“”‘’（）()\[\]【】<>《》\-—_/\\|]+")


def normalize_text(text: Any) -> str:
    """归一化文本：去空白、去常见中英文标点、统一大小写。

    用于填空题的精确比对。本期**不处理同义答案**（见 design D2）。
    """
    if text is None:
        return ""
    value = str(text).strip().lower()
    return _PUNCT_PATTERN.sub("", value)


# ---------------------------------------------------------------- 客观题判分


def grade_choice(
    answer: Any, *, correct_key: Any, options: Sequence[Mapping[str, Any]] | None = None
) -> tuple[str, str]:
    """选择题判分：比对正确选项。**不调用任何大模型。**

    兼容两种作答：选项目标（如 ``"A"``）或选项原文。返回 ``(verdict, reason)``。
    """
    given = normalize_text(answer)
    if not given:
        return WRONG, "未作答"
    key = normalize_text(correct_key)
    if given == key:
        return HIT, "选项正确"
    for option in options or ():
        if normalize_text(option.get("key")) != key:
            continue
        if given == normalize_text(option.get("text")):
            return HIT, "选项正确"
    return WRONG, "选项错误"


def grade_fill(
    answer: Any, *, expected: Any, accepted: Sequence[Any] | None = None
) -> tuple[str, str]:
    """填空题判分：归一化后精确比对。**不调用任何大模型。**"""
    given = normalize_text(answer)
    if not given:
        return WRONG, "未作答"
    candidates = [expected, *(accepted or ())]
    if any(given == normalize_text(item) for item in candidates):
        return HIT, "填空正确"
    return WRONG, "填空错误"


# ---------------------------------------------------------------- 主观题评分


@dataclass(frozen=True)
class PointSpec:
    """题目要点。``weight`` 决定权重，``required`` 缺失时一票否决。"""

    point_id: str
    text: str
    weight: float = 1.0
    required: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PointSpec":
        return cls(
            point_id=str(row["point_id"]),
            text=str(row["point_text"]),
            weight=float(row["weight"] or 1),
            required=bool(row["is_required"]),
        )


@dataclass(frozen=True)
class PointScore:
    """要点评分结果。``missing`` / ``incorrect`` 是可解释性的来源。"""

    coverage: float
    correctness: float
    score: float
    missing: tuple[str, ...] = ()
    incorrect: tuple[str, ...] = ()
    required_missing: tuple[str, ...] = ()


def score_points(
    points: Sequence[PointSpec], verdicts: Mapping[str, str]
) -> PointScore:
    """按覆盖率 × 正确性给分。

    * 覆盖率 = Σ(权重 × 系数) ÷ Σ权重，命中 1.0 / 部分 0.5 / 错误与缺失 0
    * 正确性 = 1 − 错误权重 ÷ 作答涉及权重（"说反了"比"没说"更糟）
    * 最终得分 = 覆盖率 × 正确性
    """
    specs = list(points)
    if not specs:
        raise ValueError("主观题缺少要点清单，拒绝判分（要点必须随题固化）")

    total_weight = sum(max(spec.weight, 0.0) for spec in specs) or 1.0
    hit_weight = 0.0
    wrong_weight = 0.0
    attempted_weight = 0.0
    missing: list[str] = []
    incorrect: list[str] = []
    required_missing: list[str] = []

    for spec in specs:
        verdict = str(verdicts.get(spec.point_id, MISSING))
        if verdict not in POINT_VERDICTS:
            raise ValueError(f"未知要点判定：{verdict!r}")
        weight = max(spec.weight, 0.0)
        hit_weight += weight * _VERDICT_FACTOR[verdict]
        if verdict != MISSING:
            attempted_weight += weight
        if verdict == WRONG:
            wrong_weight += weight
            incorrect.append(spec.point_id)
        elif verdict == MISSING:
            missing.append(spec.point_id)
        if spec.required and verdict != HIT:
            required_missing.append(spec.point_id)

    coverage = hit_weight / total_weight
    correctness = 1.0 if attempted_weight <= 0 else max(0.0, 1.0 - wrong_weight / attempted_weight)
    return PointScore(
        coverage=coverage,
        correctness=correctness,
        score=coverage * correctness,
        missing=tuple(missing),
        incorrect=tuple(incorrect),
        required_missing=tuple(required_missing),
    )


# ---------------------------------------------------------------- 整场评分


def type_weight(question_type: str) -> float:
    """题型的整场评分权重：客观题 0.6，主观题 0.4。"""
    return OBJECTIVE_WEIGHT if str(question_type) in OBJECTIVE_TYPES else SUBJECTIVE_WEIGHT


def overall_score(results: Sequence["GradeResult"]) -> float | None:
    """整场评分：按题型权重对单题得分做加权平均。

    权重和不为 1 时按实际权重归一化；没有任何成绩时返回 ``None``
    （不要用 0 冒充"考了零分"）。整场评分**不重新调用模型**，只做确定性聚合。
    """
    entries = list(results)
    if not entries:
        return None
    total_weight = sum(type_weight(item.question_type) for item in entries)
    if total_weight <= 0:
        return None
    weighted = sum(
        item.score * type_weight(item.question_type) for item in entries
    )
    return weighted / total_weight


# ---------------------------------------------------------------- 统一入口


@dataclass(frozen=True)
class GradeResult:
    """一次判分的完整结果。``graded_by`` 用来断言客观题没有走模型。"""

    question_type: str
    verdict: str
    passed: bool
    score: float
    graded_by: str
    coverage: float | None = None
    correctness: float | None = None
    missing: tuple[str, ...] = ()
    incorrect: tuple[str, ...] = ()
    required_missing: tuple[str, ...] = ()
    reason: str = ""
    detail: tuple[dict[str, Any], ...] = ()


def grade_question(
    question_type: str,
    *,
    answer: Any,
    expected_answer: Any = None,
    options: Sequence[Mapping[str, Any]] | None = None,
    points: Sequence[PointSpec] | None = None,
    point_verdicts: Mapping[str, str] | None = None,
    pass_threshold: float = DEFAULT_PASS_THRESHOLD,
) -> GradeResult:
    """统一判分入口：按题型分流。

    ``choice`` / ``fill`` 完全确定性；``qa`` 依赖随题固化的要点清单与逐条判定
    （逐条判定由调用方提供，本函数只做计分，自身不调用模型）。
    """
    kind = str(question_type or DEFAULT_QUESTION_TYPE)
    if kind not in QUESTION_TYPES:
        raise ValueError(f"未知题型：{kind!r}")

    if kind == "choice":
        verdict, reason = grade_choice(answer, correct_key=expected_answer, options=options)
        passed = verdict == HIT
        return GradeResult(
            question_type=kind,
            verdict=verdict,
            passed=passed,
            score=1.0 if passed else 0.0,
            graded_by="rule",
            reason=reason,
        )

    if kind == "fill":
        verdict, reason = grade_fill(answer, expected=expected_answer)
        passed = verdict == HIT
        return GradeResult(
            question_type=kind,
            verdict=verdict,
            passed=passed,
            score=1.0 if passed else 0.0,
            graded_by="rule",
            reason=reason,
        )

    specs = list(points or ())
    outcome = score_points(specs, point_verdicts or {})
    passed = not outcome.required_missing and outcome.score >= pass_threshold
    if outcome.required_missing:
        reason = f"缺少必答要点：{'、'.join(outcome.required_missing)}"
    elif passed:
        reason = "覆盖与正确性达到阈值"
    else:
        reason = f"完整度 {outcome.score:.2f} 低于阈值 {pass_threshold:.2f}"
    detail = tuple(
        {
            "point_id": spec.point_id,
            "verdict": str((point_verdicts or {}).get(spec.point_id, MISSING)),
            "weight": spec.weight,
            "required": spec.required,
        }
        for spec in specs
    )
    return GradeResult(
        question_type=kind,
        verdict=HIT if passed else MISSING,
        passed=passed,
        score=outcome.score,
        graded_by="points",
        coverage=outcome.coverage,
        correctness=outcome.correctness,
        missing=outcome.missing,
        incorrect=outcome.incorrect,
        required_missing=outcome.required_missing,
        reason=reason,
        detail=detail,
    )


# ---------------------------------------------------------------- 持久化


def record_attempt_score(
    attempt_id: int,
    result: GradeResult,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """把分数与要点级明细写回 ``practice_attempts``（任务 2.4）。"""
    payload = json.dumps(
        {
            "question_type": result.question_type,
            "coverage": result.coverage,
            "correctness": result.correctness,
            "missing": list(result.missing),
            "incorrect": list(result.incorrect),
            "required_missing": list(result.required_missing),
            "detail": list(result.detail),
        },
        ensure_ascii=False,
    )
    active = conn or _connect_sqlite()
    own = conn is None
    try:
        active.execute(
            "UPDATE practice_attempts SET score = ?, point_results = ? WHERE id = ?",
            (float(result.score), payload, int(attempt_id)),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


def load_points(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> list[PointSpec]:
    """读取随题固化的要点清单（任务 1.2 的读取端）。"""
    active = conn or _connect_sqlite()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT point_id, point_text, weight, is_required FROM question_points "
            "WHERE training_id = ? AND item_key = ? ORDER BY ordinal, id",
            (int(training_id), str(item_key)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [PointSpec.from_row(row) for row in rows]


__all__ = [
    "DEFAULT_PASS_THRESHOLD",
    "DEFAULT_QUESTION_TYPE",
    "GradeResult",
    "HIT",
    "MISSING",
    "OBJECTIVE_TYPES",
    "OBJECTIVE_WEIGHT",
    "PARTIAL",
    "POINT_VERDICTS",
    "PointScore",
    "PointSpec",
    "QUESTION_TYPES",
    "SUBJECTIVE_WEIGHT",
    "WRONG",
    "grade_choice",
    "grade_fill",
    "grade_question",
    "load_points",
    "normalize_text",
    "overall_score",
    "record_attempt_score",
    "score_points",
    "type_weight",
]
