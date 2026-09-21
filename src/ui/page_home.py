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
    TrainingStatus.DRAFT: "📝 草稿",
    TrainingStatus.PENDING_CONFIRM: "🟡 待确认目标",
    TrainingStatus.CONFIRMED: "📚 待选资料/路径",
    TrainingStatus.ACTIVE: "🟢 活跃",
    TrainingStatus.PAUSED: "⏸️ 暂停",
    TrainingStatus.COMPLETED: "🎉 已达标",
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
    from src.ui import components

    components.page_header(
        "🎯 训练教练",
        "描述想学什么 → AI 澄清目标 → 选资料 → 定位理解边缘 → 生成路径 → 每天按计划练到熟",
        chips=[
            "每道题练 5 轮（第 1/3/7/15/30 天）",
            "练过即入题库，每 14 天测验",
            "连续 2 次答对才算达标",
        ],
    )


def _render_today_plan() -> None:
    """首页「今日训练」：跨训练聚合当天的计划项（ADR-0021 / progress-dashboard）。

    只读：所有写操作（勾选）都发生在今日任务卡里。
    """
    from src.db.queries import list_trainings
    from src.services import plan_service

    from src.ui import components

    components.section("📌 今日训练", "跨训练聚合，只读")
    summary = plan_service.today_summary()
    if not summary["count"]:
        upcoming: list[tuple[date, str]] = []
        pending_plan = 0
        for training in list_trainings():
            next_due = plan_service.next_due_date(int(training.id))
            if next_due is not None:
                upcoming.append((next_due, str(training.topic or "未命名")))
            elif not plan_service.has_plan(int(training.id)):
                pending_plan += 1
        if upcoming:
            next_due, topic = min(upcoming, key=lambda pair: pair[0])
            st.info(f"今天是休息日。下一次训练：{next_due.isoformat()}（{topic}）")
        elif pending_plan:
            st.info(
                f"还有 {pending_plan} 个训练没有生成计划——"
                "打开它的「今日任务卡」会自动按创建日排出 5 轮。"
            )
        else:
            st.info("今天没有训练任务。确认训练路径后会自动生成 5 轮计划。")
        return

    with components.card():
        components.stat_cards(
            [
                ("今日训练项", f"{summary['count']} 项", "跨全部训练"),
                ("预计用时", f"{summary['minutes']} 分钟", "按题型默认时长估算"),
                ("涉及训练", f"{len(summary['groups'])} 个", "同一天可能多主题并行"),
            ]
        )
        for group in summary["groups"]:
            st.markdown(
                f"{components.badge('今日', 'run')} **{group['topic'] or '未命名'}**"
                f"　{group['count']} 项 · 约 {group['minutes']} 分钟"
            )
        if st.button("进入今日任务卡", key="home_today_enter", type="primary"):
            for key in list(st.query_params.keys()):
                del st.query_params[key]
            st.query_params["page"] = "daily"
            st.rerun()


def _render_metrics(dashboard: HomeDashboard) -> None:
    from src.ui import components

    avg_label = (
        f"{dashboard.avg_baseline:.1f}/5"
        if dashboard.avg_baseline is not None
        else "—"
    )
    components.stat_cards(
        [
            ("训练主题数", dashboard.total_all, "全部状态"),
            ("活跃训练", dashboard.total_active, "status = active"),
            ("平均基线", avg_label, "来自基线诊断"),
        ]
    )


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
    from src.ui import components

    components.section("📚 训练列表", "点击进入训练详情")
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


def _render_delete_panel(dashboard: HomeDashboard) -> None:
    """删除训练：危险操作，必须手动输入训练 ID 才能执行。"""
    from src.db import queries

    trainings = queries.list_trainings()
    if not trainings:
        return

    with st.expander("🗑 删除训练（不可恢复）", expanded=False):
        st.caption(
            "删除会一并清掉这个训练的资料、切片、路径、训练项、信号与调用记录，**无法恢复**。"
        )
        options = {
            f"#{t.id} · {getattr(t, 'status', '')} · {(getattr(t, 'topic', '') or '')[:28]}": t.id
            for t in trainings
        }
        picked = st.selectbox("选择要删除的训练", list(options), key="hm_delete_pick")
        target_id = options[picked]
        typed = st.text_input(
            f"输入 `{target_id}` 以确认删除", key="hm_delete_confirm_input"
        )
        if st.button("确认删除", key="hm_delete_btn", type="primary"):
            if (typed or "").strip() != str(target_id):
                st.error("确认编号不一致，已取消。")
            else:
                if queries.delete_training(target_id):
                    st.success(f"训练 #{target_id} 已删除")
                    st.rerun()
                else:
                    st.warning("没有找到该训练，可能已被删除。")


def render() -> None:
    """Render the home page."""
    _render_hero()
    st.divider()

    _render_today_plan()
    st.divider()

    dashboard = compute_home_dashboard()
    _render_metrics(dashboard)
    st.divider()

    _render_training_list(dashboard)
    _render_delete_panel(dashboard)
    _render_new_training_cta()


__all__ = ["render"]
