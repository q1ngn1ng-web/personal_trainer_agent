"""新建训练向导：描述 → 澄清目标 → 选资料来源 → 定位理解边缘 → 完成。

流程依据 ADR-0018：**先有来源，再定位理解边缘**——探测题从用户导入的资料里出，
而不是让模型凭空生成后拿关键词约束。
"""
from __future__ import annotations

import streamlit as st

from src.services import edge_service, source_service
from src.ui.page_sources import _render_add_forms, _render_source_list


_STEPS: tuple[int, ...] = (1, 2, 3, 4)
_STEP_TITLES: dict[int, str] = {
    1: "描述与澄清目标",
    2: "选择资料来源",
    3: "定位理解边缘",
    4: "完成",
}


def _init_state() -> None:
    defaults: dict[str, object] = {
        "nt_step": 1,
        "nt_topic": "",
        "nt_clarify_session": None,
        "nt_training_id": None,
        "nt_error": None,
        "nt_probe": None,
        "nt_probe_answers": [],
        "nt_probe_skipped": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_state() -> None:
    for key in (
        "nt_step",
        "nt_topic",
        "nt_clarify_session",
        "nt_training_id",
        "nt_error",
        "nt_probe",
        "nt_probe_answers",
        "nt_probe_skipped",
    ):
        st.session_state.pop(key, None)


def _maybe_redirect() -> bool:
    """If ``?training_id=`` is set, surface a notice and stop rendering."""
    raw = st.query_params.get("training_id")
    if raw:
        try:
            training_id = int(raw)
        except (TypeError, ValueError):
            training_id = raw
        st.info(
            f"已选择训练 #{training_id}，跳转到训练详情页。"
            f"如未自动跳转，请点击下方按钮。"
        )
        if st.button("前往训练详情", key="nt_goto_detail", type="primary"):
            st.query_params["training_id"] = str(training_id)
            st.rerun()
        st.stop()
        return True
    return False


def _render_header(step: int) -> None:
    st.title("🎯 新建训练向导")
    st.caption("主题 → 关键词 → 基线诊断 → 完成")
    cols = st.columns(4)
    for idx, step_no in enumerate(_STEPS):
        with cols[idx]:
            label = _STEP_TITLES[step_no]
            if step_no == step:
                st.markdown(f"**▶ 第 {step_no} 步 · {label}**")
            elif step_no < step:
                st.markdown(f"✅ 第 {step_no} 步 · {label}")
            else:
                st.markdown(f"第 {step_no} 步 · {label}")
    st.divider()


def _render_draft(draft) -> None:
    """展示目标草案。``inferred`` 字段标出「系统建议」。"""
    from src.core.goal import GoalFieldSource

    rows = [
        ("学习内容", draft.content),
        ("目标等级", draft.level),
        ("验收标准", _acceptance_text(draft.acceptance)),
    ]
    for label, value in rows:
        name = {"学习内容": "content", "目标等级": "level", "验收标准": "acceptance"}[label]
        # 只有「有值且来源是推断」时才标系统建议；空字段标的是待补充
        has_value = bool(str(value or "").strip())
        is_inferred = draft.field_sources.get(name) == GoalFieldSource.INFERRED.value
        mark = " 🟡系统建议" if (has_value and is_inferred) else ""
        st.markdown(f"- **{label}**：{value or '（待补充）'}{mark}")


def _acceptance_text(value) -> str:
    if isinstance(value, dict):
        if value.get("type") == "quantitative":
            return (
                f"{value.get('statement') or ''}（口径 {value.get('metric')}，目标 {value.get('target')}）"
            )
        return str(value.get("statement") or value.get("check") or "")
    return str(value or "")


def _render_step1() -> None:
    """第 1 步：描述学习内容 → AI 追问 → 用户确认目标。"""
    _render_header(1)
    st.subheader("📝 第 1 步：描述学习内容，确认训练目标")
    st.caption(
        "用一句话描述你想训练的内容即可，系统会追问关键信息。"
        "训练周期与频次属于下一步「训练路径」，这里不填。"
    )

    session = st.session_state.get("nt_clarify_session")
    topic = st.text_input(
        "学习内容",
        value=st.session_state["nt_topic"],
        placeholder="例如：我想学英语虚拟语气",
        key="nt_topic_input",
        disabled=session is not None,
    )

    if session is None:
        if st.button("开始澄清 →", key="nt_start_clarify", type="primary", width="stretch"):
            text = (topic or "").strip()
            if not text:
                st.error("请先用一句话描述你想训练的内容")
                return
            from src.services.goal_clarification_service import start_session

            with st.spinner("正在理解你的目标..."):
                try:
                    session = start_session(text)
                except Exception as exc:
                    st.error(f"澄清失败：{exc}")
                    return
            st.session_state["nt_clarify_session"] = session
            st.session_state["nt_training_id"] = session.training_id
            st.rerun()
        return

    st.divider()
    st.markdown(f"**已澄清 {session.rounds} 轮**")
    _render_draft(session.draft)

    for note in session.notes:
        st.info(note)
    if session.fallback_used:
        st.warning("LLM 暂时不可用，已降级为表单式提问。")

    # 只要还有追问（含软限后的「也可以自己改」提示）就保留回答入口
    if session.question:
        st.markdown(f"**{session.question}**")
        # 每轮用不同的 key：既能拿到空白的输入框，又避免在控件实例化后改写 session_state
        answer = st.text_input("你的回答", key=f"nt_clarify_answer_{session.rounds}")
        if st.button("提交回答", key="nt_answer", type="primary"):
            from src.services.goal_clarification_service import continue_session

            with st.spinner("正在更新目标..."):
                updated = continue_session(session.training_id, answer)
            st.session_state["nt_clarify_session"] = updated
            st.rerun()

    col1, col2 = st.columns([1, 1])
    with col1:
        confirm_disabled = not session.can_confirm
        if st.button(
            "✅ 确认目标", key="nt_confirm_goal", type="primary",
            disabled=confirm_disabled, width="stretch",
        ):
            from src.services.goal_clarification_service import confirm

            with st.spinner("正在保存目标快照..."):
                training = confirm(session.training_id)
            st.session_state["nt_topic"] = session.draft.content
            st.session_state["nt_training_id"] = training.id
            st.session_state["nt_step"] = 2
            st.session_state["nt_error"] = None
            st.rerun()
    with col2:
        if st.button("重新开始", key="nt_restart_clarify", width="stretch"):
            st.session_state["nt_clarify_session"] = None
            st.session_state["nt_topic"] = ""
            st.rerun()

    if not session.can_confirm and not session.question:
        st.caption("补充上表中标记为「待补充」的字段后即可确认。")


def _render_step2() -> None:
    """第 2 步：选择训练资料来源（至少一份才能继续）。"""
    _render_header(2)
    st.subheader("📚 第 2 步：选择训练资料来源")
    st.caption("训练内容从你的资料里来，不是模型凭空编的。至少添加一份资料才能继续。")

    training_id = st.session_state.get("nt_training_id")
    if not training_id:
        st.error("没有找到当前训练，请返回第一步重新开始。")
        if st.button("← 返回", key="nt_step2_noid_back"):
            st.session_state["nt_step"] = 1
            st.rerun()
        return

    training_id = int(training_id)
    _render_source_list(training_id)

    st.markdown("### 添加资料")
    _render_add_forms(training_id)

    sources = source_service.list_sources(training_id)
    usable = [source for source in sources if source.parse_status == "ok"]
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← 返回", key="nt_step2_back", width="stretch"):
            st.session_state["nt_step"] = 1
            st.rerun()
    with col2:
        if st.button(
            "下一步：定位理解边缘 →",
            key="nt_step2_next",
            type="primary",
            width="stretch",
            disabled=not usable,
        ):
            st.session_state["nt_probe"] = None
            st.session_state["nt_step"] = 3
            st.rerun()
    if not usable:
        st.caption("添加并解析成功至少一份资料后，才能进入下一步。")


def _render_step3() -> None:
    """第 3 步：从资料里出题，定位理解边缘。"""
    _render_header(3)
    st.subheader("🎯 第 3 步：定位理解边缘")
    st.caption(
        "题目只从你刚导入的资料里出。答完会分成三类："
        "**已掌握**（跳过）、**边缘**（教学重点）、**未达**（先做前置铺垫）。"
    )

    training_id = int(st.session_state["nt_training_id"])
    probe = st.session_state.get("nt_probe")

    if probe is None:
        if st.button("开始探测", key="nt_probe_start", type="primary", width="stretch"):
            with st.spinner("正在从资料里出题..."):
                try:
                    probe = edge_service.generate_probe_items(
                        training_id, topic=st.session_state["nt_topic"]
                    )
                except Exception as exc:
                    st.error(f"出题失败：{exc}")
                    return
            st.session_state["nt_probe"] = probe
            st.session_state["nt_probe_answers"] = [""] * len(probe.items)
            st.rerun()
        if st.button("跳过探测（按中位难度起步）", key="nt_probe_skip"):
            st.session_state["nt_probe_skipped"] = True
            st.session_state["nt_step"] = 4
            st.rerun()
        return

    answers: list[str] = list(st.session_state.get("nt_probe_answers") or [])
    if len(answers) != len(probe.items):
        answers = [""] * len(probe.items)

    if probe.fallback_used:
        st.warning("模型出题失败，已退回按知识点生成的朴素问法。")

    for index, item in enumerate(probe.items):
        st.markdown(
            f"**Q{index + 1}** · {item.knowledge_point} · 难度 {'⭐' * max(1, min(4, item.difficulty))}"
        )
        st.markdown(f"> {item.question}")
        answers[index] = st.text_area(
            f"你的答案 Q{index + 1}",
            value=answers[index],
            key=f"nt_probe_answer_{index}",
            height=100,
            placeholder="不查资料，凭理解作答；不会就写「不会」",
        )
    st.session_state["nt_probe_answers"] = answers

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← 返回", key="nt_step3_back", width="stretch"):
            st.session_state["nt_probe"] = None
            st.session_state["nt_step"] = 2
            st.rerun()
    with col2:
        submit = st.button("提交并判定 →", key="nt_probe_submit", type="primary", width="stretch")

    if submit:
        for index, item in enumerate(probe.items):
            item.answer = answers[index]
        with st.spinner("正在评定..."):
            graded = edge_service.grade_probe(
                training_id, probe.items, topic=st.session_state["nt_topic"]
            )
            edge_service.save_probe(graded)
        st.session_state["nt_probe"] = graded
        st.session_state["nt_probe_skipped"] = False
        st.session_state["nt_step"] = 4
        st.rerun()


def _render_step4() -> None:
    """第 4 步：展示探测结果并把训练推进到可训练状态。"""
    _render_header(4)
    st.subheader("🎉 训练已就绪")

    training_id = int(st.session_state["nt_training_id"])
    from src.core.goal import assert_transition
    from src.db import queries

    probe = st.session_state.get("nt_probe")
    skipped = bool(st.session_state.get("nt_probe_skipped"))

    if skipped:
        st.info("你跳过了探测：训练项会按中位难度起步，并在训练中用实际表现快速修正。")
    elif probe is not None:
        counts = probe.state_counts()
        cols = st.columns(3)
        cols[0].metric("已掌握（跳过）", counts["mastered"])
        cols[1].metric("边缘（教学重点）", counts["edge"])
        cols[2].metric("未达（先铺垫）", counts["unreached"])

        st.markdown("**逐个知识点**")
        for item in probe.items:
            label = edge_service.PROBE_STATE_LABELS.get(item.state or "", item.state or "")
            st.markdown(f"- {item.knowledge_point}：{label}")
            if item.reason:
                st.caption(f"　{item.reason}")

    training = queries.get_training(training_id)
    if training is not None and training.status == "confirmed":
        try:
            assert_transition(training.status, "active")
            queries.set_training_status(training_id, "active")
            st.success("训练已激活，可以开始今天的训练了。")
        except Exception as exc:  # 状态异常不应阻塞用户看到结果
            st.warning(f"激活训练时出错：{exc}")
    elif training is not None:
        st.caption(f"当前训练状态：`{training.status}`")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🧭 去生成训练路径", key="nt_step4_path", type="primary", width="stretch"):
            for key in list(st.query_params.keys()):
                del st.query_params[key]
            st.query_params["page"] = "path"
            st.query_params["training_id"] = str(training_id)
            st.rerun()
    with col2:
        if st.button("📅 去今日任务卡", key="nt_step4_daily", width="stretch"):
            for key in list(st.query_params.keys()):
                del st.query_params[key]
            st.query_params["page"] = "daily"
            st.query_params["training_id"] = str(training_id)
            st.rerun()


def render() -> None:
    """Render the new-training wizard."""
    if _maybe_redirect():
        return
    _init_state()

    step = int(st.session_state.get("nt_step", 1))
    if step not in _STEPS:
        step = 1
        st.session_state["nt_step"] = 1

    if step == 1:
        _render_step1()
    elif step == 2:
        _render_step2()
    elif step == 3:
        _render_step3()
    else:
        _render_step4()


__all__ = ["render"]
