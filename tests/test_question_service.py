"""出题校验与要点落库的测试（change learner-memory-and-grading 任务 3.1—3.3）。"""
from __future__ import annotations

import pytest

from src.db.sqlite import get_connection, init_db
from src.services.grading_service import HIT, grade_question, load_points
from src.services.question_service import (
    save_generated_question,
    save_question_points,
    validate_generated_question,
)

SOURCE = "Redis 单线程处理命令，因此避免了锁竞争；6.0 起引入多线程 IO 处理网络读写。"


def _points(count: int = 3) -> list[dict[str, object]]:
    return [
        {"point_id": f"p{i}", "text": f"要点{i}", "weight": 1, "is_required": i == 1}
        for i in range(1, count + 1)
    ]


def _choice_payload(*, options: list[dict[str, object]]) -> dict[str, object]:
    return {
        "question": "Redis 为什么没有锁竞争？",
        "reference_answer": "单线程处理命令",
        "difficulty": 2,
        "question_type": "choice",
        "options": options,
        "points": _points(1),
    }


def test_qa_requires_at_least_three_points() -> None:
    payload = {"question_type": "qa", "points": _points(2)}

    problems = validate_generated_question(payload)

    assert any("至少需要 3 条要点" in item for item in problems)


def test_choice_requires_exactly_one_correct_option() -> None:
    bad = _choice_payload(
        options=[
            {"key": "A", "text": "单线程处理命令", "is_correct": True},
            {"key": "B", "text": "避免了锁竞争", "is_correct": True},
            {"key": "C", "text": "6.0 起引入多线程 IO", "is_correct": False},
        ]
    )

    problems = validate_generated_question(bad, source_text=SOURCE)

    assert any("有且仅有一个正确项" in item for item in problems)


def test_choice_distractor_must_be_grounded_in_source() -> None:
    payload = _choice_payload(
        options=[
            {"key": "A", "text": "单线程处理命令", "is_correct": True},
            {"key": "B", "text": "避免了锁竞争", "is_correct": False},
            {"key": "C", "text": "使用了分布式事务两阶段提交", "is_correct": False},
        ]
    )

    problems = validate_generated_question(payload, source_text=SOURCE)

    assert any("选项 C" in item and "疑似编造" in item for item in problems)


def test_grounded_choice_passes_validation() -> None:
    payload = _choice_payload(
        options=[
            {"key": "A", "text": "单线程处理命令", "is_correct": True},
            {"key": "B", "text": "避免了锁竞争", "is_correct": False},
            {"key": "C", "text": "6.0 起引入多线程 IO", "is_correct": False},
        ]
    )

    assert validate_generated_question(payload, source_text=SOURCE) == []


def test_points_round_trip_and_drive_grading(tmp_path) -> None:
    db = tmp_path / "q.db"
    init_db(str(db))
    conn = get_connection(str(db))
    try:
        conn.execute(
            "INSERT INTO trainings (id, topic, status, created_at) "
            "VALUES (1, 'Redis', 'active', '2026-10-15T00:00:00')"
        )
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, banked_at) "
            "VALUES (1, 'k1', '2026-10-15T00:00:00')"
        )
        conn.commit()

        save_question_points(1, "k1", _points(3), conn=conn)
        points = load_points(1, "k1", conn=conn)

        result = grade_question(
            "qa", answer="x", points=points, point_verdicts={"p1": HIT, "p2": HIT}
        )
    finally:
        conn.close()

    assert [spec.point_id for spec in points] == ["p1", "p2", "p3"]
    assert points[0].required is True
    assert result.coverage == pytest.approx(2 / 3)
    assert result.missing == ("p3",)


def test_invalid_payload_is_not_persisted(tmp_path) -> None:
    db = tmp_path / "q2.db"
    init_db(str(db))
    conn = get_connection(str(db))
    try:
        conn.execute(
            "INSERT INTO trainings (id, topic, status, created_at) "
            "VALUES (1, 'Redis', 'active', '2026-10-15T00:00:00')"
        )
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, banked_at) "
            "VALUES (1, 'k1', '2026-10-15T00:00:00')"
        )
        conn.commit()

        problems = save_generated_question(
            1, "k1", {"question_type": "qa", "points": []}, conn=conn
        )
        stored = load_points(1, "k1", conn=conn)
    finally:
        conn.close()

    assert problems
    assert stored == []
