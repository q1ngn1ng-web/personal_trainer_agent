"""主观题判分结果缓存（判分一致性治理 P0 之一，change ``grading-consistency``）。

模型对「题目 + 参考答案 + 要点清单 + 作答」的逐条四态判定视为确定值：

* 命中缓存直接复用模型输出，**不再调用模型**——同一作答重判永远同一结果，
  判分可复现，同时省 token 与延迟；
* 缓存的是**模型语义意见**（逐条四态），分数与达标仍由规则层实时计算——
  判分口径升级（规则层改动）不需要清缓存；
* 缓存键 = SHA256(model | prompt_version | question | reference_answer | points | answer)，
  要点清单或 prompt 版本变化即天然失效；
* 记忆上下文（【学习者背景】）**不进键**——口径约定它只帮理解措辞、不改判定，
  进键会让每次作答历史的增长都打散缓存。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from src.db.sqlite import get_connection as _connect

logger = logging.getLogger("src.services.grading_cache")

PROMPT_NAME: str = "quiz_grade"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cache_key(
    model: str | None,
    prompt_version: str | None,
    question: Any,
    reference_answer: Any,
    points_json: Any,
    answer: Any,
) -> str:
    """判分缓存的确定键；任一语义输入变化即得到不同键。"""
    payload = "\x1f".join(
        str(part or "")
        for part in (model, prompt_version, question, reference_answer, points_json, answer)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup(key: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """命中返回模型输出 JSON（结构同 complete() 的 ``output_json``），未命中/坏数据返回 None。"""
    active = conn or _connect()
    own = conn is None
    try:
        row = active.execute(
            "SELECT output_json FROM grading_cache WHERE cache_key = ?", (str(key),)
        ).fetchone()
    finally:
        if own:
            active.close()
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        logger.warning("grading_cache: corrupt entry %s ignored", str(key)[:12])
        return None
    return payload if isinstance(payload, dict) else None


def store(
    key: str,
    prompt_version: str,
    model: str,
    output_json: dict[str, Any],
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    conn: sqlite3.Connection | None = None,
) -> None:
    """写入判分结果；键冲突静默跳过（首次结果为准）。"""
    active = conn or _connect()
    own = conn is None
    try:
        active.execute(
            "INSERT INTO grading_cache "
            "(cache_key, prompt_name, prompt_version, model, output_json, "
            " tokens_in, tokens_out, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO NOTHING",
            (
                str(key),
                PROMPT_NAME,
                str(prompt_version),
                str(model),
                json.dumps(output_json, ensure_ascii=False),
                int(tokens_in),
                int(tokens_out),
                int(latency_ms),
                _now(),
            ),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


__all__ = ["PROMPT_NAME", "cache_key", "lookup", "store"]
