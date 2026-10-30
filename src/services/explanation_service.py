"""按需解析：用户请求时才生成，且必须引用资料来源。

对应 OpenSpec change ``learner-memory-and-grading`` 的任务 6.1—6.2。

要点：

* **按需**：不预生成，用户点开某题时才调用模型；
* **可溯源**：解析基于题目关联的资料切片，片段不足时如实说明"依据不足"，不编来源；
* **留痕**：解析文本与来源引用单独入库，便于回看与统计。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from src.db.sqlite import get_connection as _connect
from src.llm.client import complete
from src.services.grading_service import load_points

logger = logging.getLogger("src.services.explanation_service")

#: 最多引用几段资料
MAX_SOURCE_CHUNKS: int = 3


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_chunk_ids(raw: Any) -> list[str]:
    """``question_bank.source_chunk_ids`` 历史上可能是 JSON 数组或逗号分隔，宽松解析。"""
    if raw in (None, ""):
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    text = str(raw)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (TypeError, ValueError):
        pass
    return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]


def load_source_snippets(
    training_id: int,
    item_key: str,
    *,
    limit: int = MAX_SOURCE_CHUNKS,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """取该题关联的资料片段原文（用于解析溯源）。"""
    active = conn or _connect()
    own = conn is None
    try:
        row = active.execute(
            "SELECT source_chunk_ids FROM question_bank "
            "WHERE training_id = ? AND item_key = ?",
            (int(training_id), str(item_key)),
        ).fetchone()
        ids = _parse_chunk_ids(row["source_chunk_ids"] if row else None)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids[:limit])
        rows = active.execute(
            f"SELECT text FROM source_chunks WHERE id IN ({placeholders}) ORDER BY id",
            tuple(ids[:limit]),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [str(r["text"]) for r in rows]


def generate_explanation(
    training_id: int,
    item_key: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """按需生成解析。返回 ``{"ok": bool, ...}``，失败不抛异常（由调用方决定怎么提示）。"""
    active = conn or _connect()
    own = conn is None
    try:
        row = active.execute(
            "SELECT question_text, answer_text FROM question_bank "
            "WHERE training_id = ? AND item_key = ?",
            (int(training_id), str(item_key)),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "题目不存在"}
        specs = load_points(int(training_id), str(item_key), conn=active)
        snippets = load_source_snippets(training_id, item_key, conn=active)
        from src.services import attempt_service

        history = attempt_service.item_history(training_id, str(item_key), conn=active)
        variables = {
            "question": str(row["question_text"] or ""),
            "points": "；".join(spec.text for spec in specs) or "（无要点清单）",
            "answer": "",
            "attempt_history": _format_attempt_history(history),
            "source_text": "\n---\n".join(snippets) or "（没有可用的资料片段）",
        }
        try:
            result = complete("explanation", variables, training_id=int(training_id))
        except Exception as exc:  # 解析不可用不该影响主流程（失败审计由客户端写入）
            logger.warning("generate_explanation: LLM 不可用（%s）", exc)
            return {"ok": False, "error": str(exc)}

        output = result.get("output_json") or {}
        text = str(output.get("explanation") or "").strip()
        if not text:
            return {"ok": False, "error": "模型未返回解析内容"}
        refs = [str(item) for item in (output.get("source_refs") or [])]
        active.execute(
            "INSERT INTO explanations "
            "(training_id, item_key, explanation_text, source_refs, prompt_name, prompt_version, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(training_id),
                str(item_key),
                text,
                json.dumps(refs, ensure_ascii=False),
                result.get("prompt_name", "explanation"),
                result.get("prompt_version", "unknown"),
                result.get("model"),
                _now(),
            ),
        )
        if own:
            active.commit()
        return {"ok": True, "text": text, "source_refs": refs, "used_snippets": len(snippets)}
    finally:
        if own:
            active.close()


def _format_attempt_history(history: list[dict[str, object]]) -> str:
    """把作答历史渲染成 prompt 友好的文本；空历史返回明确占位。"""
    if not history:
        return "（无历史作答）"
    from src.services.memory_service import MISTAKE_REASON_LABELS

    lines: list[str] = []
    for idx, item in enumerate(history, start=1):
        verdict = "通过" if item.get("result") == "pass" else "未通过"
        score_part = f"，得分 {item['score']:.2f}" if isinstance(item.get("score"), (int, float)) else ""
        reasons: list[str] = []
        raw = str(item.get("mistake_reasons") or "")
        if raw:
            try:
                mapping = json.loads(raw)
                reasons = [MISTAKE_REASON_LABELS.get(v, str(v)) for v in mapping.values()]
            except ValueError:
                reasons = []
        reason_part = f"；错因：{'、'.join(reasons)}" if reasons else ""
        answer_text = str(item.get("answer_text") or "（无作答原文）")[:200]
        lines.append(
            f"第{idx}次（{item.get('created_at', '')[:16]}，第 {item.get('round_index') or '?'} 轮）"
            f"：{verdict}{score_part}{reason_part}。作答：{answer_text}"
        )
    return "\n".join(lines)


def generate_item_explanation(
    training_id: int,
    plan_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """题目级深度解析：对比该题历史作答，指出重复错误与改进动作（change: item-history-deep-explanation）。

    与 ``generate_explanation``（按 question_bank 讲知识点）不同，这里以 plan_items 为锚：
    题目/要点/参考答案取自计划项，作答历史取自 practice_attempts，切片回指 training_items。
    """
    from src.services import attempt_service

    active = conn or _connect()
    own = conn is None
    try:
        row = active.execute(
            "SELECT training_id, item_key, question, reference_answer, points "
            "FROM plan_items WHERE id = ?",
            (int(plan_id),),
        ).fetchone()
        if row is None or row["training_id"] is None:
            return {"ok": False, "error": "计划项不存在"}
        if int(row["training_id"]) != int(training_id):
            return {"ok": False, "error": "计划项不属于该训练"}
        item_key = str(row["item_key"] or "")
        question = str(row["question"] or "")
        if not question:
            return {"ok": False, "error": "该任务还没有题目，先出题再解析"}

        specs_text = "；".join(
            str(point.get("text"))
            for point in _parse_points_list(row["points"])
            if point.get("text")
        )
        history = attempt_service.item_history(training_id, item_key, conn=active)
        snippets = _load_snippets_for_item(active, training_id, item_key)

        variables = {
            "question": question,
            "points": specs_text or "（无要点清单）",
            "answer": str(row["reference_answer"] or ""),
            "attempt_history": _format_attempt_history(history),
            "source_text": "\n---\n".join(snippets) or "（没有可用的资料片段）",
        }
        try:
            result = complete("explanation", variables, training_id=int(training_id))
        except Exception as exc:  # 解析不可用不该影响主流程（失败审计由客户端写入）
            logger.warning("generate_item_explanation: LLM 不可用（%s）", exc)
            return {"ok": False, "error": str(exc)}

        output = result.get("output_json") or {}
        text = str(output.get("explanation") or "").strip()
        if not text:
            return {"ok": False, "error": "模型未返回解析内容"}
        refs = [str(item) for item in (output.get("source_refs") or [])]
        active.execute(
            "INSERT INTO explanations "
            "(training_id, item_key, explanation_text, source_refs, prompt_name, prompt_version, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(training_id),
                item_key,
                text,
                json.dumps(refs, ensure_ascii=False),
                result.get("prompt_name", "explanation"),
                result.get("prompt_version", "unknown"),
                result.get("model"),
                _now(),
            ),
        )
        if own:
            active.commit()
        return {
            "ok": True,
            "text": text,
            "source_refs": refs,
            "attempts_used": len(history),
            "prompt_version": result.get("prompt_version"),
        }
    finally:
        if own:
            active.close()


def _parse_points_list(raw: Any) -> list[dict[str, Any]]:
    """plan_items.points 的 JSON 数组解析；非法输入返回空表。"""
    if raw in (None, ""):
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def _load_snippets_for_item(
    active: sqlite3.Connection, training_id: int, item_key: str, *, limit: int = MAX_SOURCE_CHUNKS
) -> list[str]:
    """优先取 training_items.source_chunk_ids（日常链路），退回 question_bank（测验链路）。"""
    row = active.execute(
        "SELECT source_chunk_ids FROM training_items WHERE item_key = ? ORDER BY id DESC LIMIT 1",
        (item_key,),
    ).fetchone()
    ids = _parse_chunk_ids(row["source_chunk_ids"] if row else None)
    if not ids:
        row = active.execute(
            "SELECT source_chunk_ids FROM question_bank WHERE training_id = ? AND item_key = ?",
            (int(training_id), item_key),
        ).fetchone()
        ids = _parse_chunk_ids(row["source_chunk_ids"] if row else None)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids[:limit])
    rows = active.execute(
        f"SELECT text FROM source_chunks WHERE id IN ({placeholders}) ORDER BY id",
        tuple(ids[:limit]),
    ).fetchall()
    return [str(r["text"]) for r in rows]


def list_explanations(
    training_id: int, item_key: str, *, conn: sqlite3.Connection | None = None
) -> list[str]:
    active = conn or _connect()
    own = conn is None
    try:
        rows = active.execute(
            "SELECT explanation_text FROM explanations "
            "WHERE training_id = ? AND item_key = ? ORDER BY id",
            (int(training_id), str(item_key)),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [str(r["explanation_text"]) for r in rows]


__all__ = [
    "MAX_SOURCE_CHUNKS",
    "generate_explanation",
    "list_explanations",
    "load_source_snippets",
]
