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
from src.llm.client import complete
from src.llm.schema import SCHEMA_REGISTRY
from src.services import attempt_service, memory_service, plan_service

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
               p.question, p.reference_answer, p.points, p.answer_text, p.verdict, p.status,
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


def _normalize_points(raw: Any) -> list[dict[str, Any]] | None:
    """把模型输出的要点清单整理成可落库的规范形态。

    宽进严出：缺 point_id / 重复 id / 权重非法的条目逐条修正或丢弃；
    最终少于 1 条有效要点时返回 ``None``（判分自动退回整体二元判定）。
    """
    if not isinstance(raw, list):
        return None
    points: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            weight = float(item.get("weight"))
            if weight <= 0:
                weight = 1.0
        except (TypeError, ValueError):
            weight = 1.0
        points.append(
            {
                "point_id": str(item.get("point_id") or "").strip(),
                "text": text,
                "weight": weight,
                "is_required": bool(item.get("is_required")),
            }
        )
    if not points:
        return None
    # 补齐 / 去重 point_id：以 p1、p2… 重排，保证键唯一且稳定
    seen: set[str] = set()
    for index, point in enumerate(points, start=1):
        pid = point["point_id"]
        if not pid or pid in seen:
            pid = f"p{index}"
            counter = index
            while pid in seen:
                counter += 1
                pid = f"p{counter}"
            point["point_id"] = pid
        seen.add(pid)
    return points


def _parse_points_json(raw: Any) -> list[dict[str, Any]]:
    """读取 plan_items.points 列（JSON），坏数据一律当没有要点处理。"""
    if isinstance(raw, list):
        normalized = _normalize_points(raw)
        return normalized or []
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    normalized = _normalize_points(data)
    return normalized or []


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
                "points": _parse_points_json(context.get("points")),
            }

        knowledge_point = str(context.get("knowledge_point") or context.get("title") or "")
        sample = _sample_text(active, context.get("source_chunk_ids"))
        question, answer, source = "", "", "fallback"
        points_json: str | None = None

        variables = {
            "topic": str(context.get("training_topic") or ""),
            "knowledge_point": knowledge_point,
            "round_index": int(context.get("round_index") or 1),
            "total_rounds": _TOTAL_ROUNDS,
            "sample_text": sample or "（这道题没有关联资料片段，请按知识点本身出题）",
        }
        try:
            result = complete(
                "train_question",
                variables,
                schema=SCHEMA_REGISTRY["train_question"],
                training_id=int(context["training_id"]),
            )
            output = result.get("output_json") or {}
            question = str(output.get("question") or "").strip()
            answer = str(output.get("reference_answer") or "").strip()
            if question:
                source = "llm"
                # 出题时固化要点清单：判分只引用不再生成（与测验同约束）
                normalized = _normalize_points(output.get("points"))
                if normalized:
                    points_json = json.dumps(normalized, ensure_ascii=False)
        except Exception as exc:  # 模型不可用不该让用户没题可做（失败审计由客户端写入）
            logger.warning("ensure_question: LLM unavailable (%s), using fallback", exc)

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
            "UPDATE plan_items SET question = ?, reference_answer = ?, points = ? WHERE id = ?",
            (question, answer or None, points_json, int(plan_id)),
        )
        if own:
            active.commit()
        return {
            "question": question,
            "reference_answer": answer,
            "source": source,
            "points": json.loads(points_json) if points_json else [],
        }
    finally:
        if own:
            active.close()


def _grade_answer(context: dict[str, Any], answer: str) -> dict[str, Any]:
    """用与测验相同的口径判分：有要点清单走「逐条判定 → 规则算分」，否则退回整体二元判定。

    返回 ``{"graded", "verdict", "reason", "score", "point_results"}``；
    ``score`` / ``point_results`` 仅在要点判分路径下有值（客观表现可解释的来源）。
    """
    from src.services.grading_service import (
        MISSING,
        POINT_VERDICTS,
        PointSpec,
        grade_question,
    )

    specs = [
        PointSpec(
            point_id=str(point["point_id"]),
            text=str(point["text"]),
            weight=float(point["weight"]),
            required=bool(point["is_required"]),
        )
        for point in _parse_points_json(context.get("points"))
    ]
    payload = [
        {
            "item_key": str(context.get("item_key") or ""),
            "question": str(context.get("question") or ""),
            "reference_answer": str(context.get("reference_answer") or ""),
            "answer": answer,
            "points": [
                {
                    "point_id": spec.point_id,
                    "text": spec.text,
                    "weight": spec.weight,
                    "is_required": spec.required,
                }
                for spec in specs
            ],
        }
    ]
    outcome = {
        "graded": False,
        "verdict": "",
        "reason": "",
        "score": None,
        "point_results": None,
    }
    variables = {
        "items": json.dumps(payload, ensure_ascii=False, indent=2),
        "memory_block": memory_service.grade_memory_block(
            context.get("training_id"), context.get("item_key")
        ),
    }
    try:
        result = complete(
            "quiz_grade",
            variables,
            schema=SCHEMA_REGISTRY["quiz_grade"],
            training_id=context.get("training_id"),
            call_purpose="daily_grade",
        )
        output = result.get("output_json") or {}
    except Exception as exc:
        # 失败审计由客户端写入 llm_calls；判分不可用时 graded=False，不伪造对错
        logger.warning("grade_answer: LLM unavailable (%s)", exc)
        return outcome
    results = output.get("results") or []
    if not results:
        return outcome
    entry = results[0]
    reason = str(entry.get("reason") or "")

    # 要点判分路径：模型逐条判定，规则层算分与达标（模型不得直接决定 pass/fail）
    verdicts: dict[str, str] = {}
    for point in entry.get("point_verdicts") or []:
        if not isinstance(point, dict):
            continue
        pid = str(point.get("point_id") or "")
        verdict = str(point.get("verdict") or "")
        if pid and verdict in POINT_VERDICTS:
            verdicts[pid] = verdict
    if specs and verdicts:
        graded = grade_question(
            "qa",
            answer=answer,
            points=specs,
            point_verdicts=verdicts,
        )
        point_results = json.dumps(
            [
                {
                    "point_id": spec.point_id,
                    "verdict": verdicts.get(spec.point_id, MISSING),
                    "text": spec.text,
                }
                for spec in specs
            ],
            ensure_ascii=False,
        )
        outcome.update(
            graded=True,
            verdict="pass" if graded.passed else "fail",
            reason=graded.reason or reason,
            score=round(float(graded.score), 4),
            point_results=point_results,
        )
        return outcome

    # 无要点（或模型未按要点返回）：退回整体二元判定
    outcome.update(
        graded=True,
        verdict="pass" if entry.get("verdict") == "pass" else "fail",
        reason=reason,
    )
    return outcome


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
        # ensure_question 可能刚固化了要点清单，这里以最新落库值为准
        context["points"] = question.get("points") or context.get("points")

        active.execute(
            "UPDATE plan_items SET answer_text = ? WHERE id = ?", (text, int(plan_id))
        )
        if own:
            active.commit()

        graded_result = _grade_answer(context, text)
        graded = graded_result["graded"]
        verdict = graded_result["verdict"]
        reason = graded_result["reason"]
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
                score=graded_result["score"],
                point_results=graded_result["point_results"],
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
        "score": graded_result["score"],
        "point_results": graded_result["point_results"],
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
