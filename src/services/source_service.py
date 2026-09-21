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
    origin_url: str | None = None,
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
        "origin_url": origin_url,
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
    replaced = False
    try:
        if not text:
            active.execute(
                "UPDATE sources SET parse_status = 'ok', checksum = NULL, parse_error = NULL "
                "WHERE id = ?",
                (source_id,),
            )
        else:
            replaced = bool(
                active.execute(
                    "SELECT 1 FROM source_chunks WHERE source_id = ? LIMIT 1", (source_id,)
                ).fetchone()
            )
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
    if replaced:
        # 切片被整体替换过 → 训练项里指向旧切片的回指已经悬空，必须清理（A4.1 / 审计 M3）
        _cleanup_links(source.training_id, conn=None if own else conn)
    return Source.from_row(row)


def _cleanup_links(training_id: int, *, conn: sqlite3.Connection | None = None) -> int:
    """清理训练项里悬空的来源切片回指，返回被清理的条数。

    局部导入 `path_service` 避免模块级循环依赖。
    """
    from src.services import path_service

    try:
        dropped = path_service.validate_item_chunk_links(int(training_id), conn=conn)
    except Exception:  # 清理失败不该让解析/刷新整体失败
        logger.exception("cleanup_links: failed for training %s", training_id)
        return 0
    if dropped:
        logger.info("cleanup_links: dropped %d stale chunk link(s) for training %s", dropped, training_id)
    return int(dropped or 0)


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


def set_source_enabled(
    source_id: int, enabled: bool, conn: sqlite3.Connection | None = None
) -> Source | None:
    """启用 / 停用某个来源。停用不等于删除（ADR 边界：企业版关掉 URL 来源，代码仍在）。"""
    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE sources SET enabled = ? WHERE id = ?", (1 if enabled else 0, source_id)
        )
        if own:
            active.commit()
        row = active.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    finally:
        if own:
            active.close()
    return Source.from_row(row) if row else None


def fetch_web_source(
    training_id: int,
    url: str,
    *,
    title: str | None = None,
    timeout: float | None = None,
    conn: sqlite3.Connection | None = None,
) -> Source:
    """抓取一个网页作为训练来源：保存正文快照 + 原始网址 + 抓取时间。

    失败时**先落一条来源记录再标状态**，让用户在列表里看得到失败原因（ADR-0008）。
    """
    from src.services.web_source import DEFAULT_TIMEOUT_S, WebSourceError, fetch_and_extract

    target = (url or "").strip()
    source = create_source(
        training_id,
        type="web_url",
        title=title or target or "网络来源",
        origin=target,
        origin_url=target,
        conn=conn,
    )
    try:
        page, text = fetch_and_extract(target, timeout=timeout or DEFAULT_TIMEOUT_S)
    except WebSourceError as exc:
        logger.warning("fetch_web_source: %s -> %s", target, exc)
        return mark_failed(source.id, str(exc), conn=conn) or source
    except Exception as exc:  # pragma: no cover - 兜底
        logger.exception("fetch_web_source: unexpected failure for %s", target)
        return mark_failed(source.id, f"抓取失败：{exc}", conn=conn) or source

    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE sources SET snapshot_text = ?, fetched_at = ?, checksum = ?, "
            "origin_url = ? WHERE id = ?",
            (text, page.fetched_at, content_checksum(text), page.final_url, source.id),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return parse_source(source.id, conn=conn)


def refresh_snapshot(
    source_id: int, *, timeout: float | None = None, conn: sqlite3.Connection | None = None
) -> Source:
    """按用户请求重新抓取网络来源的快照（不做定时重抓）。"""
    source = get_source(source_id, conn=conn)
    if source is None:
        raise ValueError(f"source not found: {source_id}")
    if source.type != "web_url" or not source.origin_url:
        raise ValueError("只有网络来源可以刷新快照")

    from src.services.web_source import DEFAULT_TIMEOUT_S, WebSourceError, fetch_and_extract

    try:
        page, text = fetch_and_extract(source.origin_url, timeout=timeout or DEFAULT_TIMEOUT_S)
    except WebSourceError as exc:
        return mark_failed(source_id, str(exc), conn=conn) or source

    active = _connect(conn)
    own = conn is None
    try:
        active.execute(
            "UPDATE sources SET snapshot_text = ?, fetched_at = ?, checksum = ? WHERE id = ?",
            (text, page.fetched_at, content_checksum(text), source_id),
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return parse_source(source_id, force=True, conn=conn)


def _items_referencing_chunks(chunk_ids: set[int], *, conn: sqlite3.Connection) -> int:
    """统计有多少训练项回指着给定的切片集合（影响面提示用）。"""
    if not chunk_ids:
        return 0
    rows = conn.execute(
        "SELECT source_chunk_ids FROM training_items WHERE source_chunk_ids IS NOT NULL"
    ).fetchall()
    affected = 0
    for row in rows:
        raw = row["source_chunk_ids"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue
        if not isinstance(raw, list):
            continue
        for value in raw:
            try:
                if int(value) in chunk_ids:
                    affected += 1
                    break
            except (TypeError, ValueError):
                continue
    return affected


def refresh_snapshot_report(
    source_id: int, *, timeout: float | None = None, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """刷新网页快照，并返回**影响面摘要**（新增/删除/修改 + 受影响的训练项数）。

    这是审计 M3 的修复：刷新会整体替换切片，旧 id 对应的训练项回指会悬空，
    因此必须在刷新后清理并告诉用户"哪些内容变了、动了多少条训练项的出处"。
    """
    source = get_source(source_id, conn=conn)
    if source is None:
        raise ValueError(f"source not found: {source_id}")
    if source.type != "web_url" or not source.origin_url:
        raise ValueError("只有网络来源可以刷新快照")

    old_ids = existing_chunk_ids(source_id, conn=conn)
    old_chunks = [
        Chunk(ordinal=row.ordinal, heading_path=row.heading_path or "（未分节）", text=row.text)
        for row in list_chunks(source_id, limit=10_000, conn=conn)
    ]
    active = _connect(conn)
    own = conn is None
    try:
        affected = _items_referencing_chunks(old_ids, conn=active)
    finally:
        if own:
            active.close()

    refreshed = refresh_snapshot(source_id, timeout=timeout, conn=conn)
    new_chunks = [
        Chunk(ordinal=row.ordinal, heading_path=row.heading_path or "（未分节）", text=row.text)
        for row in list_chunks(source_id, limit=10_000, conn=conn)
    ]
    impact = _core_compute_impact(old_chunks, new_chunks)
    return {
        "source": refreshed,
        "impact": impact,
        "chunk_count": len(new_chunks),
        "affected_items": affected,
    }


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
        WHERE s.training_id = ? AND s.enabled = 1 AND c.text LIKE ?
        ORDER BY c.ordinal LIMIT ?
    """
    try:
        if len(text) >= _FTS_MIN_QUERY_CHARS:
            rows = active.execute(
                """
                SELECT c.* FROM source_chunks_fts f
                JOIN source_chunks c ON c.id = f.rowid
                JOIN sources s ON s.id = c.source_id
                WHERE source_chunks_fts MATCH ? AND s.training_id = ? AND s.enabled = 1
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


def existing_chunk_ids_for_training(
    training_id: int, conn: sqlite3.Connection | None = None
) -> set[int]:
    """某训练下所有启用来源的切片 ID 集合，用于校验训练项回指是否还有效。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT c.id FROM source_chunks c JOIN sources s ON s.id = c.source_id "
            "WHERE s.training_id = ? AND s.enabled = 1",
            (training_id,),
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
    "existing_chunk_ids_for_training",
    "fetch_web_source",
    "get_chunks_by_ids",
    "get_source",
    "link_chunk_ids",
    "list_chunks",
    "list_sources",
    "mark_failed",
    "mark_unsupported",
    "parse_source",
    "refresh_snapshot",
    "refresh_snapshot_report",
    "search_chunks",
    "set_source_enabled",
]
