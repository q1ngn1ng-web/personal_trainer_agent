"""阶段 5—7 的测试：整场加权评分、按需解析、自适应题型配比。"""
from __future__ import annotations

import json

import pytest

from src.db.sqlite import get_connection, init_db
from src.services import explanation_service as ex
from src.services import memory_service as ms
from src.services.grading_service import pair_weighted_score


def _db(tmp_path):
    db = tmp_path / "f.db"
    init_db(str(db))
    conn = get_connection(str(db))
    conn.execute(
        "INSERT INTO trainings (id, topic, status, created_at) "
        "VALUES (1, 'Redis', 'active', '2026-10-01T00:00:00')"
    )
    conn.commit()
    return conn


# ------------------------------------------------------------ 整场评分（阶段 5）


def test_pair_weighted_score_weights_objective_less() -> None:
    """客观题权重 0.4、主观题 0.6：客观满分 + 主观零分 → 0.4。"""
    assert pair_weighted_score([("choice", 1.0), ("qa", 0.0)]) == pytest.approx(0.4)
    assert pair_weighted_score([("fill", 1.0), ("qa", 1.0)]) == pytest.approx(1.0)


def test_pair_weighted_score_skips_missing_scores() -> None:
    """没有分数的历史题不参与聚合；全为 None 时返回 None（不伪造分数）。"""
    assert pair_weighted_score([("qa", None), ("qa", 0.5)]) == pytest.approx(0.5)
    assert pair_weighted_score([("qa", None)]) is None
    assert pair_weighted_score([]) is None


# ------------------------------------------------------------ 自适应配比（阶段 7）


def test_recommended_type_mix_favours_weak_type(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        for key, qtype in (("c1", "choice"), ("q1", "qa")):
            conn.execute(
                "INSERT INTO question_bank (training_id, item_key, knowledge_point, question_type, banked_at) "
                "VALUES (1, ?, 'kp', ?, '2026-10-01T00:00:00')",
                (key, qtype),
            )
        # 选择题很弱、问答题很强
        for day in ("02", "03"):
            conn.execute(
                "INSERT INTO practice_attempts (training_id, item_key, result, score, created_at) "
                "VALUES (1, 'c1', 'fail', 0.2, ?)",
                (f"2026-10-{day}T10:00:00",),
            )
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, result, score, created_at) "
            "VALUES (1, 'q1', 'pass', 1.0, '2026-10-03T10:00:00')"
        )
        conn.commit()

        mix = ms.recommended_type_mix(1, conn=conn)
    finally:
        conn.close()

    assert mix["choice"] == pytest.approx(1.0)
    assert "qa" not in mix  # 表现好的题型不加压


def test_recommended_type_mix_is_empty_without_data(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        assert ms.recommended_type_mix(1, conn=conn) == {}
    finally:
        conn.close()


# ------------------------------------------------------------ 按需解析（阶段 6）


def test_explanation_refuses_when_question_missing(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        result = ex.generate_explanation(1, "nope", conn=conn)
    finally:
        conn.close()

    assert result["ok"] is False


def test_generate_explanation_uses_sources_and_persists(tmp_path, monkeypatch) -> None:
    conn = _db(tmp_path)
    calls: list[dict] = []

    def _fake_complete(purpose, variables, schema=None):
        calls.append({"purpose": purpose, "variables": variables})
        return {"output_json": {"explanation": "正确答案是 RDB", "source_refs": ["chunk-1"]}}

    monkeypatch.setattr(ex, "complete", _fake_complete)
    try:
        conn.execute(
            "INSERT INTO sources (id, training_id, type, title, imported_at) "
            "VALUES (1, 1, 'user_upload', '手册', '2026-10-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO source_chunks (id, source_id, ordinal, text, char_count) "
            "VALUES (1, 1, 1, 'RDB 是快照持久化', 12)"
        )
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, knowledge_point, question_type, question_text, source_chunk_ids, banked_at) "
            "VALUES (1, 'k1', '持久化', 'qa', 'RDB 是什么', '[1]', '2026-10-01T00:00:00')"
        )
        conn.commit()

        result = ex.generate_explanation(1, "k1", conn=conn)
        stored = ex.list_explanations(1, "k1", conn=conn)
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["used_snippets"] == 1
    assert "RDB 是快照持久化" in calls[0]["variables"]["source_text"]
    assert stored == ["正确答案是 RDB"]


def test_load_source_snippets_parses_legacy_formats(tmp_path) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO sources (id, training_id, type, title, imported_at) "
            "VALUES (1, 1, 'user_upload', '手册', '2026-10-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO source_chunks (id, source_id, ordinal, text, char_count) "
            "VALUES (7, 1, 1, '片段七', 3)"
        )
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, question_text, source_chunk_ids, banked_at) "
            "VALUES (1, 'k9', '问', '7', '2026-10-01T00:00:00')"
        )
        conn.commit()

        snippets = ex.load_source_snippets(1, "k9", conn=conn)
    finally:
        conn.close()

    assert snippets == ["片段七"]


def test_mistake_analysis_save_is_json_safe(tmp_path) -> None:
    """错因 JSON 与解析文本互不干扰（阶段 4 与 6 的边界）。"""
    conn = _db(tmp_path)
    try:
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, banked_at) "
            "VALUES (1, 'k1', '2026-10-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, result, score, mistake_reasons, created_at) "
            "VALUES (1, 'k1', 'fail', 0.3, ?, '2026-10-02T10:00:00')",
            (json.dumps({"p1": ms.MEMORY_GAP}),),
        )
        conn.commit()

        ms.save_mistake_analysis(1, "k1", "分析文本", conn=conn)
        counts = ms.mistake_reason_counts(1, conn=conn)
    finally:
        conn.close()

    assert counts[ms.MEMORY_GAP] == 1
