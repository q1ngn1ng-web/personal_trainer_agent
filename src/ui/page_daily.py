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

_ITEM_TYPE_LABEL: dict[str, str] = {
    "memory": "记忆性",
    "comprehension": "理解性",
    "practice": "实践性",
    "prerequisite": "前置铺垫",
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
    from src.ui import components

    baseline_score = float(training.baseline_score or 0)
    created_at = _parse_created_at(training.created_at)
    days = (datetime.now(timezone.utc) - created_at).days if created_at else 0
    components.stat_cards(
        [
            ("基线分", f"{baseline_score:.1f}", training.baseline_level or "档位未知"),
            ("坚持天数", f"{days} 天", f"创建于 {(created_at or datetime.now(timezone.utc)).date().isoformat()}"),
        ]
    )


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
    from src.ui import components

    components.section("3. 主动回忆题")
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


def _render_plan_item(training_id: int, task: Any) -> None:
    """计划项勾选：勾上 = **练过**（`practiced`），不产生"达标"（达标由判定写入）。"""
    from src.core.plan import local_today
    from src.services import attempt_service, plan_service

    currently = task.status == "practiced"
    label = f"第 {task.round_index}/5 轮 · {task.title}"
    if task.knowledge_point:
        label += f" · {task.knowledge_point}"
    new_value = st.checkbox(label, key=f"dl_plan_{task.plan_id}", value=currently)

    # 作答结果（客观表现的唯一来源）：答对 / 答错
    state = attempt_service.item_mastery(training_id, task.item_key)
    col_ok, col_no, col_info = st.columns([1, 1, 3])
    if col_ok.button("✓ 答对", key=f"dl_pass_{task.plan_id}"):
        with st.spinner("记录作答..."):
            _, just_mastered = attempt_service.record_and_evaluate(
                training_id,
                task.item_key,
                "pass",
                plan_id=task.plan_id,
                round_index=task.round_index,
            )
            plan_service.complete_tasks([task.plan_id], completed=True)
            check_task(training_id, f"P{task.plan_id}", True)
        st.session_state[f"dl_attempt_msg_{task.plan_id}"] = (
            "已记录：答对。连续 2 次答对即判定达标 🏅" if just_mastered else "已记录：答对。"
        )
        st.rerun()
    if col_no.button("✗ 答错", key=f"dl_fail_{task.plan_id}"):
        with st.spinner("记录作答..."):
            attempt_service.record_and_evaluate(
                training_id,
                task.item_key,
                "fail",
                plan_id=task.plan_id,
                round_index=task.round_index,
            )
            plan_service.complete_tasks([task.plan_id], completed=True)
            check_task(training_id, f"P{task.plan_id}", True)
        st.session_state[f"dl_attempt_msg_{task.plan_id}"] = "已记录：答错，下轮会继续安排。"
        st.rerun()
    if state.attempts:
        accuracy_text = f"{state.accuracy:.0%}" if state.accuracy is not None else "—"
        mastered_text = " · 已达标 🏅" if state.mastered else ""
        col_info.caption(
            f"近 {state.attempts} 次准确率 {accuracy_text} · 连续通过 {state.streak} 次{mastered_text}"
        )
    message = st.session_state.pop(f"dl_attempt_msg_{task.plan_id}", None)
    if message:
        st.success(message)

    meta = [f"预计 {task.planned_minutes} 分钟"]
    if task.item_type:
        meta.append(_ITEM_TYPE_LABEL.get(task.item_type, task.item_type))
    if task.is_overdue(local_today()):
        meta.append(f"原定 {task.original_date.isoformat()}，已累计到今天")
    st.caption("　·　".join(meta))

    if new_value != currently:
        with st.spinner("保存训练状态..."):
            plan_service.complete_tasks([task.plan_id], completed=new_value)
            # 保留打卡记录：完成度与奖励机制依赖 daily_log_tasks
            check_task(training_id, f"P{task.plan_id}", new_value)
        st.rerun()


def _render_plan_section(
    title: str, tasks: list[Any], training_id: int, empty_hint: str
) -> None:
    from src.core.plan import local_today
    from src.ui import components

    components.section(title)
    if not tasks:
        st.info(empty_hint)
        return
    for task in tasks:
        overdue = task.is_overdue(local_today())
        prefix = "⏳" if overdue else "✨"
        with st.expander(
            f"{prefix} 第 {task.round_index}/5 轮　{task.title}", expanded=False
        ):
            st.markdown(f"**知识点**：{task.knowledge_point or '—'}")
            _render_plan_item(training_id, task)


def _render_plan_overview(training_id: int, tasks: list[Any]) -> None:
    """当日负荷概览：只提示不裁剪（ADR-0021）。"""
    from src.services import path_service, plan_service
    from src.ui import components

    minutes = sum(int(task.planned_minutes or 0) for task in tasks)
    rounds = sorted({task.round_index for task in tasks})
    round_text = "、".join(f"第 {index} 轮" for index in rounds) or "—"
    progress = plan_service.plan_progress(training_id)
    with components.card():
        components.stat_cards(
            [
                ("今日任务", f"{len(tasks)} 项", round_text),
                ("预计用时", f"{minutes} 分钟", "整轮不裁剪"),
                (
                    "计划进度",
                    f"{progress['practiced']}/{progress['total']}",
                    "已练次数 / 总计划次数",
                ),
            ]
        )
        if progress["total"]:
            st.progress(min(max(progress["practiced"] / progress["total"], 0.0), 1.0))

    path = path_service.load_path(training_id)
    budget = int(getattr(path, "daily_budget_minutes", 0) or 0)
    if budget and minutes > budget:
        st.warning(
            f"今天预计 {minutes} 分钟，超过你设定的 {budget} 分钟——"
            "整轮不裁剪，做不完的部分明天继续（会累计）。"
        )


def _render_quiz_section(training_id: int) -> None:
    """测验：每 14 天一次（也可手动开始）；**作答过程中不给提示**，提交后统一出结果。

    取题只从题库里**冷却期已过**的题里选（ADR-0016）；LLM 不可用时降级为自评，并明确标注。
    """
    from src.services import quiz_service
    from src.ui import components

    components.section("4. 测验", "每 14 天一次 · 内容不可挑 · 无提示")
    key_id = f"dl_quiz_{training_id}"
    key_result = f"dl_quiz_result_{training_id}"

    result = st.session_state.get(key_result)
    if result:
        level = st.success if result["passed"] else st.warning
        level(
            f"测验结果：{result['score']:.0%}（{result['question_count']} 题）——"
            + ("通过 ✅" if result["passed"] else "未通过，相关题目已加练一轮")
        )
        if result["failed_items"]:
            st.caption("未掌握的知识点：" + "、".join(
                str(item.get("knowledge_point") or "未标注") for item in result["failed_items"]
            ))
        st.caption(f"判分方式：{'AI 判分' if result['graded_by'] == 'llm' else '自评（AI 判分不可用）'}")
        if st.button("关闭结果", key=f"dl_quiz_close_{training_id}"):
            st.session_state.pop(key_result, None)
            st.rerun()
        return

    assessment_id = st.session_state.get(key_id)
    if assessment_id is None:
        pending = quiz_service.pending_quiz_plan(training_id)
        latest = quiz_service.latest_assessment(training_id)
        if pending is not None:
            pool_size = len(quiz_service.question_pool(training_id))
            if pool_size:
                st.info(
                    f"今天的测验到点了（可抽 {pool_size} 道题）：**内容不可挑**，答完统一给结果。"
                )
            else:
                st.warning(
                    "测验到点了，但题库里还没有**冷却期已过**的题——"
                    "练过的题要过 14 天才能进测验（ADR-0016）。先去把今天的题练完吧。"
                )
        elif latest is not None and latest.status == "in_progress":
            st.info(f"有一次未完成的测验（#{latest.id}），继续它即可。")
        else:
            st.caption("没有到期的测验。每 14 天一次，也可以现在手动来一次。")
        if st.button(
            "开始测验" if pending is None else "开始今日测验",
            key=f"dl_quiz_start_{training_id}",
            type="primary",
        ):
            try:
                assessment = quiz_service.start_assessment(
                    training_id,
                    trigger="scheduled" if pending else "manual",
                    plan_id=int(pending["id"]) if pending else None,
                )
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.session_state[key_id] = int(assessment.id)
                st.rerun()
        return

    items = quiz_service.load_items(int(assessment_id))
    if not items:
        st.session_state.pop(key_id, None)
        st.warning("这次测验没有题目，已重置。")
        return
    st.caption(
        f"共 {len(items)} 题 · 通过线 80% · "
        + ("变式题" if all(item.is_variant for item in items) else "含原题（变式生成不可用）")
    )
    answers: dict[int, str] = {}
    for item in items:
        st.markdown(f"**{item.ordinal}. {item.question}**")
        answers[item.id] = st.text_area(
            "你的作答",
            key=f"dl_quiz_ans_{item.id}",
            height=80,
            label_visibility="collapsed",
        )
    col_submit, col_manual = st.columns(2)
    if col_submit.button("提交答卷", key=f"dl_quiz_submit_{assessment_id}", type="primary"):
        quiz_service.save_answers(int(assessment_id), answers)
        if quiz_service.grade_with_llm(int(assessment_id)):
            outcome = quiz_service.finish_assessment(int(assessment_id), graded_by="llm")
            st.session_state[key_result] = outcome.__dict__
            st.session_state.pop(key_id, None)
        else:
            st.session_state[f"dl_quiz_manual_{assessment_id}"] = True
        st.rerun()

    if st.session_state.get(f"dl_quiz_manual_{assessment_id}"):
        st.warning("AI 判分暂时不可用，请对照参考答案自评（自评会标注来源）。")
        verdicts: dict[int, str] = {}
        for item in items:
            st.markdown(f"**{item.ordinal}. {item.question}**")
            st.caption(f"你答的是：{answers.get(item.id) or '（空）'}")
            st.caption(f"参考答案：{item.reference_answer or '（暂无）'}")
            choice = st.radio(
                "自评",
                options=["答对", "答错"],
                key=f"dl_quiz_verdict_{item.id}",
                horizontal=True,
                label_visibility="collapsed",
            )
            verdicts[item.id] = "pass" if choice == "答对" else "fail"
        if st.button("提交自评结果", key=f"dl_quiz_finish_manual_{assessment_id}"):
            quiz_service.save_manual_verdicts(int(assessment_id), verdicts)
            outcome = quiz_service.finish_assessment(int(assessment_id), graded_by="self")
            st.session_state[key_result] = outcome.__dict__
            st.session_state.pop(key_id, None)
            st.session_state.pop(f"dl_quiz_manual_{assessment_id}", None)
            st.rerun()


def _render_signal_section(training_id: int, focus: Any | None = None) -> None:
    """四失一键反馈：点一下就提交，不填表。"""
    from src.services import attempt_service, plan_service, signal_service
    from src.ui import components

    components.section("6. 今天的感受", "点一下就行，不用填表")

    objective = attempt_service.objective_for_training(training_id)
    objective_label = {"low": "偏低", "mid": "中等", "high": "很好", "unknown": "数据不足"}.get(
        objective, objective
    )
    _accuracy, attempts = attempt_service.training_accuracy(training_id)
    st.caption(
        f"客观表现：近 {attempts} 次作答 → {objective_label}（少于 3 次只做轻微调整，不结构调）"
    )

    item_key = getattr(focus, "item_key", None)
    item_id = plan_service.item_id_for(training_id, item_key) if item_key else None
    if focus is not None:
        st.caption(f"本次反馈关联到当前训练项：{focus.title}")

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
                    training_id,
                    code,
                    item_id=item_id,
                    item_key=item_key,
                    objective=objective,
                    raw_text="",
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
    from src.ui import components

    components.section("7. 留言（可选）")
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
    from src.ui import components

    components.section("5. 完成度")
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
    from src.ui import components

    components.section("8. 奖励领取")
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
    from src.ui import components

    components.page_header(
        f"📅 今日任务卡 · {training.topic or '未命名'}",
        "勾选＝练过（不产生达标）；答对/答错才是客观记录；连续 2 次答对才算达标",
    )
    _training_header(training)

    from src.core.plan import local_today
    from src.services import plan_service

    progress = get_today_progress(training.id)
    recall_questions = get_today_recall_questions(training.id)

    # 有路径但还没排期时补生成一次（幂等）
    plan_service.ensure_plan(training.id)
    plan_tasks = plan_service.today_tasks(training_id=training.id)
    today = local_today()

    if plan_tasks or plan_service.has_plan(training.id):
        _render_plan_overview(training.id, plan_tasks)
        _render_plan_section(
            "1. 待补（累计到今天）",
            [task for task in plan_tasks if task.is_overdue(today)],
            training.id,
            "没有欠下的训练项。",
        )
        _render_plan_section(
            "2. 今天到期",
            [task for task in plan_tasks if not task.is_overdue(today)],
            training.id,
            "今天没有到期的训练项，可以休息或重练已练过的题。",
        )
    else:
        # 没有训练路径的老训练：继续走老的复习日历口径
        tasks = extract_today_tasks(training.id)
        _render_review_section(tasks.review_items, training.id, progress)
        _render_new_section(tasks.new_items, training.id, progress)

    _render_recall_section(recall_questions, training.id)
    _render_quiz_section(training.id)
    _render_progress_section(progress)
    _render_signal_section(training.id, plan_tasks[0] if plan_tasks else None)
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
