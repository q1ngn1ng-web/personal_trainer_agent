"""Streamlit page: 周复盘简报.

Displays the week's mechanical metrics, the LLM-generated calibration
suggestion, and exposes confirm/skip controls that route through the
``review_service`` orchestrator.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import streamlit as st

from src.db.queries import get_training, list_trainings
from src.services.calibration_service import CalibrationSuggestion
from src.services.metrics_calculator import WeeklyMetrics
from src.services.review_service import (
    ReviewOutcome,
    apply_weekly_review,
    prepare_weekly_review,
    skip_weekly_review,
)

logger = logging.getLogger("src.ui.page_review")


_OUTCOME_KEY: str = "rv_outcome"
_TRAINING_ID_KEY: str = "rv_training_id"
_PREPARED_FLAG_KEY: str = "rv_prepared"


def _training_header(training: Any) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("主题", training.topic or "—")
    with col2:
        score = float(training.baseline_score or 0)
        st.metric("基线分", f"{score:.1f}")
    with col3:
        created = training.created_at
        days = 0
        if created:
            try:
                days = (datetime.now() - datetime.fromisoformat(str(created).replace("Z", "+00:00"))).days
            except ValueError:
                days = 0
        st.metric(
            "档位 / 坚持天数",
            f"{training.baseline_level or '—'} · {max(days, 0)} 天",
        )


def _render_metrics_section(metrics: WeeklyMetrics) -> None:
    st.subheader("📊 本周指标")
    cells = [
        ("平均完成度", f"{metrics.avg_completion:.0%}", None),
        ("回忆题正确率", f"{metrics.avg_recall_success:.0%}", None),
        ("三省覆盖率", f"{metrics.three_reflection_coverage:.0%}", None),
        ("连续打卡", f"{metrics.consecutive_days} 天", None),
        ("薄弱主题", metrics.weakest_topic or "—", None),
        ("最强主题", metrics.strongest_topic or "—", None),
        ("漏做任务数", str(len(metrics.missed_tasks)), None),
    ]
    for row_start in range(0, len(cells), 2):
        pair = st.columns(2)
        for col, (label, value, delta) in zip(pair, cells[row_start : row_start + 2]):
            with col:
                st.metric(label, value, delta=delta)


def _dict_to_md_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    if not rows:
        return "（无）\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join(
        "| " + " | ".join(str(row.get(col, "")) for col in columns) + " |"
        for row in rows
    )
    return f"{header}\n{sep}\n{body}\n"


def _render_schedule_table(schedule: dict[str, str]) -> None:
    if not schedule:
        st.markdown("（暂无计划调整）")
        return
    rows = [{"topic": str(k), "adjustment": str(v)} for k, v in schedule.items()]
    table = _dict_to_md_table(rows, ["topic", "adjustment"])
    st.markdown(table)


def _render_materials_table(recommendations: list[dict[str, Any]]) -> None:
    if not recommendations:
        st.markdown("（暂无资料调整建议）")
        return
    rows = [
        {
            "action": str(item.get("action", "")),
            "ref": str(item.get("ref", "")),
            "reason": str(item.get("reason", "")),
        }
        for item in recommendations
        if isinstance(item, dict)
    ]
    table = _dict_to_md_table(rows, ["action", "ref", "reason"])
    st.markdown(table)


def _render_suggestion_section(suggestion: CalibrationSuggestion) -> None:
    st.subheader("🧭 LLM 校准建议")
    if suggestion.fallback_used:
        st.warning("LLM 校准不可用，使用启发式降级建议")

    delta_col, _gap = st.columns([1, 3])
    with delta_col:
        st.metric(
            "基线调整",
            f"{suggestion.baseline_score_delta:+.1f}",
            delta_color="normal",
        )

    st.markdown("**计划调整**")
    _render_schedule_table(suggestion.schedule_adjustment)

    st.markdown("**资料增减**")
    _render_materials_table(suggestion.material_recommendations)

    st.info(f"**奖励建议**：{suggestion.reward_refresh or '保持当前奖励'}")
    st.success(f"**下周重点**：{suggestion.next_week_focus or '保持当前节奏'}")


def _render_actions_section(training_id: int) -> None:
    st.subheader("✅ 确认 / 跳过")
    col_confirm, col_skip = st.columns(2)
    with col_confirm:
        if st.button(
            "✅ 确认校准",
            key=f"rv_confirm_{training_id}",
            width='stretch',
        ):
            outcome: ReviewOutcome | None = st.session_state.get(_OUTCOME_KEY)
            if outcome is None:
                st.error("尚无复盘数据，请先点击「开始本周复盘」。")
            else:
                try:
                    with st.spinner("应用校准中..."):
                        apply_weekly_review(training_id, outcome.suggestion)
                except Exception as exc:  # pragma: no cover - defensive UI surface
                    logger.exception("apply_weekly_review failed")
                    st.error(f"应用失败：{exc}")
                else:
                    st.success("已应用校准")
                    st.balloons()
                    st.session_state.pop(_OUTCOME_KEY, None)
                    st.session_state.pop(_PREPARED_FLAG_KEY, None)
                    st.rerun()
    with col_skip:
        if st.button(
            "⏭️ 跳过",
            key=f"rv_skip_{training_id}",
            width='stretch',
        ):
            try:
                with st.spinner("记录跳过..."):
                    skip_weekly_review(training_id)
            except Exception as exc:  # pragma: no cover - defensive UI surface
                logger.exception("skip_weekly_review failed")
                st.error(f"跳过失败：{exc}")
            else:
                st.info("已跳过本周复盘")
                st.session_state.pop(_OUTCOME_KEY, None)
                st.session_state.pop(_PREPARED_FLAG_KEY, None)
                st.rerun()


def _render_training(training: Any) -> None:
    training_id = int(training.id or 0)
    st.title(f"🔄 周复盘 — {training.topic}")
    _training_header(training)

    if st.button("🔄 开始本周复盘", key=f"rv_prepare_{training_id}"):
        st.session_state[_PREPARED_FLAG_KEY] = True
        st.session_state.pop(_OUTCOME_KEY, None)

    outcome: ReviewOutcome | None = st.session_state.get(_OUTCOME_KEY)
    if st.session_state.get(_PREPARED_FLAG_KEY) and outcome is None:
        with st.spinner("机械计算本周指标 + 调用 LLM 校准..."):
            try:
                outcome = prepare_weekly_review(training_id)
            except Exception as exc:
                logger.exception("prepare_weekly_review failed")
                st.error(f"复盘准备失败：{exc}")
                st.session_state[_PREPARED_FLAG_KEY] = False
                outcome = None
            else:
                st.session_state[_OUTCOME_KEY] = outcome

    if outcome is not None:
        _render_metrics_section(outcome.metrics)
        st.divider()
        _render_suggestion_section(outcome.suggestion)
        st.divider()
        _render_actions_section(training_id)


def _render_no_training() -> None:
    st.title("🔄 周复盘")
    st.warning("请先选择一个训练")
    trainings = list_trainings()
    if not trainings:
        st.info("当前没有训练记录。请先到「新建训练」创建一个。")
        return
    options = {f"#{t.id} · {t.topic}": t.id for t in trainings}
    label = st.selectbox("选择训练", list(options.keys()), key="rv_pick_training")
    if st.button("进入训练", key="rv_enter"):
        st.query_params["training_id"] = str(options[label])
        st.rerun()


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


def render() -> None:
    """Render the weekly review page."""
    training_id = _resolve_training_id()
    if training_id is None:
        _render_no_training()
        return

    training = get_training(training_id)
    if training is None:
        st.error(f"未找到训练 ID={training_id}")
        _render_no_training()
        return

    if int(st.session_state.get(_TRAINING_ID_KEY, -1)) != training_id:
        st.session_state.pop(_OUTCOME_KEY, None)
        st.session_state.pop(_PREPARED_FLAG_KEY, None)
    st.session_state[_TRAINING_ID_KEY] = training_id

    _render_training(training)


__all__ = ["render"]
