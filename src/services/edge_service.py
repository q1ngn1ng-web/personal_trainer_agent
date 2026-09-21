"""理解边缘定位：从来源切片出题、作答、判定三态。

对应 OpenSpec change ``understanding-edge-assessment`` 与 ADR-0018。
**本版是简化实现**：每个知识点 1 道题，三态由「题目难度 + 是否答对」按规则判定；
完整的「难度 1→4 升降档自适应探测」留待后续迭代。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.db.models import EdgeAssessment
from src.db.sqlite import get_connection
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY
from src.services import source_service as svc

logger = logging.getLogger("src.services.edge_service")

#: 一次探测最多覆盖多少个知识点（控制回答负担）
MAX_KNOWLEDGE_POINTS: int = 8

#: 每个知识点取样多少字作为出题依据
_SAMPLE_CHARS: int = 400

PROBE_STATE_LABELS: dict[str, str] = {
    "mastered": "✅ 已掌握（跳过，只做维护复习）",
    "edge": "🎯 边缘（教学重点）",
    "unreached": "🧱 未达（先做前置铺垫）",
}


@dataclass
class KnowledgePoint:
    """一个待探测的知识点，来源是资料切片。"""

    name: str
    heading_path: str
    sample_text: str


@dataclass
class ProbeItem:
    """一道探测题。"""

    knowledge_point: str
    heading_path: str
    difficulty: int
    question: str
    reference_answer: str
    answer: str = ""
    verdict: str | None = None
    reason: str = ""
    state: str | None = None


@dataclass
class ProbeResult:
    """一次探测的完整结果。"""

    training_id: int
    items: list[ProbeItem] = field(default_factory=list)
    fallback_used: bool = False
    #: 资料里识别出的知识点总数（用于告诉用户"这次只探了前几个"）
    total_points: int = 0
    #: 本次实际探测的知识点数
    selected_points: int = 0

    @property
    def is_graded(self) -> bool:
        return bool(self.items) and all(item.verdict for item in self.items)

    @property
    def truncated(self) -> bool:
        """是否发生了"只探了一部分知识点"的截断。"""
        return self.total_points > self.selected_points > 0

    def state_counts(self) -> dict[str, int]:
        counts = {"mastered": 0, "edge": 0, "unreached": 0}
        for item in self.items:
            if item.state in counts:
                counts[item.state] += 1
        return counts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def build_knowledge_points(
    training_id: int, *, limit: int = MAX_KNOWLEDGE_POINTS, conn: sqlite3.Connection | None = None
) -> list[KnowledgePoint]:
    """从已导入来源的切片里推导知识点清单（按标题路径去重）。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            """
            SELECT c.heading_path, c.text
            FROM source_chunks c
            JOIN sources s ON s.id = c.source_id
            WHERE s.training_id = ? AND s.enabled = 1
            ORDER BY c.id
            """,
            (training_id,),
        ).fetchall()
    finally:
        if own:
            active.close()

    points: list[KnowledgePoint] = []
    seen: set[str] = set()
    for row in rows:
        heading = (row["heading_path"] or "（未分节）").strip()
        if heading in seen:
            continue
        seen.add(heading)
        points.append(
            KnowledgePoint(
                name=heading.split(" > ")[-1][:60],
                heading_path=heading,
                sample_text=(row["text"] or "")[:_SAMPLE_CHARS],
            )
        )
        if len(points) >= limit:
            break
    return points


def count_knowledge_points(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> int:
    """资料里一共有多少个去重后的知识点（标题路径）——用于诚实告知探测覆盖面。"""
    active = _connect(conn)
    own = conn is None
    try:
        row = active.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(NULLIF(TRIM(c.heading_path), ''), '（未分节）')) AS n
            FROM source_chunks c
            JOIN sources s ON s.id = c.source_id
            WHERE s.training_id = ? AND s.enabled = 1
            """,
            (training_id,),
        ).fetchone()
        return int(row["n"] or 0)
    finally:
        if own:
            active.close()


def _format_points(points: list[KnowledgePoint]) -> str:
    return "\n\n".join(
        f"[知识点 {index + 1}] {point.name}\n标题路径: {point.heading_path}\n来源片段: {point.sample_text}"
        for index, point in enumerate(points)
    )


def _fallback_question(point: KnowledgePoint) -> str:
    """模型出题失败时的兜底问法。

    资料本身常常就是题目（如八股文），所以先看片段里有没有现成的问句；
    没有就针对该知识点的**内容**提问，而不是问「这一页讲的是什么」。
    """
    sample = (point.sample_text or "").strip()
    for raw_line in sample.splitlines():
        line = raw_line.strip()
        if 6 <= len(line) <= 60 and line.endswith(("？", "?")):
            return line
    return f"请说出「{point.name}」的关键要点（不查资料，凭理解作答）。"


def generate_probe_items(
    training_id: int,
    *,
    topic: str,
    goal: Any = None,
    points: list[KnowledgePoint] | None = None,
    conn: sqlite3.Connection | None = None,
) -> ProbeResult:
    """按知识点出题。题目只依据来源片段，不考资料之外的内容。"""
    total_points = count_knowledge_points(training_id, conn=conn)
    knowledge_points = points if points is not None else build_knowledge_points(training_id, conn=conn)
    if not knowledge_points:
        raise ValueError("没有可用的资料切片，无法出题")

    variables = {
        "topic": topic,
        "goal": json.dumps(goal or {}, ensure_ascii=False),
        "knowledge_points": _format_points(knowledge_points),
    }
    try:
        result = complete("edge_probe", variables, schema=SCHEMA_REGISTRY["edge_probe"])
        output = result.get("output_json") or {}
    except Exception as exc:
        # 模型不可用不应该让用户卡在向导里：退回按知识点生成的朴素问法
        from src.llm.client import log_llm_failure

        logger.warning("generate_probe_items: LLM unavailable (%s), using fallback", exc)
        log_llm_failure("edge_probe", json.dumps(variables, ensure_ascii=False), exc)
        output = {}
    questions = output.get("questions") or []

    items: list[ProbeItem] = []
    for raw in questions:
        items.append(
            ProbeItem(
                knowledge_point=str(raw.get("knowledge_point", "")).strip(),
                heading_path=str(raw.get("heading_path", "")).strip(),
                difficulty=int(raw.get("difficulty", 1) or 1),
                question=str(raw.get("question", "")).strip(),
                reference_answer=str(raw.get("reference_answer", "")).strip(),
            )
        )
    if not items:
        # 降级：按知识点生成最朴素的问法，保证流程能继续
        items = [
            ProbeItem(
                knowledge_point=point.name,
                heading_path=point.heading_path,
                difficulty=2,
                question=_fallback_question(point),
                reference_answer=point.sample_text[:200],
            )
            for point in knowledge_points
        ]
    if not total_points:
        total_points = len(knowledge_points)
    return ProbeResult(
        training_id=training_id,
        items=items,
        fallback_used=not questions,
        total_points=total_points,
        selected_points=len(knowledge_points),
    )


def grade_probe(
    training_id: int, items: list[ProbeItem], *, topic: str
) -> ProbeResult:
    """对作答评分并判定三态（判定规则在 :func:`judge_state`）。"""
    payload = [
        {
            "knowledge_point": item.knowledge_point,
            "question": item.question,
            "reference_answer": item.reference_answer,
            "answer": item.answer,
        }
        for item in items
    ]
    try:
        result = complete(
            "edge_probe_grade",
            {"topic": topic, "items": json.dumps(payload, ensure_ascii=False, indent=2)},
            schema=SCHEMA_REGISTRY["edge_probe_grade"],
        )
        output = result.get("output_json") or {}
    except Exception as exc:
        from src.llm.client import log_llm_failure

        logger.warning("grade_probe: LLM unavailable (%s), treating all as fail", exc)
        log_llm_failure("edge_probe_grade", json.dumps(payload, ensure_ascii=False), exc)
        output = {}
    verdicts = {str(v.get("knowledge_point", "")).strip(): v for v in (output.get("verdicts") or [])}

    for item in items:
        entry = verdicts.get(item.knowledge_point)
        if entry:
            item.verdict = "pass" if entry.get("verdict") == "pass" else "fail"
            item.reason = str(entry.get("reason", ""))
        else:
            item.verdict = "fail"
            item.reason = "未能取得评定结果，按未通过处理"
        item.state = judge_state(item.verdict, item.difficulty)
    return ProbeResult(training_id=training_id, items=items, fallback_used=not verdicts)


def judge_state(verdict: str, difficulty: int) -> str:
    """三态判定（规则层，不由模型决定）。

    简化口径：答对高档位题 = 已掌握；答对基础题或做错难题 = 边缘；基础题就做错 = 未达。
    """
    passed = verdict == "pass"
    if passed and difficulty >= 3:
        return "mastered"
    if not passed and difficulty <= 2:
        return "unreached"
    return "edge"


def save_probe(
    result: ProbeResult, conn: sqlite3.Connection | None = None
) -> None:
    """把探测结果落库（重复探测会先清掉旧的）。"""
    active = _connect(conn)
    own = conn is None
    try:
        active.execute("DELETE FROM edge_assessments WHERE training_id = ?", (result.training_id,))
        active.executemany(
            "INSERT INTO edge_assessments (training_id, knowledge_point, heading_path, difficulty, "
            "question, reference_answer, answer, verdict, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    result.training_id,
                    item.knowledge_point,
                    item.heading_path,
                    item.difficulty,
                    item.question,
                    item.reference_answer,
                    item.answer,
                    item.verdict,
                    item.state,
                    _now(),
                )
                for item in result.items
            ],
        )
        if own:
            active.commit()
    finally:
        if own:
            active.close()


def load_probe(training_id: int, conn: sqlite3.Connection | None = None) -> ProbeResult | None:
    """读回最近一次探测结果。"""
    active = _connect(conn)
    own = conn is None
    try:
        rows = active.execute(
            "SELECT * FROM edge_assessments WHERE training_id = ? ORDER BY id",
            (training_id,),
        ).fetchall()
    finally:
        if own:
            active.close()
    if not rows:
        return None
    items = [
        ProbeItem(
            knowledge_point=row["knowledge_point"],
            heading_path=row["heading_path"] or "",
            difficulty=int(row["difficulty"] or 1),
            question=row["question"],
            reference_answer=row["reference_answer"] or "",
            answer=row["answer"] or "",
            verdict=row["verdict"],
            state=row["state"],
        )
        for row in rows
    ]
    return ProbeResult(training_id=training_id, items=items)


__all__ = [
    "MAX_KNOWLEDGE_POINTS",
    "PROBE_STATE_LABELS",
    "KnowledgePoint",
    "ProbeItem",
    "ProbeResult",
    "build_knowledge_points",
    "count_knowledge_points",
    "generate_probe_items",
    "grade_probe",
    "judge_state",
    "load_probe",
    "save_probe",
]
