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
        variables = {
            "question": str(row["question_text"] or ""),
            "points": "；".join(spec.text for spec in specs) or "（无要点清单）",
            "answer": "",
            "source_text": "\n---\n".join(snippets) or "（没有可用的资料片段）",
        }
        try:
            result = complete("explanation", variables, schema=None)
        except Exception as exc:  # 解析不可用不该影响主流程
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
                "explanation",
                "v1.0.0",
                None,
                _now(),
            ),
        )
        if own:
            active.commit()
        return {"ok": True, "text": text, "source_refs": refs, "used_snippets": len(snippets)}
    finally:
        if own:
            active.close()


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
