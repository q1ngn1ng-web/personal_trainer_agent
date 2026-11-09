"""Explain a single grading decision, step by step (判分解剖工具).

Usage::

    # 离线重放：用库里已存的判分明细，重演规则层每一步算术（零 API 调用）
    uv run python scripts/explain_grading.py 235
    uv run python scripts/explain_grading.py 139

    # 现场判分：换一份自己的作答，走真实生产链路（需要 API key，会调用模型并写入缓存）
    uv run python scripts/explain_grading.py 235 --live --answer "你的作答"

What it shows, in order:

* 第 0 步 评分锚：出题时固化的要点清单（模型只在这一步参与出题，判分只读）；
* 第 1 步 模型意见：逐条四态（hit/partial/wrong/missing）——来自历史作答记录或现场调用；
* 第 2-4 步 规则层代入：覆盖率、正确性、得分，逐项代入真实权重与系数；
* 第 5 步 必答否决与阈值判定；
* 第 6 步 落库与达标（practice_attempts → 连续 2 次 → passed）。

Design intent this tool demonstrates: 模型只输出「语义意见」，分数与对错由确定性代码
计算——同一份意见永远算出同一个分数（可用本脚本反复验证）。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.grading_service import DEFAULT_PASS_THRESHOLD, PointSpec, grade_question, score_points  # noqa: E402

COEFF = {"hit": 1.0, "partial": 0.5, "wrong": 0.0, "missing": 0.0}


def _connect() -> sqlite3.Connection:
    db = Path(os.environ.get("DB_PATH", PROJECT_ROOT / "data" / "trainer.db"))
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load(plan_id: int) -> tuple[sqlite3.Row, list[PointSpec], dict[str, str], dict | None]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT p.id, p.training_id, p.item_key, p.question, p.reference_answer, "
            "       p.points, p.answer_text, p.verdict, t.topic "
            "FROM plan_items p JOIN trainings t ON t.id = p.training_id WHERE p.id = ?",
            (plan_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"plan_item #{plan_id} 不存在")
        specs = [
            PointSpec(str(p["point_id"]), str(p["text"]), float(p["weight"]), bool(p["is_required"]))
            for p in json.loads(row["points"] or "[]")
        ]
        att = conn.execute(
            "SELECT id, result, score, point_results, created_at FROM practice_attempts "
            "WHERE training_id = ? AND item_key = ? ORDER BY id DESC LIMIT 1",
            (row["training_id"], row["item_key"]),
        ).fetchone()
        verdicts: dict[str, str] = {}
        detail = None
        if att is not None and att["point_results"]:
            detail = dict(att)
            for p in json.loads(att["point_results"]):
                verdicts[str(p["point_id"])] = str(p["verdict"])
        return row, specs, verdicts, detail
    finally:
        conn.close()


def _live_verdicts(row: sqlite3.Row, specs: list[PointSpec], answer: str) -> dict[str, str]:
    """现场走生产判分链路（需要 API key；会写判分缓存与 llm_calls）。"""
    from src.services.answer_service import _grade_answer

    context = {
        "training_id": row["training_id"],
        "item_key": row["item_key"],
        "question": row["question"],
        "reference_answer": row["reference_answer"],
        "points": json.dumps(
            [{"point_id": s.point_id, "text": s.text, "weight": s.weight, "is_required": s.required} for s in specs],
            ensure_ascii=False,
        ),
    }
    outcome = _grade_answer(context, answer)
    if not outcome.get("graded"):
        raise SystemExit(f"现场判分不可用：{outcome.get('reason') or '模型不可用或无要点'}")
    return {p["point_id"]: p["verdict"] for p in json.loads(outcome["point_results"])}


def main() -> int:
    parser = argparse.ArgumentParser(description="判分解剖：一步步展示一次判分是怎么算出来的")
    parser.add_argument("plan_id", type=int, help="plan_items.id")
    parser.add_argument("--live", action="store_true", help="用真实模型现场判分（默认离线重放历史判定）")
    parser.add_argument("--answer", default=None, help="--live 时使用的作答文本（缺省用库里存的作答）")
    args = parser.parse_args()

    row, specs, verdicts, detail = _load(args.plan_id)
    answer = args.answer or row["answer_text"] or ""

    print(f"plan_item #{row['id']}｜训练「{row['topic']}」｜库内判定 verdict={row['verdict']}")
    print(f"题目：{row['question']}")
    print(f"作答：{answer!r}")

    print("\n── 第 0 步｜评分锚（出题时由模型生成并固化落库，判分时只读）──")
    for s in specs:
        print(f"  {s.point_id}: {s.text}｜权重 {s.weight}{'｜必答' if s.required else ''}")

    if args.live:
        print("\n── 第 1 步｜模型意见（现场调用，走生产链路）──")
        verdicts = _live_verdicts(row, specs, answer)
    elif not verdicts:
        raise SystemExit(
            "该题没有历史作答明细；用 --live --answer \"…\" 现场判分，或换有作答记录的 plan_id"
        )
    else:
        src = f"practice_attempt #{detail['id']}（{detail['created_at'][:10]} 判定）"
        print(f"\n── 第 1 步｜模型意见（离线重放：{src}）──")
    for s in specs:
        print(f"  {s.point_id}: {verdicts.get(s.point_id, 'missing')} ← {s.text[:30]}")

    if not any(s.point_id in verdicts for s in specs):
        raise SystemExit("模型意见里没有任何有效要点判定（可能走了整体二元降级），无可解剖的算术")

    print("\n── 第 2 步｜覆盖率 = Σ(权重×系数) / Σ权重 ──")
    total_w = sum(s.weight for s in specs)
    terms, hit_w = [], 0.0
    for s in specs:
        c = COEFF.get(verdicts.get(s.point_id, "missing"), 0.0)
        terms.append(f"{s.weight}×{c:g}（{s.point_id}={verdicts.get(s.point_id, 'missing')}）")
        hit_w += s.weight * c
    print(f"  = ({' + '.join(terms)}) / {total_w:g}")
    print(f"  = {hit_w:g} / {total_w:g} = {hit_w / total_w:.4f}")

    print("\n── 第 3 步｜正确性 = 1 − 错误权重 / 作答涉及权重 ──")
    wrong_w = sum(s.weight for s in specs if verdicts.get(s.point_id, "missing") == "wrong")
    attempted_w = sum(s.weight for s in specs if verdicts.get(s.point_id, "missing") != "missing")
    print(f"  错误权重（wrong 的权重和）= {wrong_w:g}；涉及权重（非 missing 的权重和）= {attempted_w:g}")
    correctness = 1.0 if attempted_w <= 0 else max(0.0, 1.0 - wrong_w / attempted_w)
    print(f"  = 1 − {wrong_w:g}/{attempted_w:g} = {correctness:.4f}")

    ps = score_points(specs, verdicts)
    print(f"\n── 第 4 步｜得分 = 覆盖率 × 正确性 = {ps.coverage:.4f} × {ps.correctness:.4f} = {ps.score:.4f} ──")

    print(f"\n── 第 5 步｜必答否决与阈值（阈值 {DEFAULT_PASS_THRESHOLD}，必答要点全 hit 才不否决）──")
    required_missing = ps.required_missing
    passed = not required_missing and ps.score >= DEFAULT_PASS_THRESHOLD
    if required_missing:
        print(f"  必答要点缺失：{'、'.join(required_missing)} → 一票否决 → fail")
    else:
        print(f"  必答要点无缺失；得分 {ps.score:.4f} {'≥' if ps.score >= DEFAULT_PASS_THRESHOLD else '<'} {DEFAULT_PASS_THRESHOLD} → {'pass' if passed else 'fail'}")

    print("\n── 第 6 步｜落库与达标 ──")
    if detail is not None and not args.live:
        print(f"  本次判定已落 practice_attempts #{detail['id']}（result={detail['result']}, score={detail['score']}）")
    else:
        print("  生产链路会把本次判定写入 practice_attempts（result/score/逐条明细）")
    print("  达标规则：同一训练项最近连续 2 次 pass → training_items.status='passed'（由 attempt_service 写，模型无权写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
