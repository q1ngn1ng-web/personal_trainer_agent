"""审计覆盖冒烟：在临时库上走一遍「老链路 + 学习闭环主链」，断言每个 prompt 链路都在 llm_calls 落账。

用法：
    DEEPSEEK_API_KEY= uv run python scripts/audit_coverage_smoke.py

无真实 key（全部走 fallback / 失败路径）即可执行；也可以带真实 key 跑成功路径。
每条链路断言 llm_calls 至少有一行对应记录，最后打印 per-purpose 覆盖表。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEEPSEEK_API_KEY", "")  # 默认无 key：全部走降级路径

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import (  # noqa: E402
    answer_service,
    baseline_service,
    calibration_service,
    edge_service,
    explanation_service,
    goal_clarification_service,
    keyword_service,
    metrics_calculator,
    path_service,
    plan_service,
    quiz_service,
    scoring_service,
    topic_validation,
    trainer_service,
)


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _seed_training_context(training_id: int, conn: sqlite3.Connection) -> None:
    """为学习闭环主链准备最小数据：资料切片、计划项、题库条目。"""
    conn.execute(
        "INSERT INTO sources (id, training_id, type, title, parse_status, imported_at) "
        "VALUES (1, ?, 'user_paste', '冒烟手册', 'ok', ?)",
        (training_id, _now()),
    )
    conn.execute(
        "INSERT INTO source_chunks (id, source_id, ordinal, heading_path, text, char_count) "
        "VALUES (1, 1, 1, 'RDB > 快照', 'RDB 是快照持久化，适合备份。', 18)"
    )
    conn.execute(
        "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, anchor_date, "
        "original_date, status, planned_minutes, created_at) "
        "VALUES (?, 'smoke0001item', 1, 'train', ?, ?, ?, 'planned', 10, ?)",
        (training_id, date.today().isoformat(), date.today().isoformat(),
         date.today().isoformat(), _now()),
    )
    conn.execute(
        "INSERT INTO question_bank (training_id, item_key, source_chunk_ids, knowledge_point, "
        "question_text, answer_text, banked_at, cooldown_until, status) "
        "VALUES (?, 'smoke0001item', '1', 'RDB', 'RDB 是什么？', '快照持久化', ?, ?, 'active')",
        (training_id, _now(), (date.today() - timedelta(days=30)).isoformat()),
    )
    conn.commit()


def main() -> int:
    tmp = tempfile.TemporaryDirectory()
    os.environ["DB_PATH"] = str(Path(tmp.name) / "audit_smoke.db")
    init_db()

    topic = "Redis 持久化"

    # —— 十要素一代链路（训练创建前）——
    topic_validation.validate_topic(topic)
    keyword_service.generate_keywords(topic)
    baseline_service.generate_baseline_questions(topic, ["RDB", "AOF"], 2, [])
    scoring_service.score_baseline(
        topic,
        baseline_service.generate_baseline_questions(topic, ["RDB"], 1, []).questions,
        ["快照", "日志"],
    )

    training = queries.create_training(topic=topic, status="active")
    training_id = int(training.id)
    goal_clarification_service.start_session(topic)
    trainer_service._generate_pretrain_checklist(topic, ["RDB"], [])

    conn = sqlite3.connect(os.environ["DB_PATH"])
    _seed_training_context(training_id, conn)
    conn.close()

    # —— 学习闭环主链 ——
    edge_service.generate_probe_items(training_id, topic=topic, goal={})
    path_service.generate_skeleton(training_id, topic=topic, goal={})
    plan_items = queries.list_plan_items(training_id) if hasattr(queries, "list_plan_items") else []
    if plan_items:
        answer_service.ensure_question(int(plan_items[0].id))
    else:
        # 直接按冒烟种子里的 item_key 找 plan_id
        row = sqlite3.connect(os.environ["DB_PATH"]).execute(
            "SELECT id FROM plan_items WHERE item_key='smoke0001item'"
        ).fetchone()
        if row:
            answer_service.ensure_question(int(row[0]))
    quiz_service.build_questions(
        [{"item_key": "smoke0001item", "knowledge_point": "RDB",
          "question_text": "RDB 是什么？", "answer_text": "快照持久化"}],
        training_id=training_id,
    )
    explanation_service.generate_explanation(training_id, "smoke0001item")
    calibration_service.generate_calibration(
        training,
        metrics_calculator.WeeklyMetrics(
            training_id=training_id,
            week_start=date.today() - timedelta(days=7),
            week_end=date.today(),
        ),
    )

    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT call_purpose, COUNT(*) AS n FROM llm_calls GROUP BY call_purpose"))
    conn.close()

    by_purpose = {row["call_purpose"]: row["n"] for row in rows}
    expected = [
        "topic_validation",
        "keyword_generation",
        "baseline_q",
        "baseline_scoring",
        "goal_clarification",
        "pretrain_checklist",
        "edge_probe",
        "path_skeleton",
        "train_question",
        "quiz_variant",
        "explanation",
        "weekly_calibration",
    ]
    print(f"{'call_purpose'.ljust(22)} rows")
    for purpose in expected:
        n = by_purpose.get(purpose, 0)
        mark = "OK " if n >= 1 else "MISS"
        print(f"{purpose.ljust(22)} {n:>4}  {mark}")
    total = sum(by_purpose.values())
    print(f"Total: {total} rows across {len(by_purpose)} purpose(s)")

    missing = [p for p in expected if by_purpose.get(p, 0) < 1]
    if missing:
        print(f"FAILED: missing audit rows for {missing}")
        return 1
    print("audit coverage smoke: ALL COVERED")
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
