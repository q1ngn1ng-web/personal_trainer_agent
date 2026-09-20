"""Streamlit page: 今日任务卡."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import streamlit as st

from src.core.content_dim import ContentDimension
from src.db.queries import get_training, list_trainings
from src.services.daily_log_service import (
    DailyProgress,
    TaskCheckResult,
    check_task,
    get_today_progress,
    record_recall_results,
    submit_reflections,
)
from src.services.recall_service import RecallQuestion, get_today_recall_questions
from src.services.schedule_service import TaskItem, extract_today_tasks

logger = logging.getLogger("src.ui.page_daily")


_DIMENSION_LABEL: dict[ContentDimension, str] = {
    ContentDimension.CONCEPT: "📖 概念",
    ContentDimension.READ: "📝 读代码",
    ContentDimension.WRITE: "💻 写代码",
}


def _format_dimension(dim: ContentDimension | None) -> str:
    if dim is None:
        return "未分类"
    return _DIMENSION_LABEL.get(dim, "未分类")


def _parse_created_at(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Defensive: legacy data stored before the tz-aware convention was added
    # may have naive ISO strings. Assume UTC for those, otherwise the
    # datetime.now(timezone.utc) - created_at subtraction raises TypeError.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _training_header(training: Any) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("主题", training.topic or "—")
    with col2:
        baseline_score = float(training.baseline_score or 0)
        st.metric("基线分", f"{baseline_score:.1f}", delta=None)
    with col3:
        level = training.baseline_level or "—"
        created_at = _parse_created_at(training.created_at)
        days = (datetime.now(timezone.utc) - created_at).days if created_at else 0
        st.metric("档位 / 坚持天数", f"{level} · {days} 天")


def _ensure_task_state(training_id: int, task_id: str, default: bool) -> bool:
    state_key = f"dl_state_{training_id}_{task_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = default
    return st.session_state[state_key]


def _render_task_checkbox(
    training_id: int,
    item: TaskItem,
    progress: DailyProgress,
) -> None:
    persisted = any(t.get("task_ref") == item.task_id and t.get("completed") for t in progress.is_required_tasks)
    current = _ensure_task_state(training_id, item.task_id, persisted)
    label = f"✅ {item.task_id}　{_format_dimension(item.dimension)}　{item.topic}"
    new_value = st.checkbox(label, key=f"dl_chk_{training_id}_{item.task_id}", value=current)
    if new_value != current:
        with st.spinner("保存任务状态..."):
            check_task(training_id, item.task_id, new_value)
            # 训练项来自数据库时同步状态，否则它明天还会出现在今日任务里
            if item.task_id.startswith("T") and item.task_id[1:].isdigit():
                from src.services import path_service

                path_service.mark_item(
                    int(item.task_id[1:]), "passed" if new_value else "pending"
                )
        st.session_state[f"dl_state_{training_id}_{item.task_id}"] = new_value
        st.rerun()


def _render_review_section(
    review_items: list[TaskItem],
    training_id: int,
    progress: DailyProgress,
) -> None:
    st.subheader("1. 复习项")
    if not review_items:
        st.info("今日无复习项 — 新学项为主要任务。")
        return
    for item in review_items:
        with st.expander(f"🔁 {item.task_id}　{item.topic}", expanded=False):
            st.markdown(f"**来源**：{item.source}")
            st.markdown(f"**维度**：{_format_dimension(item.dimension)}")
            _render_task_checkbox(training_id, item, progress)


def _render_new_section(
    new_items: list[TaskItem],
    training_id: int,
    progress: DailyProgress,
) -> None:
    st.subheader("2. 新学项")
    if not new_items:
        st.info("今日无新学项。")
        return
    for item in new_items:
        with st.expander(f"✨ {item.task_id}　{item.topic}", expanded=False):
            st.markdown(f"**来源**：{item.source}")
            st.markdown(f"**维度**：{_format_dimension(item.dimension)}")
            _render_task_checkbox(training_id, item, progress)


def _render_recall_section(
    questions: list[RecallQuestion],
    training_id: int,
) -> None:
    st.subheader("3. 主动回忆题")
    if not questions:
        st.info("暂无回忆题 — 跑完基线诊断后会自动生成。")
        return
    for q in questions:
        with st.container():
            st.markdown(f"**{q.qid} · {_format_dimension(q.dimension)} · {q.unit}**")
            st.markdown(f"> {q.question}")
            st.text_area(
                "你的答案",
                key=f"dl_recall_answer_{training_id}_{q.qid}",
                height=80,
                label_visibility="collapsed",
            )

            state_key = f"dl_recall_grade_{training_id}_{q.qid}"
            grade = st.session_state.get(state_key)
            if grade is True:
                with st.expander("参考答案", expanded=False):
                    st.write(q.reference or "（暂无参考）")
                st.success("✔ 已记录：答对")
            elif grade is False:
                with st.expander("参考答案", expanded=False):
                    st.write(q.reference or "（暂无参考）")
                st.warning("✘ 已记录：答错")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✓ 答对", key=f"dl_recall_ok_{training_id}_{q.qid}"):
                    with st.spinner("保存回忆结果..."):
                        record_recall_results(training_id, {q.qid: True})
                    st.session_state[state_key] = True
                    st.rerun()
            with col2:
                if st.button("✗ 答错", key=f"dl_recall_no_{training_id}_{q.qid}"):
                    with st.spinner("保存回忆结果..."):
                        record_recall_results(training_id, {q.qid: False})
                    st.session_state[state_key] = False
                    st.rerun()


def _render_signal_section(training_id: int) -> None:
    """四失一键反馈：点一下就提交，不填表。"""
    from src.services import signal_service

    st.subheader("5. 今天的感受")
    st.caption("点一下就行。系统会据此调整难度、范围或题量——**不用你填表**。")

    labels = signal_service.SIGNAL_ACTIONS
    columns = st.columns(4)
    for column, (code, meta) in zip(columns, labels.items()):
        with column:
            if st.button(
                meta["label"],
                key=f"dl_signal_{training_id}_{code}",
                width="stretch",
            ):
                decision = signal_service.process_signal(
                    training_id, code, raw_text="", item_status=None
                )
                st.session_state[f"dl_signal_msg_{training_id}"] = decision.message
                st.rerun()

    message = st.session_state.get(f"dl_signal_msg_{training_id}")
    if message:
        st.info(message)

    recent = signal_service.list_signals(training_id)[:5]
    if recent:
        counts = signal_service.signal_counts(training_id)
        summary = " · ".join(
            f"{labels[code]['label']} {count}" for code, count in counts.items() if count
        )
        st.caption(f"累计反馈：{summary}")


def _render_notes_section(training_id: int, progress: DailyProgress) -> None:
    """留言（推荐填）+ 三省（可选）。不再强制用户填写。"""
    st.subheader("6. 留言（可选）")
    st.caption("今天的感受、卡住的地方、想调整的地方，随便写一句就行。**不填也能领奖励。**")

    note = st.text_area(
        "留言",
        key=f"dl_note_{training_id}",
        height=100,
        placeholder="例如：今天这 5 道题里有两道完全不会 / 感觉太简单了 / 明天想少做一点",
    )

    with st.expander("三省（可选，想写再写）", expanded=False):
        loyal = st.text_area("忠于目标吗", key=f"dl_ref_loyal_{training_id}", max_chars=100, height=80)
        method = st.text_area("方法有效吗", key=f"dl_ref_method_{training_id}", max_chars=100, height=80)
        applied = st.text_area("付诸实践了吗", key=f"dl_ref_applied_{training_id}", max_chars=100, height=80)

    if progress.reflection_submitted_at:
        st.caption(f"上次保存于 {progress.reflection_submitted_at}")

    if st.button("保存留言", key=f"dl_save_ref_{training_id}", type="primary"):
        with st.spinner("保存中..."):
            submit_reflections(training_id, loyal, method, applied, note=note)
        st.success("已保存")
        st.rerun()


def _render_progress_section(progress: DailyProgress) -> None:
    st.subheader("4. 完成度")
    if progress.total_tasks <= 0:
        st.progress(0.0)
        st.metric("今日完成度", "0/0")
    else:
        ratio = progress.completed_count / progress.total_tasks
        st.progress(min(max(ratio, 0.0), 1.0))
        st.metric("今日完成度", f"{progress.completed_count}/{progress.total_tasks}")
    st.metric(
        "回忆题正确率",
        (
            f"{progress.recall_questions_correct}/{progress.recall_questions_total}"
            f" ({progress.recall_success_rate:.0%})"
            if progress.recall_success_rate is not None
            else "—"
        ),
    )


def _render_reward_section(progress: DailyProgress, training_id: int) -> None:
    st.subheader("7. 奖励领取")
    all_done = progress.total_tasks > 0 and progress.completed_count == progress.total_tasks
    if all_done:
        if st.button("🎁 领取今日奖励", key=f"dl_reward_{training_id}"):
            st.balloons()
            st.success("奖励领取成功！参考 07_奖励机制.md 选择你心仪的奖励。")
    else:
        pending = []
        if not all_done:
            missing = max(progress.total_tasks - progress.completed_count, 0)
            if missing > 0:
                pending.append(f"还需完成 {missing} 项")
            else:
                pending.append("尚无已完成任务")
        st.info(" · ".join(pending))


def _render_training(training: Any) -> None:
    st.title(f"📅 今日任务卡 — {training.topic}")
    _training_header(training)

    progress = get_today_progress(training.id)
    tasks = extract_today_tasks(training.id)
    recall_questions = get_today_recall_questions(training.id)

    _render_review_section(tasks.review_items, training.id, progress)
    _render_new_section(tasks.new_items, training.id, progress)
    _render_recall_section(recall_questions, training.id)
    _render_progress_section(progress)
    _render_signal_section(training.id)
    _render_notes_section(training.id, progress)
    _render_reward_section(progress, training.id)


def _render_no_training() -> None:
    st.title("📅 今日任务卡")
    st.warning("请先选择一个训练")
    trainings = list_trainings(status="active")
    if not trainings:
        st.info("当前没有 active 状态的训练。请先到「新建训练」创建一个。")
        return

    options = {f"#{t.id} · {t.topic}": t.id for t in trainings}
    label = st.selectbox("选择训练", list(options.keys()), key="dl_training_select")
    if st.button("进入训练", key="dl_enter_training"):
        st.query_params["training_id"] = str(options[label])
        st.rerun()


def render() -> None:
    """Render the daily card page."""
    raw = st.query_params.get("training_id")
    if not raw:
        _render_no_training()
        return

    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    try:
        training_id = int(str(raw))
    except (TypeError, ValueError):
        st.error("无效的训练 ID")
        return

    training = get_training(training_id)
    if training is None:
        st.error(f"未找到训练 ID={training_id}")
        _render_no_training()
        return

    _render_training(training)


__all__ = ["render"]
