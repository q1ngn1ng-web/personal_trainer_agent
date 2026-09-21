"""训练作答：**系统出题 → 用户作答 → 系统判分**。

这一层修掉一个逻辑错误：以前训练项只有"知识点名"，判对判错靠用户自己点按钮——
既没有题目，也把客观表现交给了主观。现在按用户要求改成：

* 每道训练题**由系统出题**（基于资料片段与轮次难度，落库到 `plan_items.question`）；
* 用户在任务卡上**作答**，系统**判分**（口径与测验一致，只出 pass / fail）；
* 判分结果写进 `practice_attempts`（客观表现的唯一来源），连续 2 次通过 → 达标。

例外（后置能力）：题在**第三方题库**（如 LeetCode）且对方没有 API 时，系统只能安排任务、
用户自己核对结果——这条**本轮不做**，需要时再单独开放"外部题目自评"入口。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.core.plan import local_today
from src.db.sqlite import get_connection
from src.llm.client import complete, log_llm_failure
from src.llm.schema import SCHEMA_REGISTRY
from src.services import attempt_service, plan_service

logger = logging.getLogger("src.services.answer_service")

#: 出题时喂给模型的资料片段长度
_SAMPLE_CHARS: int = 600

#: 5 轮的轮次总数（题目难度随轮次递进）
_TOTAL_ROUNDS: int = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def _task_context(active: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    """取一条计划项 + 它对应的训练项/训练信息。"""
    row = active.execute(
        """
        SELECT p.id AS plan_id, p.training_id, p.item_key, p.round_index, p.kind,
               p.question, p.reference_answer, p.answer_text, p.verdict, p.status,
               t.topic AS training_topic,
               i.title, i.knowledge_point, i.item_type, i.difficulty_tier, i.source_chunk_ids
        FROM plan_items p
        JOIN trainings t ON t.id = p.training_id
        LEFT JOIN training_items i ON i.item_key = p.item_key AND i.stage_id IN (
            SELECT s.id FROM path_stages s WHERE s.path_id = (
                SELECT tp.id FROM training_paths tp WHERE tp.training_id = p.training_id
                ORDER BY (tp.status = 'confirmed') DESC, tp.version DESC LIMIT 1
            )
        )
        WHERE p.id = ?
        """,
        (int(plan_id),),
    ).fetchone()
    return dict(row) if row else None


def _sample_text(active: sqlite3.Connection, source_chunk_ids: Any) -> str:
    """取训练项回指的资料片段（出题依据）。"""
    ids = source_chunk_ids
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except json.JSONDecodeError:
            ids = []
    if not isinstance(ids, list) or not ids:
        return ""
    placeholders = ", ".join("?" for _ in ids)
    try:
        rows = active.execute(
            f"SELECT text FROM source_chunks WHERE id IN ({placeholders}) ORDER BY ordinal LIMIT 2",
            [int(value) for value in ids],
        ).fetchall()
    except (TypeError, ValueError, sqlite3.Error):
        return ""
    return "\n\n".join(str(row["text"]) for row in rows)[:_SAMPLE_CHARS]


def _probe_question(
    active: sqlite3.Connection, training_id: int, knowledge_point: str
) -> tuple[str, str]:
    """理解边缘探测阶段留下的现成题目（八股资料里常常就是问答对）。"""
    if not knowledge_point:
        return "", ""
    row = active.execute(
        "SELECT question, reference_answer FROM edge_assessments "
        "WHERE training_id = ? AND knowledge_point = ? ORDER BY id DESC LIMIT 1",
        (int(training_id), knowledge_point),
    ).fetchone()
    if row is None:
        return "", ""
    return str(row["question"] or ""), str(row["reference_answer"] or "")


def ensure_question(
    plan_id: int, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """确保这条计划项有题目与参考答案（幂等，已生成就不再调用模型）。

    出题优先级：模型出题 → 探测阶段的现成题 → 通用问法（保证界面上永远有题可答）。
    """
    active = _connect(conn)
    own = conn is None
    try:
        context = _task_context(active, plan_id)
        if context is None:
            raise ValueError(f"plan item not found: {plan_id}")
        if context.get("question"):
            return {
                "question": str(context["question"]),
                "reference_answer": str(context.get("reference_answer") or ""),
                "source": "stored",
            }

        knowledge_point = str(context.get("knowledge_point") or context.get("title") or "")
        sample = _sample_text(active, context.get("source_chunk_ids"))
        question, answer, source = "", "", "fallback"

        variables = {
            "topic": str(context.get("training_topic") or ""),
            "knowledge_point": knowledge_point,
            "round_index": int(context.get("round_index") or 1),
            "total_rounds": _TOTAL_ROUNDS,
            "sample_text": sample or "（这道题没有关联资料片段，请按知识点本身出题）",
        }
        try:
            result = complete(
                "train_question", variables, schema=SCHEMA_REGISTRY["train_question"]
            )
            output = result.get("output_json") or {}
            question = str(output.get("question") or "").strip()
            answer = str(output.get("reference_answer") or "").strip()
            if question:
                source = "llm"
        except Exception as exc:  # 模型不可用不该让用户没题可做
            logger.warning("ensure_question: LLM unavailable (%s), using fallback", exc)
            log_llm_failure("train_question", json.dumps(variables, ensure_ascii=False), exc)

        if not question:
            question, answer = _probe_question(
                active, int(context["training_id"]), knowledge_point
            )
            source = "probe" if question else "fallback"
        if not question:
            round_index = int(context.get("round_index") or 1)
            hint = "凭理解说出" if round_index <= 2 else "不看资料讲清"
            question = f"请{hint}「{knowledge_point}」的关键要点与适用场景。"
            answer = sample[:200] or "（资料里没有可用片段，先按你的理解回答）"

        active.execute(
            "UPDATE plan_items SET question = ?, reference_answer = ? WHERE id = ?",
            (question, answer or None, int(plan_id)),
        )
        if own:
            active.commit()
        return {"question": question, "reference_answer": answer, "source": source}
    finally:
        if own:
            active.close()


def _grade_answer(context: dict[str, Any], answer: str) -> tuple[bool, str, str]:
    """用与测验相同的口径判分。返回 ``(是否判分成功, verdict, 理由)``。"""
    payload = [
        {
            "item_key": str(context.get("item_key") or ""),
            "question": str(context.get("question") or ""),
            "reference_answer": str(context.get("reference_answer") or ""),
            "answer": answer,
        }
    ]
    variables = {"items": json.dumps(payload, ensure_ascii=False, indent=2)}
    try:
        result = complete("quiz_grade", variables, schema=SCHEMA_REGISTRY["quiz_grade"])
        output = result.get("output_json") or {}
    except Exception as exc:
        logger.warning("grade_answer: LLM unavailable (%s)", exc)
        log_llm_failure("quiz_grade", json.dumps(variables, ensure_ascii=False), exc)
        return False, "", ""
    results = output.get("results") or []
    if not results:
        return False, "", ""
    entry = results[0]
    verdict = "pass" if entry.get("verdict") == "pass" else "fail"
    return True, verdict, str(entry.get("reason") or "")


def submit_answer(
    plan_id: int,
    answer: str,
    *,
    today: Any = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """提交作答 → 系统判分 → 记录客观表现 → 标记练过。

    **判分不可用时不会伪造对错**：答案照存，但返回 `graded=False`，
    不写 `practice_attempts`（客观表现宁缺勿假），页面上会显示参考答案让用户自己核对。
    """
    text = str(answer or "").strip()
    if not text:
        raise ValueError("作答不能为空")
    question = ensure_question(plan_id, conn=conn)
    active = _connect(conn)
    own = conn is None
    try:
        context = _task_context(active, plan_id)
        if context is None:
            raise ValueError(f"plan item not found: {plan_id}")
        context["question"] = question["question"]
        context["reference_answer"] = question["reference_answer"]

        active.execute(
            "UPDATE plan_items SET answer_text = ? WHERE id = ?", (text, int(plan_id))
        )
        if own:
            active.commit()

        graded, verdict, reason = _grade_answer(context, text)
        training_id = int(context["training_id"])
        item_key = str(context["item_key"])
        mastered = False

        if graded:
            active.execute(
                "UPDATE plan_items SET verdict = ?, graded_by = 'llm', graded_at = ? WHERE id = ?",
                (verdict, _now(), int(plan_id)),
            )
            if own:
                active.commit()
            attempt_service.record_attempt(
                training_id,
                item_key,
                verdict,
                plan_id=int(plan_id),
                round_index=int(context.get("round_index") or 0) or None,
                # 判分来源：模型判的日常作答（枚举里 self=自评 / quiz=测验 / llm=模型判分）
                source="llm",
                conn=active,
            )
            mastered = attempt_service.mark_mastered_if_ready(training_id, item_key, conn=active)
        else:
            active.execute(
                "UPDATE plan_items SET graded_by = 'unavailable' WHERE id = ?", (int(plan_id),)
            )

        # 不论判分是否成功，"练过"都成立（用户确实做了这道题），题库也随之登记
        plan_service.complete_tasks(
            [int(plan_id)], completed=True, today=today or local_today(), conn=active
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()

    return {
        "graded": graded,
        "verdict": verdict if graded else None,
        "reason": reason,
        "reference_answer": question["reference_answer"],
        "question_source": question.get("source"),
        "mastered": mastered,
    }


def mark_practiced_only(
    plan_id: int, *, today: Any = None, conn: sqlite3.Connection | None = None
) -> None:
    """只标记"练过"（不判分、不留客观记录）——用于"只读了一遍/背了一遍"的场景。"""
    plan_service.complete_tasks(
        [int(plan_id)], completed=True, today=today or local_today(), conn=conn
    )


__all__ = ["ensure_question", "mark_practiced_only", "submit_answer"]
