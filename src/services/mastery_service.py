"""阶段达标与任务达标：把"练到什么程度算完成"变成可查、可写回的确定状态。

对应 change ``training-execution-feedback`` 的任务 5.2 / 5.3 与 ADR-0011：

* **阶段达标**：覆盖模式看本阶段必修项是否全部达标；达成模式看阶段验收判据（判不了就退回覆盖口径）
* **任务达标**：必修覆盖 100%（全部训练项 `passed`）**且**最近一次完成的测验通过
* 判定结果会**写回** `path_stages.status`（修掉"阶段永远 locked"的老问题）与 `trainings.status='completed'`
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.mastery import (
    COVERAGE_MODE,
    MASTERY_MODE,
    consecutive_passes,
    coverage_satisfied,
    stage_mastered,
)
from src.db.sqlite import get_connection
from src.services import attempt_service

logger = logging.getLogger("src.services.mastery_service")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


@dataclass
class StageStatus:
    """一个阶段的达标情况。"""

    stage_id: int
    ordinal: int
    title: str
    status: str
    mastered: bool
    reason: str
    total: int = 0
    passed: int = 0
    practiced: int = 0


@dataclass
class TrainingStatusReport:
    """整个训练的达标情况。"""

    training_id: int
    mode: str
    total_items: int
    passed_items: int
    practiced_items: int
    coverage_done: bool
    quiz_passed: bool
    mastered: bool
    stages: list[StageStatus] = field(default_factory=list)
    reason: str = ""


def _preferred_path(active: sqlite3.Connection, training_id: int) -> sqlite3.Row | None:
    return active.execute(
        "SELECT * FROM training_paths WHERE training_id = ? "
        "ORDER BY (status = 'confirmed') DESC, version DESC LIMIT 1",
        (int(training_id),),
    ).fetchone()


def _acceptance(active: sqlite3.Connection, training_id: int) -> dict[str, Any] | None:
    row = active.execute(
        "SELECT goal_json FROM trainings WHERE id = ?", (int(training_id),)
    ).fetchone()
    if row is None or not row["goal_json"]:
        return None
    payload = row["goal_json"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        acceptance = payload.get("acceptance")
        return acceptance if isinstance(acceptance, dict) else None
    return None


def _max_streak(active: sqlite3.Connection, training_id: int) -> int:
    """任一训练项的最大连续通过次数（streak 判据用）。"""
    rows = active.execute(
        "SELECT item_key, result FROM practice_attempts WHERE training_id = ? ORDER BY item_key, id",
        (int(training_id),),
    ).fetchall()
    buckets: dict[str, list[str]] = {}
    for row in rows:
        buckets.setdefault(str(row["item_key"]), []).append(str(row["result"]))
    return max((consecutive_passes(values) for values in buckets.values()), default=0)


def _stage_rows(active: sqlite3.Connection, training_id: int) -> list[dict[str, Any]]:
    path = _preferred_path(active, training_id)
    if path is None:
        return []
    rows = active.execute(
        """
        SELECT s.id AS stage_id, s.ordinal AS stage_ordinal, s.title AS title,
               s.status AS stage_status, i.item_key, i.status AS item_status
        FROM path_stages s
        LEFT JOIN training_items i ON i.stage_id = s.id
        WHERE s.path_id = ?
        ORDER BY s.ordinal, i.ordinal
        """,
        (int(path["id"]),),
    ).fetchall()
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        bucket = grouped.setdefault(
            int(row["stage_id"]),
            {
                "stage_id": int(row["stage_id"]),
                "ordinal": int(row["stage_ordinal"]),
                "title": str(row["title"]),
                "status": str(row["stage_status"] or "locked"),
                "statuses": [],
            },
        )
        if row["item_status"] is not None:
            bucket["statuses"].append(str(row["item_status"]))
    return list(grouped.values())


def stage_statuses(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> list[StageStatus]:
    """算出每个阶段的达标情况（不改库）。"""
    active = _connect(conn)
    own = conn is None
    try:
        path = _preferred_path(active, training_id)
        mode = str(path["mode"] or MASTERY_MODE) if path else MASTERY_MODE
        acceptance = _acceptance(active, training_id)
        accuracy, _attempts = attempt_service.training_accuracy(training_id, conn=active)
        practiced_total = int(
            active.execute(
                "SELECT COUNT(*) AS n FROM plan_items WHERE training_id = ? AND status = 'practiced'",
                (int(training_id),),
            ).fetchone()["n"]
        )
        streak = _max_streak(active, training_id)

        results: list[StageStatus] = []
        for bucket in _stage_rows(active, training_id):
            statuses = bucket["statuses"]
            verdict = stage_mastered(
                mode,
                statuses,
                acceptance=acceptance,
                accuracy=accuracy,
                practiced=practiced_total,
                streak=streak,
            )
            results.append(
                StageStatus(
                    stage_id=bucket["stage_id"],
                    ordinal=bucket["ordinal"],
                    title=bucket["title"],
                    status=bucket["status"],
                    mastered=verdict.mastered,
                    reason=verdict.reason,
                    total=len(statuses),
                    passed=sum(1 for status in statuses if status == "passed"),
                    practiced=sum(1 for status in statuses if status in ("practiced", "passed")),
                )
            )
        return results
    finally:
        if own:
            active.close()


def sync_stages(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> list[StageStatus]:
    """把阶段达标结果写回 `path_stages.status`（全部达标 → completed，第一个未达标 → active，其余 locked）。"""
    active = _connect(conn)
    own = conn is None
    try:
        stages = stage_statuses(training_id, conn=active)
        first_open = next((index for index, stage in enumerate(stages) if not stage.mastered), None)
        for index, stage in enumerate(stages):
            if stage.mastered:
                target = "completed"
            elif first_open is not None and index == first_open:
                target = "active"
            else:
                target = "locked"
            if stage.status != target:
                active.execute(
                    "UPDATE path_stages SET status = ? WHERE id = ?", (target, stage.stage_id)
                )
            stage.status = target
        if own:
            active.commit()
        return stages
    finally:
        if own:
            active.close()


def training_progress(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> TrainingStatusReport:
    """任务达标报告：必修覆盖 100% 且最近一次测验通过。"""
    active = _connect(conn)
    own = conn is None
    try:
        path = _preferred_path(active, training_id)
        mode = str(path["mode"] or MASTERY_MODE) if path else MASTERY_MODE
        stages = _stage_rows(active, training_id)
        statuses = [status for bucket in stages for status in bucket["statuses"]]
        passed_items = sum(1 for status in statuses if status == "passed")
        practiced_items = sum(1 for status in statuses if status in ("practiced", "passed"))
        coverage_done = coverage_satisfied(statuses)

        quiz_row = active.execute(
            "SELECT passed FROM assessments WHERE training_id = ? AND status = 'completed' "
            "ORDER BY id DESC LIMIT 1",
            (int(training_id),),
        ).fetchone()
        quiz_passed = bool(quiz_row is not None and int(quiz_row["passed"] or 0) == 1)

        reason = "必修覆盖 100% 且最终测验通过" if (coverage_done and quiz_passed) else ""
        if not coverage_done:
            reason = f"还有 {len(statuses) - passed_items} 个训练项未达标"
        elif not quiz_passed:
            reason = "必修已全部达标，但还没有通过的测验"
        return TrainingStatusReport(
            training_id=int(training_id),
            mode=mode,
            total_items=len(statuses),
            passed_items=passed_items,
            practiced_items=practiced_items,
            coverage_done=coverage_done,
            quiz_passed=quiz_passed,
            mastered=coverage_done and quiz_passed,
            reason=reason,
        )
    finally:
        if own:
            active.close()


def sync_training_status(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> str | None:
    """任务达标时把训练置为 `completed`（终态）。返回是否发生迁移（``'completed'`` 或 None）。"""
    active = _connect(conn)
    own = conn is None
    try:
        report = training_progress(training_id, conn=active)
        if not report.mastered:
            return None
        row = active.execute(
            "SELECT status FROM trainings WHERE id = ?", (int(training_id),)
        ).fetchone()
        if row is None or str(row["status"]) == "completed":
            return None
        active.execute(
            "UPDATE trainings SET status = 'completed', last_active_at = ? WHERE id = ?",
            (_now(), int(training_id)),
        )
        if own:
            active.commit()
        logger.info("sync_training_status: training %s 任务达标 → completed", training_id)
        return "completed"
    finally:
        if own:
            active.close()


def evaluate(
    training_id: int, *, conn: sqlite3.Connection | None = None
) -> TrainingStatusReport:
    """一站式：同步阶段状态 → 同步任务状态 → 返回报告（页面进入时调用）。"""
    active = _connect(conn)
    own = conn is None
    try:
        stages = sync_stages(training_id, conn=active)
        report = training_progress(training_id, conn=active)
        report.stages = stages
        sync_training_status(training_id, conn=active)
        if own:
            active.commit()
        return report
    finally:
        if own:
            active.close()


__all__ = [
    "COVERAGE_MODE",
    "MASTERY_MODE",
    "StageStatus",
    "TrainingStatusReport",
    "evaluate",
    "stage_statuses",
    "sync_stages",
    "sync_training_status",
    "training_progress",
]
