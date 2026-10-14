"""判分服务与判分相关迁移的测试（change learner-memory-and-grading）。

覆盖：要点评分（覆盖率 x 正确性、必答一票否决）、题型分流（选择/填空确定性判分）、
以及数据层迁移（补列、建 question_points、可重复执行）。
"""
from __future__ import annotations

import sqlite3

import pytest

from src.db.migrate import migrate
from src.db.sqlite import get_connection, init_db
from src.services.grading_service import (
    DEFAULT_PASS_THRESHOLD,
    HIT,
    MISSING,
    PARTIAL,
    WRONG,
    PointSpec,
    grade_choice,
    grade_fill,
    grade_question,
    overall_score,
    score_points,
)


def _three_points() -> list[PointSpec]:
    return [
        PointSpec("p1", "Redis 单线程处理命令", weight=1, required=False),
        PointSpec("p2", "单线程避免锁竞争", weight=1, required=False),
        PointSpec("p3", "6.0 引入多线程 IO", weight=1, required=False),
    ]


def test_coverage_two_of_three() -> None:
    result = score_points(_three_points(), {"p1": HIT, "p2": HIT, "p3": MISSING})

    assert result.coverage == pytest.approx(2 / 3)
    assert result.score == pytest.approx(2 / 3)
    assert result.missing == ("p3",)


def test_wrong_answer_worse_than_missing() -> None:
    """答满但说反一条，应当低于只答对两条。"""
    all_covered_one_wrong = score_points(
        _three_points(), {"p1": HIT, "p2": HIT, "p3": WRONG}
    )
    two_correct = score_points(_three_points(), {"p1": HIT, "p2": HIT, "p3": MISSING})

    assert all_covered_one_wrong.incorrect == ("p3",)
    assert all_covered_one_wrong.score < two_correct.score


def test_required_missing_vetoes_pass() -> None:
    points = [
        PointSpec("p1", "核心结论", weight=3, required=True),
        PointSpec("p2", "补充说明", weight=1, required=False),
    ]

    result = grade_question(
        "qa", answer="...", points=points, point_verdicts={"p1": MISSING, "p2": HIT}
    )

    assert result.passed is False
    assert result.required_missing == ("p1",)
    assert "必答" in result.reason


def test_partial_counts_half() -> None:
    result = score_points(_three_points(), {"p1": HIT, "p2": PARTIAL})

    assert result.coverage == pytest.approx(1.5 / 3)


def test_qa_without_points_is_rejected() -> None:
    """主观题没有要点清单时拒绝判分，不允许模型自由发挥。"""
    with pytest.raises(ValueError):
        grade_question("qa", answer="随便答", points=[], point_verdicts={})


def test_unknown_verdict_is_rejected() -> None:
    with pytest.raises(ValueError):
        score_points(_three_points(), {"p1": "maybe"})


def test_pass_threshold_is_eight_tenths() -> None:
    """2026-10-15 用户决策：达标阈值 0.8。"""
    assert DEFAULT_PASS_THRESHOLD == pytest.approx(0.8)

    points = [PointSpec(f"p{i}", "要点", weight=1) for i in range(1, 6)]
    exactly_08 = grade_question(
        "qa",
        answer="...",
        points=points,
        point_verdicts={f"p{i}": HIT for i in range(1, 5)} | {"p5": MISSING},
    )
    below = grade_question(
        "qa",
        answer="...",
        points=points,
        point_verdicts={f"p{i}": HIT for i in range(1, 4)} | {"p4": MISSING, "p5": MISSING},
    )

    assert exactly_08.score == pytest.approx(0.8)
    assert exactly_08.passed is True
    assert below.passed is False


def test_overall_score_uses_type_weights() -> None:
    """整场评分：客观题权重 0.4、主观题 0.6（2026-10-15 用户决策）。"""
    choice = grade_question("choice", answer="A", expected_answer="A")
    qa_wrong = grade_question(
        "qa", answer="...", points=[PointSpec("p1", "要点")], point_verdicts={"p1": WRONG}
    )

    assert overall_score([choice, qa_wrong]) == pytest.approx(0.4)
    assert overall_score([choice]) == pytest.approx(1.0)
    assert overall_score([qa_wrong]) == pytest.approx(0.0)
    assert overall_score([]) is None


def test_choice_grading_uses_rules_only() -> None:
    ok = grade_question("choice", answer="B", expected_answer="B")
    bad = grade_question("choice", answer="A", expected_answer="B")

    assert ok.passed is True and ok.graded_by == "rule"
    assert bad.passed is False and bad.graded_by == "rule"


def test_choice_accepts_option_text() -> None:
    options = [
        {"key": "A", "text": "先断开电源"},
        {"key": "B", "text": "直接清洁喷头"},
    ]

    result = grade_choice("先断开电源", correct_key="A", options=options)

    assert result[0] == HIT


def test_fill_normalizes_before_compare() -> None:
    assert grade_fill(" RDB 和 AOF ", expected="rdb和aof")[0] == HIT
    assert grade_fill("AOF", expected="RDB")[0] == WRONG
    assert grade_fill("", expected="RDB")[0] == WRONG


def test_objective_grading_does_not_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """客观题判分不得触碰 LLM 客户端（硬约束第 4 条）。"""
    import src.llm.client as llm_client

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("客观题判分不应调用大模型")

    monkeypatch.setattr(llm_client, "complete", _boom)

    assert grade_question("choice", answer="A", expected_answer="A").passed is True
    assert grade_question("fill", answer="RDB", expected_answer="RDB").passed is True


def test_init_db_has_grading_schema(tmp_path) -> None:
    db = tmp_path / "trainer.db"
    init_db(str(db))

    conn = get_connection(str(db))
    try:
        bank = {row[1] for row in conn.execute("PRAGMA table_info(question_bank)")}
        attempts = {row[1] for row in conn.execute("PRAGMA table_info(practice_attempts)")}
        items = {row[1] for row in conn.execute("PRAGMA table_info(assessment_items)")}
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    assert {"question_type", "options"} <= bank
    assert {"score", "point_results"} <= attempts
    assert "question_type" in items
    assert "question_points" in tables


def test_migrate_adds_grading_columns_to_old_db(tmp_path) -> None:
    """模拟老库：只有旧列，迁移后补齐新列并建 question_points，且可重复执行。"""
    db = tmp_path / "old.db"
    raw = sqlite3.connect(db)
    raw.executescript(
        """
        CREATE TABLE trainings (id INTEGER PRIMARY KEY, topic TEXT NOT NULL);
        CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY, training_id INTEGER, item_key TEXT,
            item_type TEXT, question_text TEXT, answer_text TEXT
        );
        CREATE TABLE practice_attempts (
            id INTEGER PRIMARY KEY, training_id INTEGER, item_key TEXT, result TEXT
        );
        CREATE TABLE assessment_items (
            id INTEGER PRIMARY KEY, assessment_id INTEGER, question TEXT
        );
        """
    )
    raw.commit()
    raw.close()

    conn = get_connection(str(db))

    applied = migrate(conn)

    bank = {row[1] for row in conn.execute("PRAGMA table_info(question_bank)")}
    attempts = {row[1] for row in conn.execute("PRAGMA table_info(practice_attempts)")}
    items = {row[1] for row in conn.execute("PRAGMA table_info(assessment_items)")}
    again = migrate(conn)
    conn.close()

    assert {"question_type", "options"} <= bank
    assert {"score", "point_results"} <= attempts
    assert "question_type" in items
    assert any(name.startswith("question_bank") for name in applied)
    assert again == []
