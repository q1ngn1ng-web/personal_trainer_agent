"""Backfill question_type/options for legacy plan items (2026-11-15 UI fix follow-up).

Usage::

    DB_PATH=./data/trainer.db uv run python scripts/backfill_question_meta.py

背景：修复「客观题分流」之前生成的轮次，plan_items 里没有 question_type/options
（选择题的选项只存在于当时的出题响应里，从未落库）——这类老轮次在前端既没有
可选项，也不会走确定性判分。

处理策略（只动**未作答**的计划项，已练/已达标的历史一律不改）：

* 题库（question_bank）里同一 (training_id, item_key) 有题型/选项 → **回填**；
* 题库也没有 → 清空题目包（question/reference_answer/points 一并置空），
  下次打开该轮次时按新 schema **自动重新生成**（一次 LLM 调用，正常懒生成路径）。

只读打开数据库统计；写入用同一连接提交。WAL 模式下与服务进程并发安全。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "trainer.db"))


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, training_id, item_key, question FROM plan_items "
        "WHERE kind = 'train' AND status = 'planned' "
        "AND question IS NOT NULL AND question_type IS NULL"
    ).fetchall()
    print(f"待处理（planned + 有题干 + 缺题型）: {len(rows)} 条")

    backfilled = cleared = 0
    for row in rows:
        bank = conn.execute(
            "SELECT question_type, options FROM question_bank "
            "WHERE training_id = ? AND item_key = ?",
            (row["training_id"], row["item_key"]),
        ).fetchone()
        if bank is not None and bank["question_type"] and bank["options"]:
            try:
                json.loads(bank["options"])
            except (TypeError, ValueError):
                bank = None
        if bank is not None and bank["question_type"] and bank["options"]:
            conn.execute(
                "UPDATE plan_items SET question_type = ?, options = ? WHERE id = ?",
                (bank["question_type"], bank["options"], row["id"]),
            )
            backfilled += 1
        else:
            # 题库里也没有可回填的题型/选项：清空题目包，下次打开懒生成（新 schema）
            conn.execute(
                "UPDATE plan_items SET question = NULL, reference_answer = NULL, "
                "points = NULL WHERE id = ?",
                (row["id"],),
            )
            cleared += 1
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) FROM plan_items WHERE kind = 'train' AND status = 'planned' "
        "AND question IS NOT NULL AND question_type IS NULL"
    ).fetchone()[0]
    print(f"回填自题库: {backfilled} 条；清空待重生成: {cleared} 条；剩余未处理: {remaining}")
    print("已练/已达标的历史轮次未改动。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
