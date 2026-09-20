"""资料来源服务：登记、解析切片、全文检索、影响面、训练项回指校验。

对应 OpenSpec change ``training-source-selection`` 的阶段 A（静态层）。
阶段 A 不暴露 ``web_url``：建表时已备好字段与枚举，抓取逻辑留到阶段 B。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.core.source import (
    Chunk,
    ImpactReport,
    content_checksum,
    sanitize_chunk_ids,
    split_markdown,
    validate_source_type,
)
from src.core.source import compute_impact as _core_compute_impact
from src.db.models import Source, SourceChunk
from src.db.sqlite import get_connection

logger = logging.getLogger("src.services.source_service")

#: 阶段 A 可用的来源类型（web_url 留到阶段 B）
STATIC_SOURCE_TYPES: tuple[str, ...] = ("ai_generated", "user_upload", "user_paste")

#: 默认组织（个人版只有一个组织；企业化由后续 change 接管）
DEFAULT_ORG_ID: int = 1

#: trigram 分词要求查询至少 3 个字符，短查询退化为 LIKE
_FTS_MIN_QUERY_CHARS: int = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def create_source(
    training_id: int,
    *,
    type: str,
    title: str,
    origin: str | None = None,
    content: str | None = None,
    scope: str = "personal",
    conn: sqlite3.Connection | None = None,
) -> Source:
    """登记一条资料来源。``content`` 给出时直接落库并计算校验值。"""
    validate_source_type(type)
    text = (content or "").strip()
    payload = {
        "training_id": training_id,
        "type": type,
        "title": (title or "").strip() or "未命名来源",
        "origin": origin,
        "snapshot_text": text or None,
        "org_id": DEFAULT_ORG_ID,
        "scope": scope,
        "checksum": content_checksum(text) if text else None,
        "parse_status": "pending",
        "imported_at": _now(),
    }
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    active = _connect(conn)
    own = conn is None
    try:
        cursor = active.execute(
            f"INSERT INTO sources ({columns}) VALUES ({placeholders})",
            list(payload.values()),
        )
        row = active.execute("SELECT * FROM sources WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return Source.from_row(row)


def get_source(source_id: int, conn: sqlite3.Connection | None = None) -> Source | None:
    """按 id 取来源。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    finally:
        if own:
            active.close()
    return Source.from_row(row) if row else None


def list_sources(training_id: int, conn: sqlite3.Connection | None = None) -> list[Source]:
    """列出某个训练的全部来源。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM sources WHERE training_id = ? ORDER BY id", (training_id,)
        ).fetchall()
    finally:
        if own:
            active.close()
    return [Source.from_row(row) for row in rows]


def list_chunks(
    source_id: int, *, limit: int = 200, conn: sqlite3.Connection | None = None
) -> list[SourceChunk]:
    """按顺序列出某来源的切片。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM source_chunks WHERE source_id = ? ORDER BY ordinal LIMIT ?",
            (source_id, limit),
        ).fetchall()
    finally:
        if own:
            active.close()
    return [SourceChunk.from_row(row) for row in rows]


def _store_chunks(active: sqlite3.Connection, source_id: int, chunks: list[Chunk]) -> None:
    """替换某来源的全部切片（触发器会同步 FTS 索引）。"""
    active.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
    active.executemany(
        "INSERT INTO source_chunks (source_id, ordinal, heading_path, text, char_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (source_id, chunk.ordinal, chunk.heading_path, chunk.text, chunk.char_count)
            for chunk in chunks
        ],
    )


def parse_source(
    source_id: int, *, force: bool = False, conn: sqlite3.Connection | None = None
) -> Source:
    """解析来源并切片入索引。幂等：内容未变且上次成功时直接复用。"""
    source = get_source(source_id, conn=conn)
    if source is None:
        raise ValueError(f"source not found: {source_id}")

    text = (source.snapshot_text or "").strip()
    current_checksum = content_checksum(text) if text else None

    if not force and source.parse_status == "ok" and source.checksum == current_checksum:
        logger.info("parse_source: source %s unchanged, skipping", source_id)
        return source

    active = _connect(conn)
    own = conn is None
    try:
        if not text:
            active.execute(
                "UPDATE sources SET parse_status = 'ok', checksum = NULL, parse_error = NULL "
                "WHERE id = ?",
                (source_id,),
            )
        else:
            _store_chunks(active, source_id, split_markdown(text))
            active.execute(
                "UPDATE sources SET parse_status = 'ok', checksum = ?, parse_error = NULL "
                "WHERE id = ?",
                (current_checksum, source_id),
            )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    except Exception as exc:  # 解析失败不阻塞其他来源
        logger.exception("parse_source: source %s failed", source_id)
        if own:
            active.rollback()
        active.execute(
            "UPDATE sources SET parse_status = 'failed', parse_error = ? WHERE id = ?",
            (str(exc), source_id),
        )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    finally:
        if own:
            active.close()
    return Source.from_row(row)


def mark_failed(
    source_id: int, reason: str, conn: sqlite3.Connection | None = None
) -> Source | None:
    """把来源显式标为解析失败（损坏文件等场景）。"""
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE sources SET parse_status = 'failed', parse_error = ? WHERE id = ?",
            (reason, source_id),
        )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    finally:
        if own:
            active.close()
    return Source.from_row(row) if row else None


def mark_unsupported(
    source_id: int, reason: str, conn: sqlite3.Connection | None = None
) -> Source | None:
    """把来源标为「格式暂不支持」，与解析失败区分开。"""
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE sources SET parse_status = 'unsupported', parse_error = ? WHERE id = ?",
            (reason, source_id),
        )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    finally:
        if own:
            active.close()
    return Source.from_row(row) if row else None


def create_source_from_file(
    training_id: int,
    *,
    filename: str,
    data: bytes,
    scope: str = "personal",
    conn: sqlite3.Connection | None = None,
) -> Source:
    """从上传文件的字节登记来源。

    先把文件解析成 Markdown（PDF / Word / Excel / 文本），再走与粘贴文本
    完全相同的切片流程。失败时**显式落状态**，不静默吞掉。
    """
    from src.services.doc_parser import UnsupportedFormatError, parse_file

    try:
        text = parse_file(filename, data)
    except UnsupportedFormatError as exc:
        source = create_source(
            training_id, type="user_upload", title=filename, origin=filename, conn=conn
        )
        logger.warning("create_source_from_file: unsupported %s (%s)", filename, exc)
        return mark_unsupported(source.id, str(exc), conn=conn) or source
    except Exception as exc:
        source = create_source(
            training_id, type="user_upload", title=filename, origin=filename, conn=conn
        )
        logger.exception("create_source_from_file: failed to parse %s", filename)
        return mark_failed(source.id, f"文件解析失败：{exc}", conn=conn) or source

    source = create_source(
        training_id,
        type="user_upload",
        title=filename,
        origin=filename,
        content=text,
        scope=scope,
        conn=conn,
    )
    return parse_source(source.id, conn=conn)


def get_chunks_by_ids(
    chunk_ids: list[int], conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """按切片 ID 取原文与标题路径，供「查看出处」使用。"""
    ids = [int(value) for value in (chunk_ids or [])]
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            f"""
            SELECT c.id, c.text, c.heading_path, c.ordinal,
                   s.id AS source_id, s.title AS source_title, s.type AS source_type
            FROM source_chunks c
            JOIN sources s ON s.id = c.source_id
            WHERE c.id IN ({placeholders})
            ORDER BY c.id
            """,
            ids,
        ).fetchall()
    finally:
        if own:
            active.close()
    return [dict(row) for row in rows]


def search_chunks(
    training_id: int, query: str, *, limit: int = 10, conn: sqlite3.Connection | None = None
) -> list[SourceChunk]:
    """在某个训练的资料来源里做全文检索。**不产生任何 LLM 调用。**"""
    text = (query or "").strip()
    if not text:
        return []
    active = _connect(conn)
    own = conn is None
    like_sql = """
        SELECT c.* FROM source_chunks c
        JOIN sources s ON s.id = c.source_id
        WHERE s.training_id = ? AND c.text LIKE ?
        ORDER BY c.ordinal LIMIT ?
    """
    try:
        if len(text) >= _FTS_MIN_QUERY_CHARS:
            rows = active.execute(
                """
                SELECT c.* FROM source_chunks_fts f
                JOIN source_chunks c ON c.id = f.rowid
                JOIN sources s ON s.id = c.source_id
                WHERE source_chunks_fts MATCH ? AND s.training_id = ?
                ORDER BY bm25(source_chunks_fts) LIMIT ?
                """,
                (text, training_id, limit),
            ).fetchall()
        else:
            rows = active.execute(like_sql, (training_id, f"%{text}%", limit)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("search_chunks: FTS failed (%s), falling back to LIKE", exc)
        rows = active.execute(like_sql, (training_id, f"%{text}%", limit)).fetchall()
    finally:
        if own:
            active.close()
    return [SourceChunk.from_row(row) for row in rows]


def compute_impact(
    source_id: int, new_content: str | None = None, conn: sqlite3.Connection | None = None
) -> ImpactReport:
    """比较来源已有切片与「新内容」的差异，给出新增 / 删除 / 修改清单。

    ``new_content`` 省略时以当前快照为准（内容未变则返回空清单）。
    只给清单，**不删除任何训练项**。
    """
    source = get_source(source_id, conn=conn)
    if source is None:
        raise ValueError(f"source not found: {source_id}")

    incoming = (source.snapshot_text or "") if new_content is None else new_content
    if new_content is not None and content_checksum(incoming.strip()) == source.checksum:
        return ImpactReport()

    existing = list_chunks(source_id, limit=10_000, conn=conn)
    old_chunks = [
        Chunk(ordinal=row.ordinal, heading_path=row.heading_path or "（未分节）", text=row.text)
        for row in existing
    ]
    fresh = split_markdown(incoming.strip())
    return _core_compute_impact(old_chunks, fresh)


def existing_chunk_ids(source_id: int, conn: sqlite3.Connection | None = None) -> set[int]:
    """某来源下真实存在的切片 ID 集合，用于训练项回指校验。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT id FROM source_chunks WHERE source_id = ?", (source_id,)
        ).fetchall()
    finally:
        if own:
            active.close()
    return {int(row["id"]) for row in rows}


def link_chunk_ids(
    raw_ids: Any, source_id: int, conn: sqlite3.Connection | None = None
) -> tuple[list[int], list[int]]:
    """训练项回指校验：不存在的切片 ID 被丢弃并记日志。"""
    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except json.JSONDecodeError:
            raw_ids = []
    existing = existing_chunk_ids(source_id, conn=conn)
    valid, dropped = sanitize_chunk_ids(raw_ids or [], existing)
    if dropped:
        logger.warning("link_chunk_ids: dropped non-existent chunk ids %s", dropped)
    return valid, dropped


__all__ = [
    "DEFAULT_ORG_ID",
    "STATIC_SOURCE_TYPES",
    "compute_impact",
    "create_source",
    "create_source_from_file",
    "existing_chunk_ids",
    "get_chunks_by_ids",
    "get_source",
    "link_chunk_ids",
    "list_chunks",
    "list_sources",
    "mark_failed",
    "mark_unsupported",
    "parse_source",
    "search_chunks",
]
