"""Streamlit page: per-training detail with P0 metrics and P1 placeholders."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.db.queries import (
    get_daily_logs_in_range,
    get_reviews_by_training,
    get_training,
    list_trainings,
)
from src.services.progress_service import (
    P1Summary,
    TrainingProgress,
    compute_training_progress,
    get_p1_summary,
)

logger = logging.getLogger("src.ui.page_training")


_REFLECTION_TITLES: tuple[str, ...] = (
    "忠于目标",
    "方法有效",
    "付诸实践",
)
_REFLECTION_KEYS: tuple[str, ...] = (
    "loyal_to_goal",
    "method_effective",
    "applied_to_practice",
)
_P1_MIN_DAYS: int = 14
_RECALL_WINDOW_DAYS: int = 7


def _resolve_training_id() -> int | None:
    raw = st.query_params.get("training_id")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if not raw:
        return None
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _render_no_training() -> None:
    st.title("📋 训练详情")
    st.warning("请选择一个训练")
    trainings = list_trainings()
    if not trainings:
        st.info("当前没有训练记录。请先到「新建训练」创建一个。")
        if st.button("➕ 新建训练", key="td_no_training_new", type="primary"):
            st.query_params["page"] = "new_training"
            st.rerun()
        return

    options = {f"#{t.id} · {t.topic or '未命名'}": int(t.id) for t in trainings}
    label = st.selectbox(
        "选择训练",
        list(options.keys()),
        key="td_pick_training",
    )
    if st.button("查看训练 →", key="td_enter_picked", type="primary"):
        st.query_params["training_id"] = str(options[label])
        st.query_params["page"] = "detail"
        st.rerun()


def _render_header(topic: str, status: str) -> None:
    cols = st.columns([6, 2, 2])
    with cols[0]:
        st.title(f"📋 {topic or '未命名训练'}")
    with cols[1]:
        st.metric("状态", status)
    with cols[2]:
        if st.button("← 返回首页", key="td_back_home", use_container_width=True):
            for key in ("training_id", "page"):
                if key in st.query_params:
                    del st.query_params[key]
            st.query_params["page"] = "home"
            st.rerun()


def _render_p0_metrics(progress: TrainingProgress) -> None:
    st.subheader("📊 P0 进展指标")
    cols = st.columns(3)
    cols[0].metric(
        "基线评分",
        f"{progress.baseline_score:.1f}/5",
        help="0=低，2.5=中，4=高",
    )
    cols[1].metric(
        "连续打卡",
        f"{progress.consecutive_days} 天",
        help="连续完成 ≥1 项任务的天数",
    )
    cols[2].metric(
        "今日完成度",
        (
            f"{progress.today_completed}/{progress.today_total}"
            if progress.today_total > 0
            else "0/0"
        ),
        help="今日任务完成进度",
    )
    if progress.today_total > 0:
        ratio = max(0.0, min(1.0, progress.today_completion))
        st.progress(ratio, text=f"今日 {ratio:.0%}")

    secondary = st.columns(2)
    secondary[0].metric("坚持天数", f"{progress.days_since_creation} 天")
    secondary[1].metric("当前周", f"第 {progress.current_week} 周")


def _render_links(training: Any) -> None:
    st.subheader("🔗 快捷入口")
    cols = st.columns(3)
    with cols[0]:
        if st.button("📅 今日训练", key="td_link_daily", use_container_width=True):
            st.query_params["page"] = "daily"
            st.rerun()
    with cols[1]:
        if st.button("🔄 周复盘", key="td_link_review", use_container_width=True):
            st.query_params["page"] = "review"
            st.rerun()
    with cols[2]:
        st.button("✏️ 编辑", key="td_link_edit", use_container_width=True, disabled=True)
    with st.expander("📂 训练目录", expanded=False):
        st.code(str(training.directory) if training.directory else "（未设置）")


def _render_p1_section(
    summary: P1Summary,
    days_since_creation: int,
) -> None:
    st.subheader("📈 P1 趋势指标")
    if not summary.has_enough_data:
        remaining = max(0, _P1_MIN_DAYS - days_since_creation)
        st.info(f"数据收集中，再练 {remaining} 天可见趋势")
        return

    history = summary.baseline_history_points
    if history:
        st.caption("基线升级曲线（按周散点）")
        st.line_chart(pd.DataFrame(history), x="date", y="score")
    else:
        st.caption("基线升级曲线暂未生成。完成首次周复盘后会记录第一个点。")

    recalls = summary.recall_rates
    if recalls:
        st.caption("回忆题正确率（最近 7 天）")
        st.line_chart(pd.DataFrame(recalls), x="date", y="rate")
    else:
        st.caption("最近 7 天没有回忆题数据。")


def _render_p2_placeholder() -> None:
    with st.expander("📌 P2 阶段目标 / 三省覆盖率", expanded=False):
        st.caption("即将推出（Phase 3 启用）")


def _parse_reflections(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
    if isinstance(raw, dict):
        return [str(raw.get(key, "") or "") for key in _REFLECTION_KEYS]
    if isinstance(raw, list):
        return [str(item or "") for item in raw]
    return [str(raw)]


def _render_three_reflections(training_id: int, today: date) -> None:
    st.subheader("🪞 最近三省")
    window_start = today - timedelta(days=14)
    logs = get_daily_logs_in_range(training_id, window_start, today)
    latest = max(logs, key=lambda log: log.log_date, default=None)
    if latest is None or not latest.three_reflections:
        st.info("还没有三省记录。今天去「今日训练」页面写下三省 ✏️")
        return

    st.caption(f"日期：{latest.log_date}")
    values = _parse_reflections(latest.three_reflections)
    cols = st.columns(3)
    for idx, column in enumerate(cols):
        with column:
            title = _REFLECTION_TITLES[idx] if idx < len(_REFLECTION_TITLES) else f"三省 {idx + 1}"
            text = values[idx] if idx < len(values) else ""
            st.markdown(f"**{title}**")
            st.markdown(text or "（未填写）")


def _render_review_history(training_id: int) -> None:
    st.subheader("📜 历史复盘")
    reviews = get_reviews_by_training(training_id)
    if not reviews:
        st.info("还没有周复盘记录。每周日跑一次复盘后会在这里累积。")
        return

    for review in reviews:
        action = "✅ 已确认" if review.user_action == "confirmed" else "⏭️ 已跳过"
        title = f"📅 {review.week_start} · {action}"
        with st.expander(title, expanded=False):
            st.caption(f"创建于 {review.created_at}")
            metrics_raw = review.metrics
            if isinstance(metrics_raw, str):
                try:
                    metrics_raw = json.loads(metrics_raw)
                except json.JSONDecodeError:
                    metrics_raw = None
            if isinstance(metrics_raw, dict) and metrics_raw:
                st.markdown("**机械指标**")
                st.json(metrics_raw)
            else:
                st.caption("（无机械指标）")
            suggestions_raw = review.llm_suggestions
            if isinstance(suggestions_raw, str):
                try:
                    suggestions_raw = json.loads(suggestions_raw)
                except json.JSONDecodeError:
                    suggestions_raw = None
            if isinstance(suggestions_raw, dict) and suggestions_raw:
                st.markdown("**LLM 校准建议**")
                st.json(suggestions_raw)
            elif isinstance(suggestions_raw, list) and suggestions_raw:
                st.markdown("**LLM 校准建议**")
                st.json(suggestions_raw)
            else:
                st.caption("（无 LLM 建议）")


def _status_label(progress: TrainingProgress) -> str:
    mapping = {
        "created": "🆕 已创建",
        "active": "🟢 活跃",
        "paused": "⏸️ 暂停",
        "archived": "📦 已归档",
        "failed": "⚠️ 失败",
    }
    return mapping.get(progress.status.value, "❓ 未知")


def _render_training(training: Any, progress: TrainingProgress) -> None:
    _render_header(training.topic or "未命名训练", _status_label(progress))
    st.divider()
    _render_p0_metrics(progress)
    st.divider()
    _render_links(training)
    st.divider()

    summary = get_p1_summary(int(training.id))
    _render_p1_section(summary, progress.days_since_creation)
    _render_p2_placeholder()
    st.divider()

    _render_three_reflections(int(training.id), date.today())
    st.divider()

    _render_review_history(int(training.id))


def render() -> None:
    """Render the training detail page."""
    training_id = _resolve_training_id()
    if training_id is None:
        _render_no_training()
        return

    training = get_training(training_id)
    if training is None:
        st.error(f"未找到训练 ID={training_id}")
        _render_no_training()
        return

    progress = compute_training_progress(training_id)
    _render_training(training, progress)


__all__ = ["render"]