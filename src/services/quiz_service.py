"""测验服务：取题（排除冷却期内的原题）、生成变式、判分、成绩与回退重练。

对应 OpenSpec change ``training-execution-feedback`` 的 ``periodic-assessment`` 能力与 ADR-0016：

* 题目从**题库**里抽，且只抽**冷却期已过**的题（不是"近期练过的原题"）
* 优先用 LLM 生成**变式题**（换场景/换问法/改条件）；LLM 不可用时退回冷却期外的原题并显式标记
* 判分优先用 LLM；不可用时降级为**用户自评**（并标注这是自评，不让系统假装判过分）
* 未通过 → 相关题目追加**补练轮次**（回退重练，ADR-0016 决策 5）
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.core.plan import local_today
from src.db.models import Assessment, AssessmentItem
from src.db.sqlite import get_connection
from src.llm.client import complete, log_llm_failure
from src.llm.schema import SCHEMA_REGISTRY
from src.services import attempt_service, plan_service

logger = logging.getLogger("src.services.quiz_service")

#: 一次测验最多几道题（题量上限，ADR-0018 决策 7 的成本控制）
QUIZ_SIZE: int = 5

#: 通过线：答对比例
QUIZ_PASS_RATIO: float = 0.8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


@dataclass
class QuizQuestion:
    """一道测验题。"""

    item_key: str
    knowledge_point: str
    question: str
    reference_answer: str
    is_variant: bool = True


@dataclass
class QuizResult:
    """一次测验的结果摘要。"""

    assessment_id: int
    training_id: int
    question_count: int
    score: float
    passed: bool
    failed_items: list[dict[str, Any]] = field(default_factory=list)
    extra_rounds: int = 0
    graded_by: str = "llm"


def question_pool(
    training_id: int, *, today: date | None = None, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """可抽题的池子：题库里**冷却期已过**的题（冷却期内的近期原题不得进池，ADR-0016）。"""
    return plan_service.drawable_questions(training_id, today=today, conn=conn)


def pick_blueprints(pool: list[dict[str, Any]], *, size: int = QUIZ_SIZE) -> list[dict[str, Any]]:
    """选题：先保证**知识点覆盖**（每个知识点最多一题），再按练过次数补足。"""
    if size <= 0 or not pool:
        return []
    covered: set[str] = set()
    picked: list[dict[str, Any]] = []
    for row in sorted(pool, key=lambda item: -int(item.get("practiced_count") or 0)):
        point = str(row.get("knowledge_point") or "")
        if point and point in covered:
            continue
        picked.append(row)
        if point:
            covered.add(point)
        if len(picked) >= size:
            return picked
    # 知识点不够时，用剩余的题补足
    for row in sorted(pool, key=lambda item: -int(item.get("practiced_count") or 0)):
        if len(picked) >= size:
            break
        if row not in picked:
            picked.append(row)
    return picked[:size]


def build_questions(blueprints: list[dict[str, Any]]) -> tuple[list[QuizQuestion], bool]:
    """把蓝本题变成测验题：优先 LLM 变式，失败则退回原题（标记 is_variant=False）。"""
    if not blueprints:
        return [], False
    payload = [
        {
            "item_key": str(row.get("item_key")),
            "knowledge_point": str(row.get("knowledge_point") or ""),
            "question": str(row.get("question_text") or ""),
            "reference_answer": str(row.get("answer_text") or ""),
        }
        for row in blueprints
    ]
    variables = {"blueprints": json.dumps(payload, ensure_ascii=False, indent=2)}
    output: dict[str, Any] = {}
    try:
        result = complete("quiz_variant", variables, schema=SCHEMA_REGISTRY["quiz_variant"])
        output = result.get("output_json") or {}
    except Exception as exc:  # LLM 不可用不该阻塞测验
        logger.warning("build_questions: LLM unavailable (%s), falling back to banked originals", exc)
        log_llm_failure("quiz_variant", json.dumps(variables, ensure_ascii=False), exc)

    by_key = {str(row.get("item_key")): row for row in blueprints}
    questions: list[QuizQuestion] = []
    for raw in output.get("questions") or []:
        key = str(raw.get("item_key") or "")
        blueprint = by_key.get(key)
        if blueprint is None:
            continue
        questions.append(
            QuizQuestion(
                item_key=key,
                knowledge_point=str(blueprint.get("knowledge_point") or ""),
                question=str(raw.get("question") or "").strip(),
                reference_answer=str(
                    raw.get("reference_answer") or blueprint.get("answer_text") or ""
                ).strip(),
                is_variant=True,
            )
        )
    questions = [question for question in questions if question.question]
    if questions:
        return questions, True
    # 降级：冷却期外的原题（此时已不属于"近期练过的原题"），显式标记为非变式
    fallback = [
        QuizQuestion(
            item_key=str(row.get("item_key")),
            knowledge_point=str(row.get("knowledge_point") or ""),
            question=str(row.get("question_text") or "").strip() or "（题库里这道题没有题干）",
            reference_answer=str(row.get("answer_text") or ""),
            is_variant=False,
        )
        for row in blueprints
    ]
    return fallback, False


def start_assessment(
    training_id: int,
    *,
    trigger: str = "manual",
    plan_id: int | None = None,
    size: int = QUIZ_SIZE,
    today: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> Assessment:
    """生成一次测验批次（题目落库，等待作答）。"""
    if trigger not in ("scheduled", "manual", "stage_end"):
        raise ValueError(f"invalid trigger: {trigger!r}")
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        pool = question_pool(training_id, today=effective_today, conn=active)
        blueprints = pick_blueprints(pool, size=size)
        if not blueprints:
            raise ValueError(
                "题库里还没有可抽的题：练过的题要过 14 天冷却期才能进入测验（ADR-0016）"
            )
        questions, _used_llm = build_questions(blueprints)
        cursor = active.execute(
            "INSERT INTO assessments (training_id, plan_id, trigger, status, question_count, "
            "created_at) VALUES (?, ?, ?, 'in_progress', ?, ?)",
            (int(training_id), plan_id, trigger, len(questions), _now()),
        )
        assessment_id = int(cursor.lastrowid)
        active.executemany(
            "INSERT INTO assessment_items (assessment_id, ordinal, item_key, knowledge_point, "
            "question, reference_answer, is_variant, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    assessment_id,
                    index,
                    question.item_key,
                    question.knowledge_point or None,
                    question.question,
                    question.reference_answer or None,
                    1 if question.is_variant else 0,
                    _now(),
                )
                for index, question in enumerate(questions, start=1)
            ],
        )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        logger.info(
            "start_assessment: training %s -> assessment %s (%d 题, trigger=%s)",
            training_id,
            assessment_id,
            len(questions),
            trigger,
        )
    finally:
        if own:
            active.close()
    return Assessment.from_row(row)


def load_assessment(
    assessment_id: int, *, conn: sqlite3.Connection | None = None
) -> Assessment | None:
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT * FROM assessments WHERE id = ?", (int(assessment_id),)
        ).fetchone()
    finally:
        if own:
            active.close()
    return Assessment.from_row(row) if row else None


def load_items(
    assessment_id: int, *, conn: sqlite3.Connection | None = None
) -> list[AssessmentItem]:
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM assessment_items WHERE assessment_id = ? ORDER BY ordinal",
            (int(assessment_id),),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [AssessmentItem.from_row(row) for row in rows]


def latest_assessment(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> Assessment | None:
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT * FROM assessments WHERE training_id = ? ORDER BY id DESC LIMIT 1",
            (int(training_id),),
        ).fetchone()
    finally:
        if own:
            active.close()
    return Assessment.from_row(row) if row else None


def pending_quiz_plan(
    training_id: int, *, today: date | None = None, conn: sqlite3.Connection | None = None
) -> dict[str, Any] | None:
    """今天（或已累计到今天的）测验任务计划项。"""
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            "SELECT * FROM plan_items WHERE training_id = ? AND kind = 'assessment' "
            "AND status = 'planned' AND due_date <= ? ORDER BY due_date LIMIT 1",
            (int(training_id), effective_today.isoformat()),
        ).fetchone()
    finally:
        if own:
            active.close()
    return dict(row) if row else None


def save_answers(
    assessment_id: int, answers: dict[int, str], *, conn: sqlite3.Connection | None = None
) -> int:
    """保存用户作答（item_id → 答案文本）。"""
    active = _connect(conn)
    own = conn is None
    try:
        updated = 0
        for item_id, answer in answers.items():
            active.execute(
                "UPDATE assessment_items SET user_answer = ? WHERE id = ? AND assessment_id = ?",
                (str(answer or "").strip(), int(item_id), int(assessment_id)),
            )
            updated += 1
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return updated


def grade_with_llm(
    assessment_id: int, *, conn: sqlite3.Connection | None = None
) -> bool:
    """用 LLM 判分。返回是否判分成功（失败时由用户自评兜底）。"""
    items = load_items(assessment_id, conn=conn)
    payload = [
        {
            "item_key": item.item_key,
            "question": item.question,
            "reference_answer": item.reference_answer or "",
            "answer": item.user_answer or "",
        }
        for item in items
    ]
    variables = {"items": json.dumps(payload, ensure_ascii=False, indent=2)}
    output: dict[str, Any] = {}
    try:
        result = complete("quiz_grade", variables, schema=SCHEMA_REGISTRY["quiz_grade"])
        output = result.get("output_json") or {}
    except Exception as exc:
        logger.warning("grade_with_llm: LLM unavailable (%s), 需要用户自评", exc)
        log_llm_failure("quiz_grade", json.dumps(variables, ensure_ascii=False), exc)
        return False

    verdicts: dict[str, dict[str, Any]] = {}
    for raw in output.get("results") or []:
        verdicts[str(raw.get("item_key") or "")] = raw
    if not verdicts:
        return False

    active = _connect(conn)
    own = conn is None
    try:
        for item in items:
            entry = verdicts.get(item.item_key)
            if entry is None:
                continue
            active.execute(
                "UPDATE assessment_items SET verdict = ?, reason = ? WHERE id = ?",
                (
                    "pass" if entry.get("verdict") == "pass" else "fail",
                    str(entry.get("reason") or ""),
                    item.id,
                ),
            )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return True


def save_manual_verdicts(
    assessment_id: int, verdicts: dict[int, str], *, conn: sqlite3.Connection | None = None
) -> int:
    """用户自评兜底（LLM 不可用时）：标记每道题对错，并注明来源是自评。"""
    active = _connect(conn)
    own = conn is None
    try:
        updated = 0
        for item_id, verdict in verdicts.items():
            if verdict not in ("pass", "fail"):
                continue
            active.execute(
                "UPDATE assessment_items SET verdict = ?, reason = ? WHERE id = ? "
                "AND assessment_id = ?",
                (verdict, "自评（LLM 判分不可用）", int(item_id), int(assessment_id)),
            )
            updated += 1
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return updated


def _extra_round(
    active: sqlite3.Connection, training_id: int, item_key: str, *, today: date
) -> bool:
    """给某道题追加一轮补练（测验未通过的"回退重练"）。"""
    row = active.execute(
        "SELECT COALESCE(MAX(round_index), 0) AS max_round FROM plan_items "
        "WHERE training_id = ? AND item_key = ?",
        (int(training_id), str(item_key)),
    ).fetchone()
    next_round = int(row["max_round"] or 0) + 1
    due = (today + timedelta(days=1)).isoformat()
    minutes = active.execute(
        "SELECT i.item_type FROM training_items i "
        "JOIN path_stages s ON s.id = i.stage_id "
        "JOIN training_paths p ON p.id = s.path_id "
        "WHERE p.training_id = ? AND i.item_key = ? "
        "ORDER BY (p.status = 'confirmed') DESC, p.version DESC LIMIT 1",
        (int(training_id), str(item_key)),
    ).fetchone()
    planned = plan_service.TYPE_MINUTES.get(
        str(minutes["item_type"] if minutes else ""), 15
    )
    cursor = active.execute(
        "INSERT OR IGNORE INTO plan_items (training_id, item_key, round_index, kind, due_date, "
        "anchor_date, original_date, status, planned_minutes, reason, created_at) "
        "VALUES (?, ?, ?, 'train', ?, ?, ?, 'planned', ?, 'quiz_failed', ?)",
        (int(training_id), str(item_key), next_round, due, due, due, planned, _now()),
    )
    return cursor.rowcount > 0


def finish_assessment(
    assessment_id: int,
    *,
    pass_ratio: float = QUIZ_PASS_RATIO,
    today: date | None = None,
    graded_by: str = "llm",
    conn: sqlite3.Connection | None = None,
) -> QuizResult:
    """结算测验：算成绩、写达标与作答记录、未通过则追加补练轮次。"""
    effective_today = today or local_today()
    active = _connect(conn)
    own = conn is None
    try:
        assessment_row = active.execute(
            "SELECT * FROM assessments WHERE id = ?", (int(assessment_id),)
        ).fetchone()
        if assessment_row is None:
            raise ValueError(f"assessment not found: {assessment_id}")
        training_id = int(assessment_row["training_id"])
        items = load_items(assessment_id, conn=active)
        total = len(items)
        passed_items = [item for item in items if item.verdict == "pass"]
        failed_items = [item for item in items if item.verdict != "pass"]
        score = (len(passed_items) / total) if total else 0.0
        passed = bool(total) and score >= pass_ratio

        active.execute(
            "UPDATE assessments SET status = 'completed', score = ?, passed = ?, completed_at = ? "
            "WHERE id = ?",
            (score, 1 if passed else 0, _now(), int(assessment_id)),
        )
        if own:
            active.commit()

        # 测验结果也进入作答记录：客观通道要把测验算进去
        for item in items:
            attempt_service.record_attempt(
                training_id,
                item.item_key,
                "pass" if item.verdict == "pass" else "fail",
                source="quiz",
                note=f"测验 #{assessment_id}",
                conn=active,
            )
            if item.verdict == "pass":
                attempt_service.mark_mastered_if_ready(training_id, item.item_key, conn=active)

        extra = 0
        for item in failed_items:
            if _extra_round(active, training_id, item.item_key, today=effective_today):
                extra += 1
        if assessment_row["plan_id"]:
            plan_service.complete_tasks(
                [int(assessment_row["plan_id"])], completed=True, today=effective_today, conn=active
            )
        if own:
            active.commit()
    finally:
        if own:
            active.close()

    return QuizResult(
        assessment_id=int(assessment_id),
        training_id=training_id,
        question_count=total,
        score=score,
        passed=passed,
        failed_items=[
            {"item_id": item.id, "knowledge_point": item.knowledge_point, "reason": item.reason}
            for item in failed_items
        ],
        extra_rounds=extra,
        graded_by=graded_by,
    )


__all__ = [
    "QUIZ_PASS_RATIO",
    "QUIZ_SIZE",
    "QuizQuestion",
    "QuizResult",
    "build_questions",
    "finish_assessment",
    "grade_with_llm",
    "latest_assessment",
    "load_assessment",
    "load_items",
    "pending_quiz_plan",
    "pick_blueprints",
    "question_pool",
    "save_answers",
    "save_manual_verdicts",
    "start_assessment",
]
