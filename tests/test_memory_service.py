"""学习者记忆的测试（change learner-memory-and-grading 任务 4.1—4.8）。"""
from __future__ import annotations

import json

import pytest

from src.db.sqlite import get_connection, init_db
from src.services import memory_service as ms


def _db(tmp_path):
    db = tmp_path / "m.db"
    init_db(str(db))
    conn = get_connection(str(db))
    conn.execute(
        "INSERT INTO trainings (id, topic, status, created_at) "
        "VALUES (1, 'Redis', 'active', '2026-10-01T00:00:00')"
    )
    conn.commit()
    return conn


def _bank(conn, item_key: str, kp: str, qtype: str = "qa") -> None:
    conn.execute(
        "INSERT INTO question_bank (training_id, item_key, knowledge_point, question_type, banked_at) "
        "VALUES (1, ?, ?, ?, '2026-10-01T00:00:00')",
        (item_key, kp, qtype),
    )
    conn.commit()


def _attempt(conn, item_key: str, result: str, score: float, reasons: dict | None = None, day: str = "02"):
    conn.execute(
        "INSERT INTO practice_attempts "
        "(training_id, item_key, result, score, mistake_reasons, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (
            item_key,
            result,
            score,
            json.dumps(reasons) if reasons else None,
            f"2026-10-{day}T10:00:00",
        ),
    )
    conn.commit()


# ------------------------------------------------------------ 错因推导（4.5）


def test_derive_mistake_reasons_from_point_verdicts() -> None:
    payload = {
        "detail": [
            {"point_id": "p1", "verdict": "missing", "required": True},
            {"point_id": "p2", "verdict": "missing", "required": False},
            {"point_id": "p3", "verdict": "wrong", "required": False},
            {"point_id": "p4", "verdict": "partial", "required": False},
            {"point_id": "p5", "verdict": "hit", "required": False},
        ]
    }

    reasons = ms.derive_mistake_reasons(payload)

    assert reasons == {
        "p1": ms.KEY_OMISSION,
        "p2": ms.MEMORY_GAP,
        "p3": ms.CONCEPT_CONFUSION,
        "p4": ms.INCOMPLETE_EXPRESSION,
    }


def test_derive_mistake_reasons_is_empty_without_data() -> None:
    assert ms.derive_mistake_reasons(None) == {}
    assert ms.derive_mistake_reasons({}) == {}


def test_record_mistake_reasons_writes_back(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.3)
        attempt_id = conn.execute("SELECT id FROM practice_attempts").fetchone()["id"]

        ms.record_mistake_reasons(attempt_id, {"p1": ms.MEMORY_GAP}, conn=conn)

        row = conn.execute(
            "SELECT mistake_reasons FROM practice_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
    finally:
        conn.close()

    assert json.loads(row["mistake_reasons"]) == {"p1": ms.MEMORY_GAP}


# ------------------------------------------------------------ 画像与聚合（4.2 / 4.8）


def test_knowledge_profile_aggregates_and_flags_weak(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _bank(conn, "k2", "主从复制")
        _attempt(conn, "k1", "fail", 0.4, day="02")
        _attempt(conn, "k1", "fail", 0.5, day="03")
        _attempt(conn, "k2", "pass", 1.0, day="03")

        profile = {stat.knowledge_point: stat for stat in ms.knowledge_profile(1, conn=conn)}
    finally:
        conn.close()

    assert profile["持久化"].attempts == 2
    assert profile["持久化"].is_weak is True
    assert profile["主从复制"].is_weak is False


def test_mistake_reason_counts_aggregate(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.3, {"p1": ms.CONCEPT_CONFUSION}, day="02")
        _attempt(conn, "k1", "fail", 0.4, {"p1": ms.CONCEPT_CONFUSION}, day="03")
        _attempt(conn, "k1", "fail", 0.2, {"p1": ms.MEMORY_GAP}, day="04")

        counts = ms.mistake_reason_counts(1, conn=conn)
    finally:
        conn.close()

    assert counts[ms.CONCEPT_CONFUSION] == 2
    assert counts[ms.MEMORY_GAP] == 1


def test_recent_mistake_notes_are_readable(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.3, {"p1": ms.CONCEPT_CONFUSION}, day="12")

        notes = ms.recent_mistake_notes(1, conn=conn)
    finally:
        conn.close()

    assert notes and "概念混淆" in notes[0] and "持久化" in notes[0]


# ------------------------------------------------------------ 上下文渲染（4.1 / 4.4 / 4.7）


def test_render_context_has_four_sections_and_reports_ratio(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.3, {"p1": ms.CONCEPT_CONFUSION}, day="12")
        conn.execute(
            "INSERT INTO assessments (id, training_id, status, question_count, created_at) "
            "VALUES (1, 1, 'completed', 1, '2026-10-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO assessment_items "
            "(assessment_id, ordinal, item_key, question, user_answer, created_at) "
            "VALUES (1, 1, 'k1', '问', ?, '2026-10-01T00:00:00')",
            ("这是一段很长的原始作答" * 20,),
        )
        conn.commit()

        ctx = ms.render_context(1, current_item_key="k1", conn=conn)
    finally:
        conn.close()

    assert "【薄弱知识点】" in ctx.text
    assert "【错因分布】" in ctx.text
    assert "【最近错因】" in ctx.text
    assert "【当前题背景】" in ctx.text
    assert ctx.approx_tokens < ctx.naive_tokens
    assert 0 < ctx.compression_ratio < 1


# ------------------------------------------------------------ 开关与分析（4.6）


def test_mistake_analysis_defaults_to_off(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        assert ms.is_mistake_analysis_enabled(conn=conn) is False
        ms.set_mistake_analysis_enabled(True, conn=conn)
        assert ms.is_mistake_analysis_enabled(conn=conn) is True
        ms.set_mistake_analysis_enabled(False, conn=conn)
        assert ms.is_mistake_analysis_enabled(conn=conn) is False
    finally:
        conn.close()


def test_mistake_analysis_is_stored_separately(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.3, {"p1": ms.MEMORY_GAP})

        ms.save_mistake_analysis(1, "k1", "你把 RDB 和 AOF 记反了", conn=conn)
        texts = ms.list_mistake_analysis(1, "k1", conn=conn)
        reasons = conn.execute(
            "SELECT mistake_reasons FROM practice_attempts"
        ).fetchone()
    finally:
        conn.close()

    assert texts == ["你把 RDB 和 AOF 记反了"]
    # 分析文本不覆盖规则错因
    assert json.loads(reasons["mistake_reasons"]) == {"p1": ms.MEMORY_GAP}


# -------------------------------------------------- 判分记忆块（任务 4.3 判分侧）


def test_grade_memory_block_defaults_on_and_renders(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.5, {"p1": ms.MEMORY_GAP})

        block = ms.grade_memory_block(1, "k1", conn=conn)
    finally:
        conn.close()

    assert block.startswith("\n\n【学习者背景】\n")
    assert "记忆缺失" in block
    assert "当前题背景" in block


def test_grade_memory_block_empty_without_attempts(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        assert ms.grade_memory_block(1, None, conn=conn) == ""
        assert ms.grade_memory_block(None, conn=conn) == ""
    finally:
        conn.close()


def test_grade_memory_block_can_be_disabled(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        _bank(conn, "k1", "持久化")
        _attempt(conn, "k1", "fail", 0.5, {"p1": ms.MEMORY_GAP})

        # 缺省（app_settings 无记录）= 开启
        assert ms.is_memory_context_enabled(conn=conn) is True
        ms.set_memory_context_enabled(False, conn=conn)
        assert ms.is_memory_context_enabled(conn=conn) is False
        assert ms.grade_memory_block(1, "k1", conn=conn) == ""
        ms.set_memory_context_enabled(True, conn=conn)
        assert "【学习者背景】" in ms.grade_memory_block(1, "k1", conn=conn)
    finally:
        conn.close()


def test_grade_memory_block_survives_render_failure(tmp_path, monkeypatch) -> None:
    conn = _db(tmp_path)
    try:
        _attempt(conn, "k1", "fail", 0.5, {"p1": ms.MEMORY_GAP})

        def _boom(*args, **kwargs):
            raise RuntimeError("render exploded")

        monkeypatch.setattr(ms, "render_context", _boom)
        assert ms.grade_memory_block(1, "k1", conn=conn) == ""
    finally:
        conn.close()
