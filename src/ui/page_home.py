"""Streamlit page: home (project description + training list + new-training CTA)."""
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd
import streamlit as st

from src.core.element import TrainingStatus
from src.services.progress_service import (
    HomeDashboard,
    TrainingProgress,
    compute_home_dashboard,
)

logger = logging.getLogger("src.ui.page_home")


_STATUS_BADGE: dict[TrainingStatus, str] = {
    TrainingStatus.CREATED: "🆕 已创建",
    TrainingStatus.ACTIVE: "🟢 活跃",
    TrainingStatus.PAUSED: "⏸️ 暂停",
    TrainingStatus.ARCHIVED: "📦 已归档",
    TrainingStatus.FAILED: "⚠️ 失败",
}



def _format_relative(value: datetime | None) -> str:
    if value is None:
        return "—"
    target = value.date()
    today = date.today()
    if target == today:
        return "今天"
    delta = (today - target).days
    if delta <= 0:
        return "刚刚"
    if delta < 7:
        return f"{delta} 天前"
    return target.isoformat()


def _render_hero() -> None:
    st.markdown(
        """
        <div style="padding: 8px 0 16px 0;">
          <h1 style="margin-bottom: 4px;">🎯 训练教练 MVP</h1>
          <p style="color: #6b7280; font-size: 1.05rem; margin-top: 0;">
            基于「训练之道·十要素完整闭环 v3」的自用训练教练应用
          </p>
          <p style="margin-top: 8px;">
            把"如何高效训练任何技能"工程化为可执行代码：
            主题 → LLM 校验 → 基线诊断 → 10 份 md → 日常 surface → 周复盘。
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    with cols[0]:
        st.markdown("### 🧭 闭环训练")
        st.caption("十要素覆盖：对象 / 基 / 的 / 器 / 序 / 术 / 境 / 奖 / 省 / 止")
    with cols[1]:
        st.markdown("### 📊 进展可视化")
        st.caption("基线评分、坚持天数、今日完成度，一眼看到进展")
    with cols[2]:
        st.markdown("### 🤖 LLM 增强")
        st.caption("主题校验、关键词白名单、基线题、周复盘校准，全部可追溯")


def _render_metrics(dashboard: HomeDashboard) -> None:
    cols = st.columns(3)
    cols[0].metric("训练主题数", dashboard.total_all)
    cols[1].metric("活跃训练", dashboard.total_active)
    avg_label = (
        f"{dashboard.avg_baseline:.1f}/5"
        if dashboard.avg_baseline is not None
        else "—"
    )
    cols[2].metric("平均基线", avg_label)


def _build_dataframe(progresses: list[TrainingProgress]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for p in progresses:
        rows.append(
            {
                "主题": p.topic or "—",
                "状态": _STATUS_BADGE.get(p.status, "❓ 未知"),
                "基线": float(p.baseline_score),
                "连续打卡": int(p.consecutive_days),
                "今日完成度": f"{p.today_completed}/{p.today_total}",
                "坚持天数": int(p.days_since_creation),
                "最近活跃": _format_relative(p.last_active_at),
                "_id": int(p.training_id),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(by="最近活跃", ascending=False).reset_index(drop=True)


def _render_empty_state() -> None:
    st.markdown(
        """
        <div style="border: 1px dashed #d1d5db; border-radius: 12px;
                    padding: 32px; text-align: center; background: #fafafa;">
          <h3 style="margin-bottom: 8px;">🌱 还没有训练</h3>
          <p style="color: #6b7280;">点击下方按钮开始第一次训练</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    spacer_l, button_col, spacer_r = st.columns([1, 1, 1])
    with button_col:
        if st.button(
            "➕ 新建训练",
            key="hm_empty_new_training",
            type="primary",
            width='stretch',
        ):
            st.query_params["page"] = "new_training"
            st.rerun()


def _render_training_list(dashboard: HomeDashboard) -> None:
    st.subheader("📚 训练列表")
    if not dashboard.trainings:
        _render_empty_state()
        return

    df = _build_dataframe(dashboard.trainings)
    display_df = df.drop(columns=["_id"])
    st.dataframe(
        display_df,
        width='stretch',
        hide_index=True,
        column_config={
            "基线": st.column_config.ProgressColumn(
                "基线",
                min_value=0.0,
                max_value=5.0,
                format="%.1f",
            ),
        },
    )

    options = {
        f"#{int(row['_id'])} · {row['主题']}": int(row["_id"])
        for row in df.to_dict(orient="records")
    }
    label = st.selectbox(
        "选择训练",
        list(options.keys()),
        key="hm_select_training",
    )
    cols = st.columns([1, 4])
    with cols[0]:
        if st.button(
            "进入训练 →",
            key="hm_enter_training",
            type="primary",
            width='stretch',
        ):
            st.query_params["training_id"] = str(options[label])
            st.query_params["page"] = "detail"
            st.rerun()


def _render_new_training_cta() -> None:
    st.divider()
    cols = st.columns([1, 4])
    with cols[0]:
        if st.button(
            "➕ 新建训练",
            key="hm_new_training",
            type="primary",
            width='stretch',
        ):
            st.query_params["page"] = "new_training"
            st.rerun()


def render() -> None:
    """Render the home page."""
    _render_hero()
    st.divider()

    dashboard = compute_home_dashboard()
    _render_metrics(dashboard)
    st.divider()

    _render_training_list(dashboard)
    _render_new_training_cta()


__all__ = ["render"]