"""FastAPI 后端：鉴权注入 + 只读接口（P0/P1，ADR-0024）。

设计原则（与 ADR-0024 一致）：**只做鉴权、参数校验与序列化**，
业务规则一律调用 `src/services/` ——因此 Streamlit 与 Vue 两个界面行为必然一致。

个人版（没有登录）时 `viewer is None`，权限判定放行（ADR-0020 的 profile 语义）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.core.permissions import (
    Action,
    Role,
    Viewer,
    can,
    can_view_source,
    can_view_training,
    visible_trainings,
)
from src.services.grading_service import parse_options
from src.db import queries
from src.db.connection import IntegrityError
from src.services import (
    answer_service,
    assignment_service,
    attempt_service,
    auth_service,
    mastery_service,
    org_service,
    path_service,
    plan_service,
    preferences_service,
    quiz_service,
    review_service,
    session_summary,
    signal_service,
    source_service,
)
from src.services.calibration_service import CalibrationSuggestion
from src.services.progress_service import compute_home_dashboard

logger = logging.getLogger("src.api.app")

#: 会话 Cookie 名
SESSION_COOKIE = "tc_session"

#: 是否强制 HTTPS Cookie（生产环境应开；本地 http 调试默认关）
COOKIE_SECURE = os.environ.get("TRAINER_COOKIE_SECURE", "0") == "1"

app = FastAPI(title="训练教练 API", version="0.1.0")


def auth_enabled() -> bool:
    """当前 profile 是否启用鉴权（默认企业版：需要登录）。"""
    return os.environ.get("TRAINER_AUTH", "1") == "1"


#: 不要求登录的接口（登录流程本身 + 健康检查）
_AUTH_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/api/health",
        "/api/auth/mode",
        "/api/auth/request-code",
        "/api/auth/verify",
        "/api/auth/logout",
        # 个人版（2026-10-26）：注册与密码登录也是公开入口
        "/api/auth/register",
        "/api/auth/login",
    }
)


def _has_valid_session(cookie_value: str | None) -> bool:
    return bool(cookie_value) and auth_service.viewer_from_session(cookie_value) is not None


@app.middleware("http")
async def enforce_auth(request: Request, call_next: Any) -> Any:
    """企业版 profile 下，未登录一律 401——**服务端强制**，不依赖前端守卫。

    个人版 profile（`TRAINER_AUTH=0`）不做拦截，`viewer` 恒为 None 且权限判定放行（ADR-0020）。
    """
    path = request.url.path
    if auth_enabled() and path.startswith("/api") and path not in _AUTH_EXEMPT_PATHS:
        if not _has_valid_session(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "请先登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    return await call_next(request)


class RequestCodeBody(BaseModel):
    """登录码申请。邮箱格式由 `org_service` 统一校验（不自带 email-validator 依赖）。"""

    email: str


class VerifyBody(BaseModel):
    token: str


class PointEditBody(BaseModel):
    text: str
    weight: float = 1.0
    is_required: bool = False


class PointsEditBody(BaseModel):
    points: list[PointEditBody]


class AnswerBody(BaseModel):
    answer: str


class SkipBody(BaseModel):
    reason: str


class SignalBody(BaseModel):
    training_id: int
    signal_type: str
    item_id: int | None = None
    item_key: str | None = None
    raw_text: str = ""


class StartAssessmentBody(BaseModel):
    training_id: int
    trigger: str = "manual"


class SubmitAssessmentBody(BaseModel):
    answers: dict[int, str] = {}


class ManualVerdictsBody(BaseModel):
    verdicts: dict[int, str] = {}


class DepartmentBody(BaseModel):
    name: str


class RosterBody(BaseModel):
    email: str
    department_id: int | None = None
    role: str = "member"
    status: str = "invited"


class AssignmentBody(BaseModel):
    title: str
    description: str = ""
    source_ids: list[int] = []
    acceptance: dict[str, Any] = {}
    target_type: str = ""
    target_value: Any = None
    due_date: str = ""


def current_viewer(tc_session: str | None = Cookie(default=None)) -> Viewer | None:
    """从 Cookie 解析身份；没有会话就是 `None`（个人版 profile 照常放行）。"""
    if not tc_session:
        return None
    return auth_service.viewer_from_session(tc_session)


def require_viewer(viewer: Viewer | None = Depends(current_viewer)) -> Viewer:
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return viewer


def _viewer_payload(viewer: Viewer) -> dict[str, Any]:
    """会话身份 + 基本信息（名称 / 注册邮箱，个人中心展示用；附加字段）。"""
    conn = queries.get_connection()
    try:
        row = conn.execute(
            "SELECT email, display_name FROM users WHERE id = ?", (int(viewer.user_id),)
        ).fetchone()
    finally:
        conn.close()
    return {
        "user_id": viewer.user_id,
        "org_id": viewer.org_id,
        "role": viewer.role.value,
        "department_ids": sorted(viewer.department_ids),
        "email": str(row["email"]) if row is not None and row["email"] else "",
        "display_name": str(row["display_name"]) if row is not None and row["display_name"] else "",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/mode")
def auth_mode() -> dict[str, bool]:
    """前端据此决定要不要显示登录页。

    **默认启用鉴权（企业版 profile）**：没登录就不能访问受保护接口，前端会先跳登录页。
    个人版（自用、没有账号体系）用 `TRAINER_AUTH=0` 或 `serve-api --personal` 关闭，
    此时 `viewer` 恒为 `None`，权限判定放行（ADR-0020 的 profile 语义）。
    """
    return {"auth_enabled": auth_enabled()}


@app.post("/api/auth/request-code", status_code=status.HTTP_202_ACCEPTED)
def request_code(body: RequestCodeBody) -> dict[str, str]:
    """申请登录码。

    **不在这里返回明文登录码**：那等于"知道邮箱就能登录"。
    第一版由管理员用 CLI（`issue-login`）签发并转交；接入邮件服务后改为系统发信。
    为避免枚举公司成员，无论邮箱是否在名单内都返回同一句话。
    """
    try:
        auth_service.issue_login_code(body.email)
    except PermissionError:
        logger.info("request-code: 邮箱不在名单内（对外不区分）")
    return {"message": "如果该邮箱在公司名单内，登录码已生成，请联系管理员获取"}


@app.post("/api/auth/verify")
def verify(body: VerifyBody, response: Response) -> dict[str, Any]:
    """用一次性登录码换会话：设置 HttpOnly Cookie。"""
    try:
        result = auth_service.verify_login_code(body.token)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response.set_cookie(
        SESSION_COOKIE,
        result["session"]["token"],
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=int(auth_service.SESSION_TTL_DAYS) * 24 * 3600,
        path="/",
    )
    return {"viewer": _viewer_payload(result["viewer"]), "expires_at": result["session"]["expires_at"]}


@app.post("/api/auth/logout")
def logout(response: Response, tc_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    if tc_session:
        auth_service.revoke_session(tc_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(viewer: Viewer = Depends(require_viewer)) -> dict[str, Any]:
    return _viewer_payload(viewer)


@app.get("/api/today")
def today(
    background_tasks: BackgroundTasks,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """今日训练（跨训练聚合）：汇总 + 任务明细 + 今日已作答（P1）。

    早早生成：今日任务的题目若未生成，交后台任务补齐（幂等，模型不可用时跳过）。
    """
    summary = plan_service.today_summary()
    visible_ids = _visible_training_ids(viewer)
    tasks = [
        _task_payload(task)
        for task in summary["tasks"]
        if visible_ids is None or task.training_id in visible_ids
    ]
    groups = [group for group in summary["groups"] if visible_ids is None or group["training_id"] in visible_ids]
    done = [
        _task_payload(task)
        for task in plan_service.done_today_tasks()
        if visible_ids is None or task.training_id in visible_ids
    ]
    for tid in sorted({task.training_id for task in summary["tasks"]}):
        background_tasks.add_task(plan_service.pregenerate_questions, tid)
    return {
        "viewer": _viewer_payload(viewer) if viewer else None,
        "count": len(tasks),
        "minutes": sum(task["planned_minutes"] for task in tasks),
        "groups": groups,
        "tasks": tasks,
        "done": done,
    }


def _visible_training_ids(viewer: Viewer | None) -> set[int] | None:
    """个人版（无 identity）返回 None 表示不限制；企业版按组织/归属过滤。"""
    if viewer is None:
        return None
    rows = [row.to_dict() for row in queries.list_trainings()]
    visible = {int(row["id"]) for row in visible_trainings(viewer, rows)}
    visible |= set(queries.list_shared_training_ids(viewer.user_id))
    return visible


def _task_payload(task: Any) -> dict[str, Any]:
    """任务明细。**参考答案只在已判分后返回**，避免把答案提前送给用户。

    客观题（choice/fill）附带 question_type 与选项数组，供前端渲染可选项；
    选项来自出题时固化的 plan_items 字段，is_correct 字段不下发给前端。
    """
    graded = bool(task.verdict)
    meta = plan_service.question_meta(task.plan_id)
    options = json.loads(meta["options"]) if meta["options"] else None
    if isinstance(options, list) and options:
        options = [
            {k: v for k, v in option.items() if k != "is_correct"} for option in options if isinstance(option, dict)
        ]
    else:
        options = None
    return {
        "plan_id": task.plan_id,
        "training_id": task.training_id,
        "training_topic": task.training_topic,
        "item_key": task.item_key,
        "title": task.title,
        "knowledge_point": task.knowledge_point,
        "item_type": task.item_type,
        "question_type": meta["question_type"],
        "options": options,
        "round_index": task.round_index,
        "planned_minutes": task.planned_minutes,
        "due_date": task.due_date.isoformat(),
        "original_date": task.original_date.isoformat(),
        "is_overdue": task.is_overdue(plan_service.local_today()),
        "question": task.question,
        "reference_answer": task.reference_answer if graded else "",
        "answer_text": task.answer_text,
        "verdict": task.verdict,
        "status": task.status,
    }


def _training_payload(training: Any) -> dict[str, Any]:
    data = training.to_dict()
    return {
        "id": data["id"],
        "topic": data.get("topic") or "",
        "status": data.get("status") or "draft",
        "org_id": data.get("org_id") or 1,
        "owner_user_id": data.get("owner_user_id"),
        "visibility": data.get("visibility") or "private",
        "schedule_mode": data.get("schedule_mode") or "legacy_v21",
        "baseline_score": data.get("baseline_score") or 0,
        "created_at": data.get("created_at"),
        "last_active_at": data.get("last_active_at"),
    }


def _load_training_for(viewer: Viewer | None, training_id: int) -> Any:
    training = queries.get_training(int(training_id))
    if training is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练不存在")
    shared_uids = queries.list_training_shared_user_ids(int(training_id))
    if not can_view_training(viewer, training.to_dict(), shared_uids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该训练")
    return training


@app.get("/api/dashboard")
def dashboard(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """跨训练进度仪表盘（第一版 Streamlit 首页的 Vue 迁移）。"""
    snap = compute_home_dashboard()
    visible_ids = _visible_training_ids(viewer)
    trainings = []
    for p in snap.trainings:
        if visible_ids is not None and p.training_id not in visible_ids:
            continue
        trainings.append(
            {
                "training_id": p.training_id,
                "topic": p.topic,
                "status": str(p.status.value) if hasattr(p.status, "value") else str(p.status),
                "baseline_score": p.baseline_score,
                "baseline_level": str(p.baseline_level),
                "consecutive_days": p.consecutive_days,
                "days_since_creation": p.days_since_creation,
                "today_completion": p.today_completion,
                "today_completed": p.today_completed,
                "today_total": p.today_total,
                "last_active_at": p.last_active_at.isoformat() if p.last_active_at else None,
                "current_week": p.current_week,
            }
        )
    return {
        "trainings": trainings,
        "total_active": snap.total_active,
        "total_all": snap.total_all,
        "avg_baseline": snap.avg_baseline,
    }


@app.get("/api/trainings")
def list_trainings_endpoint(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    rows = [_training_payload(training) for training in queries.list_trainings()]
    if viewer is not None:
        shares_by_training = _shares_grouped("training_shares", "training_id")
        rows = [
            row
            for row in rows
            if can_view_training(viewer, row, shares_by_training.get(int(row["id"])))
        ]
    return {"trainings": rows}


@app.get("/api/trainings/{training_id}/path")
def training_path(training_id: int, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _load_training_for(viewer, training_id)
    path = path_service.load_path(int(training_id))
    if path is None:
        return {"path": None, "stages": [], "progress": None}
    stages = []
    for stage in path_service.load_stages(path.id):
        items = [
            {
                "id": item.id,
                "ordinal": item.ordinal,
                "title": item.title,
                "item_type": item.item_type,
                "difficulty_tier": item.difficulty_tier,
                "knowledge_point": item.knowledge_point,
                "status": item.status,
            }
            for item in path_service.load_items(stage.id)
        ]
        stages.append(
            {
                "id": stage.id,
                "ordinal": stage.ordinal,
                "title": stage.title,
                "goal": stage.goal,
                "status": stage.status,
                "estimated_minutes": stage.estimated_minutes,
                "items": items,
            }
        )
    report = mastery_service.evaluate(int(training_id))
    return {
        "path": {
            "id": path.id,
            "version": path.version,
            "status": path.status,
            "mode": path.mode,
            "horizon_weeks": path.horizon_weeks,
            "weekly_frequency": path.weekly_frequency,
            "daily_budget_minutes": path.daily_budget_minutes,
            "budget_minutes": path.budget_minutes,
            "planned_minutes": path.planned_minutes,
        },
        "stages": stages,
        "progress": {
            "total_items": report.total_items,
            "passed_items": report.passed_items,
            "practiced_items": report.practiced_items,
            "coverage_done": report.coverage_done,
            "quiz_passed": report.quiz_passed,
            "mastered": report.mastered,
            "reason": report.reason,
        },
    }


class VisibilityBody(BaseModel):
    visibility: str  # private / specific / public
    shared_user_ids: list[int] = []
    shared_emails: list[str] = []  # 指定成员按邮箱输入，服务端解析为本组织 user_id
    confirm_source_ids: list[int] = []  # share-gate：目标为 public 时的文档门禁确认集


@app.put("/api/trainings/{training_id}/visibility")
def set_training_visibility(
    training_id: int, body: VisibilityBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """设置训练可见性（仅 owner 或组织管理员）。"""
    training = _load_training_for(viewer, training_id)
    if viewer is not None:
        if int(training.owner_user_id or 0) != int(viewer.user_id) and not can(
            viewer.role, "publish_assignment"
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有创建者可以修改可见性")
    if body.visibility not in ("private", "specific", "public"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="visibility 取值非法")
    if body.visibility == "public" and viewer is not None:
        # share-gate（design D4）：训练公开 = 受众级 public，引用文档不达标需逐件确认
        from src.services import share_gate_service

        try:
            share_gate_service.confirm_and_execute(
                int(training_id),
                "publish",
                int(viewer.user_id),
                confirm_source_ids=body.confirm_source_ids,
                conn=None,
            )
        except share_gate_service.GateIncompleteError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "message": str(exc),
                "blocked": exc.blocked,
                "action": "publish",
            }) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        # publish 动作已在 confirm 事务里把训练置为 public 并升级文档，直接返回
        return {"ok": True, "visibility": "public", "shared_user_ids": [], "upgraded": True}
    if body.visibility == "specific":
        org_for_check = int(viewer.org_id) if viewer is not None and viewer.org_id is not None else None
        if org_for_check is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号没有组织成员资格，无法使用指定人分享")
        resolved_uids = set(body.shared_user_ids) | set(
            _resolve_shared_uids(org_for_check, body.shared_emails)
        )
        for uid in sorted(resolved_uids):
            member = queries.get_connection().execute(
                "SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ? AND status = 'active'",
                (int(uid), org_for_check),
            ).fetchone()
            if member is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"用户 {uid} 不是本组织成员")
    else:
        resolved_uids = set()
    conn = queries.get_connection()
    try:
        queries.update_training(training_id, visibility=body.visibility, conn=conn)
        conn.execute("DELETE FROM training_shares WHERE training_id = ?", (training_id,))
        if body.visibility == "specific":
            for uid in sorted(resolved_uids):
                conn.execute(
                    "INSERT OR IGNORE INTO training_shares (training_id, user_id, created_by, created_at) "
                    "VALUES (?, ?, ?, 'now')",
                    (training_id, int(uid), int(viewer.user_id or 0)),
                )
        conn.commit()
    finally:
        conn.close()
    shared = (
        queries.list_training_shared_user_ids(training_id) if body.visibility == "specific" else []
    )
    return {"ok": True, "visibility": body.visibility, "shared_user_ids": shared}


class SourceVisibilityBody(BaseModel):
    visibility: str
    shared_user_ids: list[int] = []
    shared_emails: list[str] = []  # 同训练可见性：指定成员按邮箱输入


@app.put("/api/trainings/{training_id}/sources/{source_id}/visibility")
def set_source_visibility(
    training_id: int,
    source_id: int,
    body: SourceVisibilityBody,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """设置单条资料的可见性（资料归属训练，owner 或组织管理员）。"""
    training = _load_training_for(viewer, training_id)
    if viewer is not None:
        if int(training.owner_user_id or 0) != int(viewer.user_id) and not can(
            viewer.role, "publish_assignment"
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有创建者可以修改可见性")
    if body.visibility not in ("private", "specific", "public"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="visibility 取值非法")
    resolved_uids: set[int] = set(body.shared_user_ids)
    if body.visibility == "specific":
        org_for_check = int(viewer.org_id) if viewer is not None and viewer.org_id is not None else None
        if org_for_check is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号没有组织成员资格，无法使用指定人分享")
        resolved_uids |= set(_resolve_shared_uids(org_for_check, body.shared_emails))
        for uid in sorted(resolved_uids):
            member = queries.get_connection().execute(
                "SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ? AND status = 'active'",
                (int(uid), org_for_check),
            ).fetchone()
            if member is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"用户 {uid} 不是本组织成员")
    conn = queries.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM sources WHERE id = ? AND training_id = ?",
            (int(source_id), int(training_id)),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        conn.execute(
            "UPDATE sources SET scope = ? WHERE id = ?",
            (body.visibility, int(source_id)),
        )
        conn.execute("DELETE FROM source_shares WHERE source_id = ?", (int(source_id),))
        if body.visibility == "specific":
            for uid in sorted(resolved_uids):
                conn.execute(
                    "INSERT OR IGNORE INTO source_shares (source_id, user_id, created_by, created_at) "
                    "VALUES (?, ?, ?, 'now')",
                    (int(source_id), int(uid), int(viewer.user_id or 0)),
                )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "visibility": body.visibility}


@app.post("/api/trainings/{training_id}/questions/pregenerate")
def pregenerate_training_questions(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """手动触发：把该训练全部未生成轮次的题目提前生成（同步执行）。"""
    _load_training_for(viewer, training_id)
    return plan_service.pregenerate_questions(int(training_id))


@app.delete("/api/trainings/{training_id}")
def delete_training_view(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, bool]:
    """删除训练及其全部关联数据（不可恢复；仅创建者）。"""
    training = _load_training_for(viewer, training_id)
    if viewer is not None:
        if training.owner_user_id in (None, "") or int(training.owner_user_id) != int(viewer.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有创建者可以删除训练")
    return {"ok": queries.delete_training(int(training_id))}


@app.post("/api/trainings/{training_id}/archive")
def archive_training_view(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """归档已完成的训练（仅 owner；仅已达标状态可归档）。"""
    training = _load_training_for(viewer, training_id)
    if viewer is not None:
        if training.owner_user_id in (None, "") or int(training.owner_user_id) != int(viewer.user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有创建者可以归档")
    if training.status != "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只有已达标的训练可以归档")
    queries.update_training(int(training_id), status="archived")
    return {"ok": True, "status": "archived"}


def _training_owner(training_id: int | None) -> int | None:
    if training_id in (None, ""):
        return None
    training = queries.get_training(int(training_id))
    owner = training.owner_user_id if training is not None else None
    return int(owner) if owner not in (None, "") else None


def _shares_grouped(table: str, key_col: str) -> dict[int, list[int]]:
    """读指定成员授权表，按 key 列分组为 ``{key_id: [user_id, ...]}``。"""
    conn = queries.get_connection()
    try:
        rows = conn.execute(f"SELECT {key_col} AS key_id, user_id FROM {table}").fetchall()
    finally:
        conn.close()
    grouped: dict[int, list[int]] = {}
    for row in rows:
        grouped.setdefault(int(row["key_id"]), []).append(int(row["user_id"]))
    return grouped


def _resolve_shared_uids(org_id: int, emails: list[str]) -> list[int]:
    """把「指定人」的邮箱解析为本组织在册 user_id；不存在或不在本组织 → 400。

    前端指定成员用邮箱输入（个人用户无成员列表权限），服务端统一解析校验。
    """
    normalized = [email.strip().lower() for email in emails if email and email.strip()]
    if not normalized:
        return []
    conn = queries.get_connection()
    found: dict[str, int] = {}
    try:
        for email in normalized:
            row = conn.execute(
                "SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE LOWER(u.email) = ? AND m.org_id = ? AND m.status = 'active'",
                (email, int(org_id)),
            ).fetchone()
            if row is not None:
                found[email] = int(row["id"])
    finally:
        conn.close()
    missing = [email for email in normalized if email not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="以下邮箱不是本组织成员：" + "、".join(missing),
        )
    return list(found.values())


@app.get("/api/sources/overview")
def sources_overview_view(
    viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """资料总览：按内容指纹聚合，回答「这份资料被几个训练计划引用」。"""
    visible_ids = _visible_training_ids(viewer)
    return {"sources": source_service.sources_overview(visible_ids)}


@app.get("/api/trainings/{training_id}/questions")
def training_questions(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """题库总览：该训练的全部题目与状态（不含参考答案，防背题）。"""
    _load_training_for(viewer, training_id)
    rows = plan_service.questions_overview(int(training_id))
    return {"count": len(rows), "questions": rows}


@app.post("/api/trainings/{training_id}/plan/regenerate")
def regenerate_plan(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """补齐缺失的训练轮次（幂等）：路径重生成后新增的训练项，由此补入计划。"""
    _load_training_for(viewer, training_id)
    summary = plan_service.generate_plan(int(training_id))
    rounds = plan_service.training_plan_items(int(training_id))
    return {"ok": True, "count": len(rounds), "created": summary.created}


@app.get("/api/trainings/{training_id}/plan-items")
def training_plan_items(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """完整训练计划：全部训练轮次（含未到期），按到期日排序——支持查看全貌与提前练。

    任务动作端点（answer/practice-only/skip）不设到期门，未来轮次可直接提交作答。
    """
    _load_training_for(viewer, training_id)
    tasks = plan_service.training_plan_items(int(training_id))
    return {
        "count": len(tasks),
        "items": [_task_payload(task) for task in tasks],
    }


@app.get("/api/trainings/{training_id}/sources")
def training_sources(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    _load_training_for(viewer, training_id)
    rows = [source.to_dict() for source in source_service.list_sources(int(training_id))]
    if viewer is not None:
        shares_by_source = _shares_grouped("source_shares", "source_id")
        rows = [
            {**row, "owner_user_id": _training_owner(row.get("training_id"))}
            for row in rows
        ]
        rows = [
            row for row in rows if can_view_source(viewer, row, shares_by_source.get(int(row["id"])))
        ]
    training = queries.get_training(int(training_id))
    return {
        "training_visibility": getattr(training, "visibility", None) or "private",
        "training_shared_user_ids": queries.list_training_shared_user_ids(int(training_id)),
        "sources": [
            {
                "id": row["id"],
                "type": row.get("type"),
                "title": row.get("title"),
                "scope": row.get("scope"),
                "department_id": row.get("department_id"),
                "enabled": row.get("enabled"),
                "parse_status": row.get("parse_status"),
                "origin_url": row.get("origin_url"),
                "imported_at": row.get("imported_at"),
                "owner_user_id": row.get("owner_user_id"),
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------- P2 写操作


def _find_task(plan_id: int) -> Any:
    for task in plan_service.today_tasks():
        if task.plan_id == int(plan_id):
            return task
    for training in queries.list_trainings():
        for task in plan_service.today_tasks(training_id=int(training.id)):
            if task.plan_id == int(plan_id):
                return task
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到该训练项")


def _guard_task(viewer: Viewer | None, plan_id: int) -> Any:
    """写操作前的可见性校验：先找到任务，再确认它属于可见训练。"""
    task = _find_task(plan_id)
    visible_ids = _visible_training_ids(viewer)
    if visible_ids is not None and task.training_id not in visible_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该训练")
    return task


def _guard_training(viewer: Viewer | None, training_id: int) -> None:
    visible_ids = _visible_training_ids(viewer)
    if visible_ids is not None and int(training_id) not in visible_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该训练")


@app.post("/api/plan-items/{plan_id}/question")
def plan_item_question(
    plan_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """按需生成这道题的题干与参考答案（懒生成，避免打开页面就批量烧 token）。"""
    task = _guard_task(viewer, plan_id)
    try:
        question = answer_service.ensure_question(int(plan_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    options = parse_options(question.get("options"))
    if options:
        options = [
            {k: v for k, v in option.items() if k != "is_correct"} for option in options
        ]
    else:
        options = None
    return {
        "question": question["question"],
        "reference_answer": question.get("reference_answer") or "",
        "source": question.get("source"),
        "question_type": question.get("question_type"),
        "options": options,
        "points": question.get("points") or [],
    }


@app.patch("/api/plan-items/{plan_id}/points")
def edit_plan_item_points(
    plan_id: int, body: PointsEditBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """编辑该题要点（首判前可修 rubric；已判分 409 锁定）。grading-rubric-hardening。"""
    _guard_task(viewer, plan_id)
    try:
        points = answer_service.update_points(int(plan_id), [p.model_dump() for p in body.points])
    except answer_service.PointsLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "points": points}


@app.post("/api/plan-items/{plan_id}/answer")
def submit_answer(
    plan_id: int, body: AnswerBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """提交作答 → **系统判分**；判分不可用时如实返回 graded=false，不伪造对错。"""
    _guard_task(viewer, plan_id)
    try:
        return answer_service.submit_answer(int(plan_id), body.answer)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/plan-items/{plan_id}/practice-only")
def practice_only(
    plan_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, bool]:
    """只标记"练过"（不计入客观表现）。"""
    _guard_task(viewer, plan_id)
    answer_service.mark_practiced_only(int(plan_id))
    return {"ok": True}


@app.post("/api/plan-items/{plan_id}/explanation")
def plan_item_explanation(
    plan_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """题目级深度解析：对比该题历史作答，指出重复错误与改进动作。

    与出题/作答不同，解析对已判分与未判分的任务都可用（未判分时按"本次作答"解析）。
    """
    from src.db.connection import transaction
    from src.services import explanation_service

    with transaction() as active:
        row = active.execute(
            "SELECT training_id FROM plan_items WHERE id = ?", (int(plan_id),)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到该训练项")
    _guard_training(viewer, int(row["training_id"]))
    try:
        result = explanation_service.generate_item_explanation(int(row["training_id"]), int(plan_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(result.get("error") or "解析生成失败"),
        )
    return result


@app.post("/api/plan-items/{plan_id}/skip")
def skip_plan_item(
    plan_id: int, body: SkipBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, bool]:
    """跳过一项（必须给原因，且不计入完成）。"""
    _guard_task(viewer, plan_id)
    try:
        plan_service.skip_task(int(plan_id), body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/signals")
def submit_signal(
    body: SignalBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """四失反馈：客观口径来自逐次作答（<3 次作答算数据不足，只做轻微调整）。"""
    _guard_training(viewer, body.training_id)
    objective = attempt_service.objective_for_training(body.training_id)
    try:
        decision = signal_service.process_signal(
            body.training_id,
            body.signal_type,
            item_id=body.item_id,
            item_key=body.item_key,
            objective=objective,
            raw_text=body.raw_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "signal_type": decision.signal_type,
        "action": decision.action,
        "applied": decision.applied,
        "blocked_reason": decision.blocked_reason,
        "message": decision.message,
        "objective": objective,
    }


@app.get("/api/trainings/{training_id}/learner-model")
def training_learner_model(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """学习者模型（只读，未来对话 agent 的记忆工具面）：掌握度 + 读时衰减 + 活跃误解。

    change layered-learner-memory——纯增量，不改变任何现有判分/解析链路。
    """
    _load_training_for(viewer, training_id)
    from src.services import learner_service

    rows = learner_service.get_learner_model(int(training_id))
    return {
        "training_id": int(training_id),
        "count": len(rows),
        "weak_count": sum(1 for row in rows if row["weak"]),
        "items": rows,
    }


@app.post("/api/trainings/{training_id}/learner-model/rebuild")
def rebuild_learner_model(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """从 practice_attempts 全量重放重建学习者模型（部署后回填存量；幂等）。"""
    _load_training_for(viewer, training_id)
    from src.services import learner_service

    return learner_service.rebuild(int(training_id))


@app.get("/api/trainings/{training_id}/quiz")
def quiz_state(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """测验状态：是否到期、可抽多少题、最近一次结果。"""
    _guard_training(viewer, training_id)
    pending = quiz_service.pending_quiz_plan(int(training_id))
    pool = quiz_service.question_pool(int(training_id))
    latest = quiz_service.latest_assessment(int(training_id))
    return {
        "pending": bool(pending),
        "plan_id": int(pending["id"]) if pending else None,
        "pool_size": len(pool),
        "latest": (
            {
                "id": latest.id,
                "status": latest.status,
                "score": latest.score,
                "passed": bool(latest.passed) if latest.passed is not None else None,
            }
            if latest is not None
            else None
        ),
    }


@app.post("/api/assessments")
def start_assessment(
    body: StartAssessmentBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """开始测验：题目只从**冷却期已过**的题库里抽（ADR-0016）。"""
    _guard_training(viewer, body.training_id)
    pending = quiz_service.pending_quiz_plan(body.training_id)
    try:
        assessment = quiz_service.start_assessment(
            body.training_id,
            trigger=body.trigger,
            plan_id=int(pending["id"]) if pending else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "assessment_id": assessment.id,
        "question_count": assessment.question_count,
        "items": [
            {
                "item_id": item.id,
                "ordinal": item.ordinal,
                "question": item.question,
                "is_variant": bool(item.is_variant),
            }
            for item in quiz_service.load_items(assessment.id)
        ],
    }


@app.post("/api/assessments/{assessment_id}/submit")
def submit_assessment(
    assessment_id: int,
    body: SubmitAssessmentBody,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """提交答卷：优先 AI 判分；不可用时返回需自评的题目。"""
    assessment = quiz_service.load_assessment(int(assessment_id))
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测验不存在")
    _guard_training(viewer, assessment.training_id)
    quiz_service.save_answers(int(assessment_id), body.answers)
    if quiz_service.grade_with_llm(int(assessment_id)):
        result = quiz_service.finish_assessment(int(assessment_id), graded_by="llm")
        return {"graded_by": "llm", "needs_manual": False, **_quiz_result_payload(result)}
    return {
        "graded_by": "unavailable",
        "needs_manual": True,
        "items": [
            {
                "item_id": item.id,
                "ordinal": item.ordinal,
                "question": item.question,
                "reference_answer": item.reference_answer,
                "user_answer": item.user_answer,
            }
            for item in quiz_service.load_items(int(assessment_id))
        ],
    }


@app.post("/api/assessments/{assessment_id}/manual")
def grade_assessment_manually(
    assessment_id: int,
    body: ManualVerdictsBody,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """AI 判分不可用时的自评兜底（结果标注 `graded_by=self`）。"""
    assessment = quiz_service.load_assessment(int(assessment_id))
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测验不存在")
    _guard_training(viewer, assessment.training_id)
    quiz_service.save_manual_verdicts(int(assessment_id), body.verdicts)
    result = quiz_service.finish_assessment(int(assessment_id), graded_by="self")
    return {"graded_by": "self", "needs_manual": False, **_quiz_result_payload(result)}


def _quiz_result_payload(result: quiz_service.QuizResult) -> dict[str, Any]:
    return {
        "assessment_id": result.assessment_id,
        "question_count": result.question_count,
        "score": result.score,
        "passed": result.passed,
        "extra_rounds": result.extra_rounds,
        "failed_items": result.failed_items,
        # 终测（user-defined-training-plan）：未通过时追加的会话周期信息（None=非终测/未追加）
        "cycle_appended": result.cycle_appended,
    }


#: 前端构建产物目录（`cd web && npm run build`）
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


# ---------------------------------------------------------------- P3 管理端


def _require_admin_viewer(viewer: Viewer | None) -> Viewer:
    """管理端必须登录（个人版没有身份时不允许操作组织数据）。"""
    if viewer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="管理功能需要登录"
        )
    return viewer


def _assert_action(viewer: Viewer, action: Any) -> None:
    from src.core.permissions import assert_can

    try:
        assert_can(viewer, action)
    except Exception as exc:  # PermissionDenied
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


class ShareLinkBody(BaseModel):
    """分享链接参数（share-gate）：open_level 开放级别 + 可选一次性确认集。"""

    open_level: str = "org"  # org | anyone
    confirm_source_ids: list[int] = []


@app.post("/api/trainings/{training_id}/share/link")
def create_share_link(
    training_id: int,
    body: ShareLinkBody | None = None,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """生成/返回该训练的分享链接（幂等；仅 owner 或组织管理员）。

    share-gate：未过文档门禁且确认集不齐 → 409 带缺失清单；确认集齐全 →
    升级与生成同一事务完成（一步式，design D4）。
    """
    training = _load_training_for(viewer, training_id)
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要登录")
    if int(training.owner_user_id or 0) != int(viewer.user_id) and not can(
        viewer.role, "publish_assignment"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有训练创建者可以分享")
    payload = body or ShareLinkBody()
    if payload.open_level not in ("org", "anyone"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="open_level 取值非法")
    from src.services import share_gate_service, training_clone_service

    action = "link_anyone" if payload.open_level == "anyone" else "link_org"
    try:
        result = share_gate_service.confirm_and_execute(
            int(training_id),
            action,
            int(viewer.user_id),
            open_level=payload.open_level,
            confirm_source_ids=payload.confirm_source_ids,
        )
    except share_gate_service.GateIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "message": str(exc),
            "blocked": exc.blocked,
            "action": action,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "token": result["token"],
        "created": result["created"],
        "open_level": payload.open_level,
        "upgraded": result.get("upgraded", []),
        "url": f"/share/{result['token']}",
    }


@app.get("/api/share/{token}")
def share_preview(token: str, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """分享链接预览：只含计划结构与验收标准（不含题库/参考答案/作答数据）。"""
    from src.services.training_clone_service import get_share_preview

    try:
        return get_share_preview(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/api/share/{token}/pull")
def share_pull(token: str, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """拉取为独立副本（同组织成员；幂等）。"""
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    from src.services.training_clone_service import pull_by_token

    try:
        result = pull_by_token(token, int(viewer.user_id))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result


class ShareMembersBody(BaseModel):
    user_ids: list[int]
    confirm_source_ids: list[int] = []  # share-gate：文档门禁一次性确认集


@app.post("/api/trainings/{training_id}/share/members")
def share_to_members(
    training_id: int, body: ShareMembersBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """把计划（连题库）直接复制推送给指定成员（分享即复制）。

    share-gate：推送受众级 = specific(目标成员)；引用文档不达标且确认集不齐 →
    409 带清单；齐全则升级 + 推送同一事务完成（design D4）。
    """
    training = _load_training_for(viewer, training_id)
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要登录")
    if int(training.owner_user_id or 0) != int(viewer.user_id) and not can(
        viewer.role, "publish_assignment"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有训练创建者可以推送")
    from src.services import share_gate_service

    if not body.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少选择一个推送目标")
    try:
        result = share_gate_service.confirm_and_execute(
            int(training_id),
            "push",
            int(viewer.user_id),
            target_uids=body.user_ids,
            confirm_source_ids=body.confirm_source_ids,
        )
    except share_gate_service.GateIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "message": str(exc),
            "blocked": exc.blocked,
            "action": "push",
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "delivered": result.get("delivered", []),
        "skipped": result.get("skipped", []),
        "upgraded": result.get("upgraded", []),
    }


class ShareGateBody(BaseModel):
    """门禁两步协议（share-gate design D3）：gate 查询 / confirm 事务共用参数。"""

    action: str  # publish | link_org | link_anyone | push
    target_emails: list[str] = []  # 仅 push：复用邮箱解析
    user_ids: list[int] = []  # 仅 push：也可直接给 user_id
    open_level: str | None = None  # link_* 时冗余校验
    confirm_source_ids: list[int] = []  # confirm 专用


def _gate_targets(training_id: int, body: ShareGateBody, viewer: Viewer) -> list[int]:
    """解析 push 目标：user_ids 直传或 target_emails 邮箱解析（复用 content-visibility 规则）。"""
    if body.user_ids:
        return [int(uid) for uid in body.user_ids]
    training = queries.get_training(int(training_id))
    org_id = int(training.org_id) if training is not None and training.org_id else (
        int(viewer.org_id) if viewer is not None and viewer.org_id else None
    )
    from src.services import share_gate_service

    try:
        return share_gate_service.resolve_member_uids(org_id, body.target_emails)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/trainings/{training_id}/share/gate")
def share_gate_query(
    training_id: int, body: ShareGateBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """门禁第一步（只读）：返回不达标文档清单；不产生任何副作用。"""
    training = _load_training_for(viewer, training_id)
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要登录")
    from src.services import share_gate_service

    try:
        targets = _gate_targets(training_id, body, viewer) if body.action == "push" else []
        return share_gate_service.gate_check(int(training_id), body.action, target_uids=targets)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/trainings/{training_id}/share/confirm")
def share_gate_confirm(
    training_id: int, body: ShareGateBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """门禁第二步（单事务）：定向升级确认的文档 + 执行分享动作，无部分生效。"""
    training = _load_training_for(viewer, training_id)
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要登录")
    if int(training.owner_user_id or 0) != int(viewer.user_id) and not can(
        viewer.role, "publish_assignment"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有训练创建者可以分享")
    from src.services import share_gate_service

    try:
        targets = _gate_targets(training_id, body, viewer) if body.action == "push" else []
        result = share_gate_service.confirm_and_execute(
            int(training_id),
            body.action,
            int(viewer.user_id),
            target_uids=targets,
            open_level=body.open_level,
            confirm_source_ids=body.confirm_source_ids,
        )
    except share_gate_service.GateIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "message": str(exc),
            "blocked": exc.blocked,
            "action": body.action,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    payload = {"upgraded": result.get("upgraded", [])}
    if body.action in ("link_org", "link_anyone"):
        payload.update(
            {
                "token": result.get("token"),
                "created": result.get("created"),
                "open_level": body.open_level or ("anyone" if body.action == "link_anyone" else "org"),
                "url": f"/share/{result.get('token')}",
            }
        )
    elif body.action == "push":
        payload.update(
            {
                "delivered": result.get("delivered", []),
                "skipped": result.get("skipped", []),
            }
        )
    else:
        payload["ok"] = True
        payload["visibility"] = "public"
    return payload


@app.get("/api/trainings/{training_id}/review/weekly")
def review_weekly_prepare(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """周复盘准备：本周指标 + LLM 校准建议（LLM 不可用时启发式兜底；不落库）。"""
    _load_training_for(viewer, training_id)
    outcome = review_service.prepare_weekly_review(int(training_id))
    return {
        "metrics": outcome.metrics.to_plain_dict(),
        "suggestion": outcome.suggestion.to_dict(),
        "applied": outcome.applied,
    }


@app.post("/api/trainings/{training_id}/review/apply")
def review_weekly_apply(
    training_id: int,
    body: dict[str, Any],
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """应用周复盘建议：持久化基线/排期/资料调整并归档。"""
    _load_training_for(viewer, training_id)
    raw = body.get("suggestion") or {}
    suggestion = CalibrationSuggestion(
        baseline_score_delta=float(raw.get("baseline_score_delta") or 0.0),
        schedule_adjustment=dict(raw.get("schedule_adjustment") or {}),
        material_recommendations=list(raw.get("material_recommendations") or []),
        reward_refresh=str(raw.get("reward_refresh") or ""),
        next_week_focus=str(raw.get("next_week_focus") or ""),
        raw=dict(raw.get("raw") or {}),
        fallback_used=bool(raw.get("fallback_used") or False),
    )
    outcome = review_service.apply_weekly_review(int(training_id), suggestion)
    return {
        "metrics": outcome.metrics.to_plain_dict(),
        "suggestion": outcome.suggestion.to_dict(),
        "applied": outcome.applied,
    }


@app.post("/api/trainings/{training_id}/review/skip")
def review_weekly_skip(
    training_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """跳过本周复盘：归档快照但不做任何调整。"""
    _load_training_for(viewer, training_id)
    outcome = review_service.skip_weekly_review(int(training_id))
    return {
        "metrics": outcome.metrics.to_plain_dict(),
        "suggestion": outcome.suggestion.to_dict(),
        "applied": outcome.applied,
    }


@app.get("/api/org/departments")
def list_departments(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    from src.core.permissions import Action
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    rows = org_service.list_departments(current.org_id)
    return {"departments": rows}


@app.post("/api/org/departments")
def create_department(
    body: DepartmentBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    from src.core.permissions import Action
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    try:
        return org_service.create_department(body.name.strip(), org_id=current.org_id)
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/org/roster")
def list_roster(
    department_id: int | None = None, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    from src.core.permissions import Action, can_manage_department
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    rows = org_service.list_roster(current.org_id)
    # 部门主管只看自己部门的名单（ADR-0022 配套硬规则）
    rows = [
        row
        for row in rows
        if row.get("department_id") is None
        or can_manage_department(current, int(row["department_id"]))
    ]
    if department_id is not None:
        rows = [row for row in rows if int(row.get("department_id") or 0) == int(department_id)]
    return {"roster": rows}


@app.post("/api/org/roster")
def upsert_roster(
    body: RosterBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    from src.core.permissions import Action, Role, can_manage_department
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    # 部门主管只能往自己部门加人，且只能给员工角色（不能自己造管理员）
    if current.role is Role.ADMIN:
        if body.department_id is None or not can_manage_department(current, body.department_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本部门")
        if body.role != Role.MEMBER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="部门主管只能添加员工"
            )
    try:
        return org_service.upsert_roster_entry(
            body.email,
            org_id=current.org_id,
            department_id=body.department_id,
            role=body.role,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/org/roster/{email}/issue-login")
def issue_login_for(
    email: str, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """签发一次性登录码。

    这是**唯一返回明文登录码**的地方：只有管理者能调，且部门主管只能给自己部门的人签发。
    """
    from src.core.permissions import Action, can_manage_department
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    entry = org_service.match_roster(email, org_id=current.org_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该邮箱不在名单里")
    department_id = entry.get("department_id")
    if department_id is not None and not can_manage_department(current, int(department_id)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本部门")
    issued = auth_service.issue_login_code(email, org_id=current.org_id)
    return {"email": issued["email"], "token": issued["token"], "expires_at": issued["expires_at"]}


@app.get("/api/org/members")
def list_org_members(
    department_id: int | None = None, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    from src.core.permissions import Action, Role
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    if current.role is Role.ADMIN:
        # 主管只能看本部门成员；未指定部门时取他第一个部门
        target = department_id or next(iter(sorted(current.department_ids)), None)
        if target is None:
            return {"members": []}
        if int(target) not in current.department_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能查看本部门")
        return {"members": org_service.list_members(current.org_id, department_id=int(target))}
    return {"members": org_service.list_members(current.org_id, department_id=department_id)}


@app.get("/api/org/summary")
def org_summary(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """组织概览：人数、部门数、训练数与达标数（企业版最常用的四个数）。"""
    from src.core.permissions import Action
    from src.services import org_service

    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    members = org_service.list_members(current.org_id)
    departments = org_service.list_departments(current.org_id)
    rows = [row.to_dict() for row in queries.list_trainings()]
    visible = visible_trainings(current, rows)
    mastered = 0
    for row in visible:
        report = mastery_service.training_progress(int(row["id"]))
        if report.mastered:
            mastered += 1
    return {
        "members": len(members),
        "departments": len(departments),
        "trainings": len(visible),
        "mastered_trainings": mastered,
    }


@app.get("/api/org/sources")
def org_sources(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """组织公共资料（发任务时选「资料范围」用；只列 `org_shared` 且解析成功的）。"""
    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    rows = [row.to_dict() for row in queries.list_trainings()]
    options: list[dict[str, Any]] = []
    for training in visible_trainings(current, rows):
        for source in source_service.list_sources(int(training["id"])):
            data = source.to_dict()
            if data.get("scope") != "org_shared" or data.get("parse_status") != "ok":
                continue
            options.append(
                {
                    "id": data["id"],
                    "title": data.get("title"),
                    "training_id": training["id"],
                    "training_topic": training.get("topic"),
                }
            )
    return {"sources": options}


# ---------------------------------------------------------------- 培训任务分发（5.x）


def _manager_scope(viewer: Viewer) -> set[int]:
    """主管能管哪些部门（组织管理员用不到：空集合表示"全部"）。"""
    if viewer.role is Role.ORG_ADMIN:
        return set()
    return set(viewer.department_ids)


@app.get("/api/assignments")
def list_assignments(viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    """管理端：本组织任务列表（部门主管只看与自己部门相关的）。"""
    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    rows = assignment_service.list_assignments(current.org_id)
    if current.role is not Role.ORG_ADMIN:
        scope = {str(value) for value in _manager_scope(current)}
        rows = [
            row
            for row in rows
            if str(row.get("target_value")) in scope or row.get("created_by") == current.user_id
        ]
    return {"assignments": rows}


@app.post("/api/assignments")
def create_assignment(
    body: AssignmentBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """创建任务草案：四要素缺一不可；部门主管只能发给自己部门。"""
    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    if current.role is Role.ADMIN:
        if body.target_type != "department" or body.target_value in (None, ""):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="主管只能按本部门发布任务"
            )
        if int(body.target_value) not in current.department_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="只能发布给本部门"
            )
    try:
        return assignment_service.create_assignment(
            current.org_id,
            title=body.title,
            source_ids=body.source_ids,
            acceptance=body.acceptance,
            target_type=body.target_type,
            target_value=body.target_value,
            due_date=body.due_date,
            description=body.description,
            created_by=current.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _load_assignment_for(viewer: Viewer, assignment_id: int) -> dict[str, Any]:
    rows = assignment_service.list_assignments(viewer.org_id or -1)
    match = next((row for row in rows if int(row["id"]) == int(assignment_id)), None)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if viewer.role is not Role.ORG_ADMIN:
        scope = {str(value) for value in viewer.department_ids}
        if str(match.get("target_value")) not in scope and match.get("created_by") != viewer.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该任务")
    return match


@app.post("/api/assignments/{assignment_id}/publish")
def publish_assignment(
    assignment_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    _load_assignment_for(current, assignment_id)
    try:
        return assignment_service.publish_assignment(int(assignment_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/assignments/{assignment_id}/targets")
def assignment_targets(
    assignment_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """目标人群与接收情况（管理端看进度）。"""
    current = _require_admin_viewer(viewer)
    _assert_action(current, Action.MANAGE_DEPARTMENT)
    _load_assignment_for(current, assignment_id)
    return {"targets": assignment_service.list_targets(int(assignment_id))}


@app.get("/api/assignments/mine")
def my_assignments(viewer: Viewer = Depends(require_viewer)) -> dict[str, Any]:
    """员工端：待接收任务。"""
    rows = assignment_service.pending_for_user(viewer.user_id)
    return {
        "pending": [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row.get("description"),
                "due_date": row.get("due_date"),
                "acceptance": row.get("acceptance"),
            }
            for row in rows
        ]
    }


@app.post("/api/assignments/{assignment_id}/accept")
def accept_assignment(
    assignment_id: int, viewer: Viewer = Depends(require_viewer)
) -> dict[str, Any]:
    """员工接收任务 → 自动生成个人训练（复制资料 + 排 5 轮计划）。"""
    try:
        receipt = assignment_service.accept_assignment(int(assignment_id), viewer.user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "assignment_id": receipt["assignment_id"],
        "training_id": receipt["training_id"],
        "received_at": receipt["received_at"],
    }


# ---------------------------------------------------------------- 前端静态资源（同域）
#

# ======================================================================
# 个人版（2026-10-26 用户决策）：邮箱+密码账户 + 创建训练全链路向导
# 企业版登录码机制保留在上方原端点（前端个人版不再使用）。
# ======================================================================


class RegisterBody(BaseModel):
    email: str
    password: str
    display_name: str = ""


class PasswordLoginBody(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=int(auth_service.SESSION_TTL_DAYS) * 24 * 3600,
        path="/",
    )


@app.post("/api/auth/register")
def register_account_endpoint(body: RegisterBody, response: Response) -> dict[str, Any]:
    try:
        result = auth_service.register_account(
            body.email, body.password, body.display_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _set_session_cookie(response, result["session"]["token"])
    return {
        "viewer": _viewer_payload(result["viewer"]),
        "expires_at": result["session"]["expires_at"],
    }


@app.post("/api/auth/login")
def login_password_endpoint(body: PasswordLoginBody, response: Response) -> dict[str, Any]:
    try:
        result = auth_service.login_password(body.email, body.password)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不正确"
        ) from exc
    _set_session_cookie(response, result["session"]["token"])
    return {
        "viewer": _viewer_payload(result["viewer"]),
        "expires_at": result["session"]["expires_at"],
    }


# ------------------------------ 创建向导 ------------------------------


def _require_user(viewer: Viewer | None) -> Viewer:
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return viewer


def _clarify_payload(session: Any) -> dict[str, Any]:
    from src.services import goal_clarification_service as _gcs

    draft = session.draft
    pace = {
        "horizon_days": draft.horizon_days or None,
        "horizon_weeks": round(draft.horizon_days / 7) if draft.horizon_days else None,
        "session_count": draft.session_count or None,
        # 推荐值【待校准】：澄清步知识点未知，按等级给建议（user-defined-training-plan 1.3）
        "recommended": _gcs.recommend_pace(draft.level or ""),
        "ranges": {"horizon_weeks": [1, 8], "session_count": [2, 6]},
    }
    return {
        "training_id": session.training_id,
        "topic": session.topic,
        "question": session.question,
        "action": session.action,
        "rounds": session.rounds,
        "can_confirm": session.can_confirm,
        "draft": {
            "content": draft.content,
            "level": draft.level,
            "acceptance": draft.acceptance,
            "field_sources": draft.field_sources,
        },
        "pace": pace,
        "missing_fields": list(session.missing_fields),
        "history": session.history,
        "notes": session.notes,
    }


class WizardStartBody(BaseModel):
    topic: str


class WizardAnswerBody(BaseModel):
    answer: str


class WizardPaceBody(BaseModel):
    """训练节奏（user-defined-training-plan）：UI 控件收集，非对话。"""

    horizon_weeks: int  # 1-8 周（快照落 horizon_days = 周 × 7，范围 7-56）
    session_count: int  # 2-6 次


class SourceAddBody(BaseModel):
    type: str  # text | url
    title: str = ""
    content: str = ""
    url: str = ""


class ProbeGradeBody(BaseModel):
    answers: list[str]
    items: list[dict[str, Any]] = []


@app.post("/api/wizard/start")
def wizard_start(body: WizardStartBody, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _require_user(viewer)
    topic = body.topic.strip()
    if len(topic) < 4:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="多用一句话描述你想学什么")
    from src.db.connection import transaction as _tx
    from src.services import goal_clarification_service

    session = goal_clarification_service.start_session(topic)
    with _tx() as active:  # 个人版：训练归属当前账号与所在组织（member-invite 后组织可为空）
        if viewer.org_id is not None:
            active.execute(
                "UPDATE trainings SET owner_user_id = ?, org_id = ? WHERE id = ?",
                (int(viewer.user_id), int(viewer.org_id), int(session.training_id)),
            )
        else:
            active.execute(
                "UPDATE trainings SET owner_user_id = ? WHERE id = ?",
                (int(viewer.user_id), int(session.training_id)),
            )
    return _clarify_payload(session)


@app.get("/api/wizard/{training_id}/clarify")
def wizard_clarify_state(training_id: int, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import goal_clarification_service

    session = goal_clarification_service.load_session(int(training_id))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有进行中的澄清会话")
    return _clarify_payload(session)


@app.post("/api/wizard/{training_id}/answer")
def wizard_clarify_answer(
    training_id: int, body: WizardAnswerBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import goal_clarification_service

    try:
        session = goal_clarification_service.continue_session(int(training_id), body.answer)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _clarify_payload(session)


@app.post("/api/wizard/{training_id}/pace")
def wizard_set_pace(
    training_id: int, body: WizardPaceBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """训练节奏（change user-defined-training-plan）：UI 控件收集，user_input 来源落快照。"""
    _require_user(viewer)
    from src.services import goal_clarification_service

    try:
        session = goal_clarification_service.set_pace(
            int(training_id),
            int(body.horizon_weeks) * 7,
            int(body.session_count),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _clarify_payload(session)


@app.post("/api/wizard/{training_id}/confirm")
def wizard_clarify_confirm(training_id: int, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import goal_clarification_service

    try:
        training = goal_clarification_service.confirm(int(training_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"training_id": int(training_id), "status": training.status}


@app.post("/api/wizard/{training_id}/sources")
def wizard_add_source(
    training_id: int, body: SourceAddBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import source_service

    try:
        if body.type == "text":
            source = source_service.create_source(
                int(training_id), type="user_paste", title=body.title, content=body.content
            )
        elif body.type == "url":
            # fetch_web_source 负责抓取 + 快照 + 登记一步完成
            source = source_service.fetch_web_source(int(training_id), body.url)
        else:
            raise ValueError("暂不支持该来源类型（支持 text / url / 文件上传）")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    source = source_service.parse_source(source.id)  # 切片入索引，供出题/探测回指
    return {"id": source.id, "title": source.title, "type": source.type, "parse_status": source.parse_status}


@app.post("/api/wizard/{training_id}/sources/file")
async def wizard_upload_source(
    training_id: int, request: Request, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import source_service

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件")
    data = await upload.read()
    try:
        source = source_service.create_source_from_file(
            int(training_id), filename=str(upload.filename or "upload"), data=data
        )
        source = source_service.parse_source(source.id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"解析失败：{exc}") from exc
    return {"id": source.id, "title": source.title, "type": source.type, "parse_status": source.parse_status}


@app.post("/api/wizard/{training_id}/probe")
def wizard_generate_probe(training_id: int, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import edge_service

    training = queries.get_training(int(training_id))
    if training is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练不存在")
    goal = _training_goal(training)
    try:
        probe = edge_service.generate_probe_items(
            int(training_id), topic=training.topic, goal=goal
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    items = [
        {
            "index": i,
            "knowledge_point": item.knowledge_point,
            "heading_path": item.heading_path,
            "difficulty": item.difficulty,
            "question": item.question,
            "reference_answer": item.reference_answer,
        }
        for i, item in enumerate(probe.items)
    ]
    return {
        "training_id": int(training_id),
        "items": items,
        "total_points": getattr(probe, "total_points", len(items)),
        "selected_points": getattr(probe, "selected_points", len(items)),
        "fallback_used": getattr(probe, "fallback_used", False),
        "truncated": getattr(probe, "truncated", False),
    }


def _training_goal(training: Any) -> Any:
    import json as _json

    raw = getattr(training, "goal_json", None)
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except Exception:
        return None


@app.post("/api/wizard/{training_id}/probe/grade")
def wizard_grade_probe(
    training_id: int, body: ProbeGradeBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import edge_service

    training = queries.get_training(int(training_id))
    if training is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练不存在")
    items = [
        edge_service.ProbeItem(
            knowledge_point=str(raw.get("knowledge_point") or ""),
            heading_path=str(raw.get("heading_path") or ""),
            difficulty=int(raw.get("difficulty") or 1),
            question=str(raw.get("question") or ""),
            reference_answer=str(raw.get("reference_answer") or ""),
            answer=str(raw.get("answer") or ""),
        )
        for raw in body.items
    ]
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可判定的作答")
    try:
        graded = edge_service.grade_probe(int(training_id), items, topic=training.topic)
        edge_service.save_probe(graded)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "training_id": int(training_id),
        "counts": graded.state_counts(),
        "items": [
            {
                "knowledge_point": item.knowledge_point,
                "question": item.question,
                "answer": item.answer,
                "state": item.state,
                "verdict": item.verdict,
                "reason": item.reason,
            }
            for item in graded.items
        ],
    }


@app.post("/api/wizard/{training_id}/activate")
def wizard_activate(training_id: int, viewer: Viewer | None = Depends(current_viewer)) -> dict[str, Any]:
    _require_user(viewer)
    from src.core.goal import assert_transition

    training = queries.get_training(int(training_id))
    if training is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练不存在")
    try:
        assert_transition(training.status, "active")
        queries.set_training_status(int(training_id), "active")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"training_id": int(training_id), "status": "active"}


@app.post("/api/wizard/{training_id}/path")
def wizard_generate_path(
    training_id: int,
    background_tasks: BackgroundTasks,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    _require_user(viewer)
    from src.services import path_service, plan_service

    training = queries.get_training(int(training_id))
    if training is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练不存在")
    try:
        skeleton, _report = path_service.generate_skeleton(
            int(training_id), topic=training.topic, goal=_training_goal(training)
        )
        path_service.save_skeleton(skeleton)
        plan_service.generate_plan(int(training_id))
        # 早早生成：路径一出就把题目全部预生成（后台，幂等）
        background_tasks.add_task(plan_service.pregenerate_questions, int(training_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"路径生成失败：{exc}") from exc
    return {
        "training_id": int(training_id),
        "stages": len(skeleton.stages),
        "items": sum(len(stage.items) for stage in skeleton.stages),
    }


# ---------------------------------------------------------------- 成员邀请（change member-invite）


def _org_viewer(viewer: Viewer | None, org_id: int) -> Viewer:
    """组织类端点的登录守卫：必须登录且属于该组织（org-and-roles 语义沿用）。"""
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    if viewer.org_id is None or int(viewer.org_id) != int(org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能操作自己所在的组织")
    return viewer


class OrgCreateBody(BaseModel):
    name: str


@app.post("/api/org/create")
def create_organization_view(
    body: OrgCreateBody, viewer: Viewer = Depends(require_viewer)
) -> dict[str, Any]:
    """建组（member-invite）：个人模式用户创建组织并成为其组织管理员。"""
    from src.db.connection import transaction as _tx
    from src.services.org_service import add_membership, create_organization

    if viewer.org_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="你已经在组织中——建新组请先退出当前组织")
    if len(body.name.strip()) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="组织名至少 2 个字符")
    with _tx() as active:
        org = create_organization(body.name.strip(), conn=active)
        membership = add_membership(
            int(viewer.user_id), int(org["id"]), role="org_admin", status="active", conn=active
        )
    return {"org_id": int(org["id"]), "name": org["name"], "role": membership["role"]}


@app.get("/api/org/{org_id}/candidates")
def list_candidates_view(
    org_id: int,
    q: str = "",
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """候选列表（已注册 ∧ 非本组织成员）；仅 admin+/本组织成员。"""
    v = _org_viewer(viewer, org_id)
    _assert_action(v, "manage_members")
    return {"candidates": org_service.list_candidates(org_id, query=q)}


class InviteBody(BaseModel):
    email: str


@app.post("/api/org/{org_id}/invite")
def invite_member_view(
    org_id: int, body: InviteBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """站内邀请（拍板 3：站外邮箱后置）：admin 受配额，org_admin 不受限。"""
    v = _org_viewer(viewer, org_id)
    _assert_action(v, "manage_members")
    try:
        return org_service.invite_member(org_id, v, body.email)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/org/{org_id}/members/{user_id}/progress")
def member_progress_view(
    org_id: int, user_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """成员互看进度（拍板 4：完成状态 + 分数聚合，不暴露作答明细）。"""
    v = _org_viewer(viewer, org_id)
    try:
        return org_service.member_progress(org_id, v, user_id)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


class MemberRoleBody(BaseModel):
    role: str  # member | admin
    admin_quota: int | None = None
    admin_can_remove: bool | None = None


@app.put("/api/org/{org_id}/members/{user_id}/role")
def set_member_role_view(
    org_id: int,
    user_id: int,
    body: MemberRoleBody,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """org_admin 专属：升降 admin / 逐人配额与删除开关。"""
    v = _org_viewer(viewer, org_id)
    try:
        return org_service.set_member_role(
            org_id,
            v,
            user_id,
            role=body.role,
            admin_quota=body.admin_quota,
            admin_can_remove=body.admin_can_remove,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.delete("/api/org/{org_id}/members/{user_id}")
def remove_member_view(
    org_id: int, user_id: int, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """移除成员（资格置 disabled）：admin 受开关且只能移 member；org_admin 总可。"""
    v = _org_viewer(viewer, org_id)
    try:
        return org_service.remove_member(org_id, v, user_id)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@app.get("/api/my/invites")
def my_invites_view(viewer: Viewer = Depends(require_viewer)) -> dict[str, Any]:
    """被邀请人侧：我的待接受邀请。"""
    return {"invites": org_service.list_my_invites(int(viewer.user_id))}


@app.post("/api/my/invites/{membership_id}/accept")
def accept_invite_view(
    membership_id: int, viewer: Viewer = Depends(require_viewer)
) -> dict[str, Any]:
    """接受邀请：invited → active（进组后共享计划拉取自动可用）。"""
    try:
        return org_service.accept_invite(int(viewer.user_id), membership_id)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------- coach-memory（会话小结 / 连败反馈 / 偏好）


@app.get("/api/trainings/{training_id}/session-summary")
def training_session_summary(
    training_id: int,
    date: str | None = None,
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """训练日会话小结（coach-memory）：读时聚合当天判分作答，零新表。

    ``date`` 缺省取当地今天；格式必须 YYYY-MM-DD。
    """
    _load_training_for(viewer, training_id)
    if date is not None and not session_summary.is_valid_summary_date(date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date 格式应为 YYYY-MM-DD")
    return session_summary.summarize_day(int(training_id), date or None)


class PreferenceBody(BaseModel):
    values: dict[str, Any]


@app.get("/api/preferences")
def get_preferences_view(
    viewer: Viewer | None = Depends(current_viewer),
) -> dict[str, Any]:
    """用户偏好（coach-memory）：app_settings 三键，未设置的键回落默认值。

    偏好只影响呈现与节奏，MUST NOT 影响学习内容与判分（合意困难边界）。
    """
    return {"preferences": preferences_service.get_preferences()}


@app.put("/api/preferences")
def put_preferences_view(
    body: PreferenceBody, viewer: Viewer | None = Depends(current_viewer)
) -> dict[str, Any]:
    """批量写偏好：键白名单 + 值校验，非法键/值整批拒绝（400）。"""
    try:
        preferences = preferences_service.set_preferences(body.values)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "preferences": preferences}


# 【必须放在文件最后】FastAPI 按注册顺序匹配路由：SPA 回退用的是 `/{full_path:path}` 通配，
# 一旦注册在 API 之前，就会把后面注册的接口全部吞掉（第一次部署时 `/api/org/*` 就是这样 404 的）。

if WEB_DIST.is_dir():
    _assets = WEB_DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        """SPA 路由回退：`/`、`/login`、`/path` 等前端路由都返回 index.html。

        同一个进程既提供 API 又提供界面 → 天然同域、Cookie 直接可用，**不需要 Nginx**。
        `/api/*` 未命中的路径返回 404，而不是把 index.html 当接口结果返回。
        """
        if full_path.startswith("api"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接口不存在")
        candidate = (WEB_DIST / full_path).resolve()
        if full_path and candidate.is_file() and WEB_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


__all__ = ["app", "current_viewer", "require_viewer"]
