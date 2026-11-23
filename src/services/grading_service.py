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

#: 整场评分的题型权重：客观题（选择 / 填空）0.4，主观题 0.6。
#: 2026-10-15 用户决策（同日修正过一次方向）。理由：选择题容易满分、区分度低，
#: 主观题更能反映真实掌握程度，所以主观题权重更高。
OBJECTIVE_WEIGHT: float = 0.4
SUBJECTIVE_WEIGHT: float = 0.6

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
    """填空题判分（单空、无答案键的兜底口径）：归一化后精确比对。**不调用任何大模型。**

    多空填空走 :func:`grade_fill_keyed`（按每空答案键逐空比对，部分给分）。
    """
    given = normalize_text(answer)
    if not given:
        return WRONG, "未作答"
    candidates = [expected, *(accepted or ())]
    if any(given == normalize_text(item) for item in candidates):
        return HIT, "填空正确"
    return WRONG, "填空错误"


def fill_blanks_of(raw: Any) -> list[list[str]] | None:
    """从 ``options`` 解析填空题的**每空答案键**。

    约定（train_question v1.2.0 起）：每个空一项，``key`` 为空序号（"1"、"2"…），
    ``text`` 为该空的标准答案——同空多个可接受写法用 ``;`` 分隔（不能用 ``|``，
    那是作答的分空分隔符）。任一空缺序号或缺答案即整体视为无键（返回 None）：
    没有答案键的填空不具备机判条件。
    """
    options = parse_options(raw)
    if not options:
        return None
    entries: list[tuple[int, list[str]]] = []
    for entry in options:
        key = str(entry.get("key") or "").strip()
        text = str(entry.get("text") or "").strip()
        if not key.isdigit() or not text:
            return None
        variants = [v for v in (p.strip() for p in text.split(";")) if v]
        if not variants:
            return None
        entries.append((int(key), variants))
    entries.sort(key=lambda kv: kv[0])
    return [variants for _, variants in entries]


def grade_fill_keyed(answer: Any, *, blanks: Sequence[Sequence[str]]) -> tuple[str, str, float]:
    """带答案键的多空填空判分：作答按 ``|`` 分空，逐空归一化精确比对。

    得分 = 命中空数 / 总空数（**部分给分**），全部命中才算通过。
    **不调用任何大模型。**
    """
    parts = [p for p in str(answer or "").split("|")]
    results = []
    for i, variants in enumerate(blanks):
        given = normalize_text(parts[i]) if i < len(parts) else ""
        results.append(bool(given) and any(given == normalize_text(v) for v in variants))
    hit = sum(1 for ok in results if ok)
    score = hit / len(blanks)
    if all(results):
        return HIT, f"{len(blanks)} 空全部答对", score
    missed = "、".join(f"第 {i + 1} 空" for i, ok in enumerate(results) if not ok)
    return WRONG, f"{len(blanks)} 空答对 {hit} 空（{missed}与标准答案不符）", score


def parse_options(raw: Any) -> list[dict[str, Any]] | None:
    """解析 ``question_bank.options``（JSON 数组：key/text/is_correct），坏数据一律当没有选项。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list) or not raw:
        return None
    return [entry for entry in raw if isinstance(entry, dict)]


def correct_key_of(raw: Any) -> str | None:
    """取唯一正确项的 key（有且仅有一个 ``is_correct``；异常形态返回 None）。"""
    options = parse_options(raw)
    if not options:
        return None
    correct = [str(entry.get("key") or "") for entry in options if entry.get("is_correct")]
    return correct[0] if len(correct) == 1 else None


def fill_key_from_reference(expected: Any) -> list[list[str]] | None:
    """参考答案本身是竖线拼接的简洁答案键（如 ``"RDB|AOF"``）→ 每空一项的键。

    沿用既有约定（test_today_flow 钉住）：出题模型给出 pipe 拼接的简洁参考答案时
    本身就是每空标准答案。任一段为空或只有一段则不算键（叙述性参考答案走别的口径）。
    """
    if expected is None:
        return None
    parts = [p.strip() for p in str(expected).split("|")]
    if len(parts) < 2 or not all(parts):
        return None
    return [[p] for p in parts]


def _fill_grade_result(
    answer: Any, *, expected: Any, options: Any
) -> "GradeResult | None":
    """填空判分统一口径（grade_objective 与 grade_question 共用）。

    * 有每空答案键（``options`` 按约定存每空标准答案，v1.2.0 起生成侧固化）→
      逐空比对，部分给分；
    * 无 options 键但参考答案本身是 ``"RDB|AOF"`` 形式的 pipe 键 → 同样逐空比对
      （旧约定，test_today_flow::test_fill_inline_join_grading 钉住）；
    * 无键且参考答案是叙述文、作答含 ``|``（多空）→ 不具备机判条件，返回 None
      交回语义判分链路——2026-11-23 修复：此前整串与参考答案全文精确比对，
      多空填空必 0 分（训练 144 "内存|单线程" 全对被判 fail 的根因）；
    * 无键单空 → 保留旧口径：与参考答案精确比对（答案本身即标准词时成立）。
    """
    blanks = fill_blanks_of(options)
    if blanks is None:
        blanks = fill_key_from_reference(expected)
    if blanks:
        verdict, reason, score = grade_fill_keyed(answer, blanks=blanks)
    elif "|" in str(answer or ""):
        return None
    else:
        verdict, reason = grade_fill(answer, expected=expected)
        score = 1.0 if verdict == HIT else 0.0
    return GradeResult(
        question_type="fill",
        verdict=verdict,
        passed=verdict == HIT,
        score=score,
        graded_by="rule",
        reason=reason,
    )


def grade_objective(
    question_type: str,
    answer: Any,
    *,
    expected: Any = None,
    correct_key: Any = None,
    options: Sequence[Mapping[str, Any]] | None = None,
) -> "GradeResult | None":
    """客观题（choice / fill）确定性判分的统一入口；``qa`` 返回 None 走语义链路。

    2026-11-15 修复：此前主链（answer_service / quiz_service）没有按题型分流，
    选择题也被送进 LLM 语义判分——违反本模块头部的硬约束（客观题 MUST NOT 调用大模型）。
    """
    kind = str(question_type or DEFAULT_QUESTION_TYPE)
    if kind == "choice":
        verdict, reason = grade_choice(answer, correct_key=correct_key, options=options)
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
        return _fill_grade_result(answer, expected=expected, options=options)
    return None


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
    """题型的整场评分权重：客观题 0.4，主观题 0.6。"""
    return OBJECTIVE_WEIGHT if str(question_type) in OBJECTIVE_TYPES else SUBJECTIVE_WEIGHT


def overall_score(results: Sequence["GradeResult"]) -> float | None:
    """整场评分：按题型权重对单题得分做加权平均。

    权重和不为 1 时按实际权重归一化；没有任何成绩时返回 ``None``
    （不要用 0 冒充"考了零分"）。整场评分**不重新调用模型**，只做确定性聚合。
    """
    return pair_weighted_score([(item.question_type, item.score) for item in results])


def pair_weighted_score(pairs: Sequence[tuple[str, float | None]]) -> float | None:
    """按题型权重聚合 ``(题型, 得分)``；全部没有分数时返回 None（不伪造分数）。"""
    entries = [
        (str(question_type), float(score))
        for question_type, score in pairs
        if score is not None
    ]
    if not entries:
        return None
    total_weight = sum(type_weight(question_type) for question_type, _ in entries)
    if total_weight <= 0:
        return None
    return (
        sum(score * type_weight(question_type) for question_type, score in entries)
        / total_weight
    )


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
        return _fill_grade_result(answer, expected=expected_answer, options=options)

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


# ------------------------------------------------- 证据引用（grading-rubric-hardening）

#: 归一化只保留字母数字与中日韩字符——标点、空白、大小写差异不参与证据比对
_NORMALIZE_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def normalize_for_evidence(text: Any) -> str:
    """证据比对用的归一化：小写、去一切非字母数字/非中文字符。"""
    return _NORMALIZE_RE.sub("", str(text or "").lower())


def verify_evidence(answer_text: Any, evidence: Any) -> bool:
    """核验证据片段确实摘自用户作答（归一化后子串匹配）。

    仅作审计标记：返回 False **不改变**判定与得分（见 change 设计 D1——
    模型引用常微改写，先积累 evidence_ok 数据再定降级策略）。
    """
    needle = normalize_for_evidence(evidence)
    if not needle:
        return False
    return needle in normalize_for_evidence(answer_text)


def build_point_results(
    result: GradeResult,
    *,
    text_by_pid: Mapping[str, str] | None = None,
    evidence_by_pid: Mapping[str, str] | None = None,
    answer_text: str = "",
) -> str:
    """把判分结果组装成 dict 格式的 ``point_results``（practice_attempts 落库用）。

    每条 detail 快照 point_text 与 evidence，并记 ``evidence_ok``：
    hit/partial/wrong → bool（归一化核验）；missing → None（无证据不适用）。
    证据**不参与**得分——score/coverage/correctness 全部来自 ``result`` 本身。
    """
    texts = dict(text_by_pid or {})
    evidences = dict(evidence_by_pid or {})
    detail: list[dict[str, Any]] = []
    for entry in result.detail:
        pid = str(entry.get("point_id") or "")
        verdict = str(entry.get("verdict") or MISSING)
        if verdict == MISSING:
            evidence, evidence_ok = "", None
        else:
            evidence = str(evidences.get(pid, "") or "")
            evidence_ok = verify_evidence(answer_text, evidence)
        detail.append(
            {
                "point_id": pid,
                "text": str(texts.get(pid, "")),
                "verdict": verdict,
                "weight": entry.get("weight"),
                "required": bool(entry.get("required")),
                "evidence": evidence,
                "evidence_ok": evidence_ok,
            }
        )
    return json.dumps(
        {
            "coverage": result.coverage,
            "correctness": result.correctness,
            "missing": list(result.missing),
            "incorrect": list(result.incorrect),
            "required_missing": list(result.required_missing),
            "detail": detail,
        },
        ensure_ascii=False,
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
    "grade_fill_keyed",
    "fill_blanks_of",
    "fill_key_from_reference",
    "grade_question",
    "load_points",
    "normalize_text",
    "overall_score",
    "record_attempt_score",
    "score_points",
    "type_weight",
]
