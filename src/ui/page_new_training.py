"""Streamlit wizard that drives the new-training creation flow."""
from __future__ import annotations

import streamlit as st

from src.services.baseline_service import BaselineQuestions
from src.services.keyword_service import KeywordResult
from src.services.trainer_service import TrainerCreationError, create_training


_STEPS: tuple[int, ...] = (1, 2, 3, 4)
_STEP_TITLES: dict[int, str] = {
    1: "描述与澄清目标",
    2: "确认关键词",
    3: "基线诊断",
    4: "完成",
}


def _init_state() -> None:
    defaults: dict[str, object] = {
        "nt_step": 1,
        "nt_topic": "",
        "nt_clarify_session": None,
        "nt_clarify_answer": "",
        "nt_validation": None,
        "nt_keywords": None,
        "nt_keywords_input": "",
        "nt_forbidden_input": "",
        "nt_must_cover_count": 2,
        "nt_questions": None,
        "nt_answers": ["", "", ""],
        "nt_result": None,
        "nt_training_id": None,
        "nt_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_state() -> None:
    for key in (
        "nt_step",
        "nt_topic",
        "nt_clarify_session",
        "nt_clarify_answer",
        "nt_validation",
        "nt_keywords",
        "nt_keywords_input",
        "nt_forbidden_input",
        "nt_must_cover_count",
        "nt_questions",
        "nt_answers",
        "nt_result",
        "nt_training_id",
        "nt_error",
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


def _score_label(score: str) -> str:
    return {
        "mastered": "✅掌握",
        "partial": "⚠️半掌握",
        "missing": "❌缺失",
        "": "☐ 未判定",
    }.get(score, "☐ 未判定")


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
        mark = " 🟡系统建议" if draft.field_sources.get(name) == GoalFieldSource.INFERRED.value else ""
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

    if session.question and not session.can_confirm:
        st.markdown(f"**{session.question}**")
        answer = st.text_input("你的回答", key="nt_clarify_answer")
        if st.button("提交回答", key="nt_answer", type="primary"):
            from src.services.goal_clarification_service import continue_session

            with st.spinner("正在更新目标..."):
                updated = continue_session(session.training_id, answer)
            st.session_state["nt_clarify_session"] = updated
            st.session_state["nt_clarify_answer"] = ""
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
    _render_header(2)
    st.subheader("🔑 第 2 步：关键词白名单确认")
    st.caption("每道基线诊断题至少覆盖 must_cover_count 个关键词；forbidden 中的词不会出现在题目里。")

    if st.session_state["nt_keywords"] is None:
        from src.services.keyword_service import generate_keywords
        try:
            with st.spinner("正在生成关键词白名单..."):
                kw = generate_keywords(st.session_state["nt_topic"])
        except Exception as exc:
            st.error(f"关键词生成失败：{exc}")
            if st.button("← 返回", key="nt_step2_back_fail", width='stretch'):
                st.session_state["nt_step"] = 1
                st.rerun()
            return
        st.session_state["nt_keywords"] = kw
        st.session_state["nt_keywords_input"] = "\n".join(kw.keywords)
        st.session_state["nt_forbidden_input"] = "\n".join(kw.forbidden)
        st.session_state["nt_must_cover_count"] = kw.must_cover_count
        st.rerun()

    kw: KeywordResult = st.session_state["nt_keywords"]
    st.info(f"已生成 {len(kw.keywords)} 个关键词，必覆盖数 {kw.must_cover_count}，禁止词 {len(kw.forbidden)} 个。")

    new_keywords_text = st.text_area(
        "关键词（每行一个，可编辑）",
        value=st.session_state.get("nt_keywords_input", "\n".join(kw.keywords)),
        height=200,
        key="nt_keywords_input_widget",
    )
    new_forbidden_text = st.text_area(
        "禁止词（每行一个，可留空）",
        value=st.session_state.get("nt_forbidden_input", "\n".join(kw.forbidden)),
        height=100,
        key="nt_forbidden_input_widget",
    )
    new_must = st.number_input(
        "每道题必须覆盖的关键词数",
        min_value=1,
        max_value=5,
        value=int(st.session_state.get("nt_must_cover_count", kw.must_cover_count)),
        step=1,
        key="nt_must_widget",
    )

    st.session_state["nt_keywords_input"] = new_keywords_text
    st.session_state["nt_forbidden_input"] = new_forbidden_text
    st.session_state["nt_must_cover_count"] = new_must

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← 返回", key="nt_step2_back", width='stretch'):
            st.session_state["nt_step"] = 1
            st.rerun()
    with col2:
        confirm = st.button(
            "下一步：生成基线诊断题 →", key="nt_go_step3", type="primary", width='stretch'
        )

    if confirm:
        parsed_keywords = [
            line.strip() for line in (new_keywords_text or "").splitlines() if line.strip()
        ]
        parsed_forbidden = [
            line.strip() for line in (new_forbidden_text or "").splitlines() if line.strip()
        ]
        if not parsed_keywords:
            st.error("至少需要一个关键词。")
            return
        updated = KeywordResult(
            keywords=parsed_keywords,
            must_cover_count=int(new_must),
            forbidden=parsed_forbidden,
            raw=kw.raw,
        )
        st.session_state["nt_keywords"] = updated
        st.session_state["nt_answers"] = ["", "", ""]
        st.session_state["nt_questions"] = None
        st.session_state["nt_step"] = 3
        st.rerun()


def _ensure_questions() -> BaselineQuestions | None:
    cached = st.session_state.get("nt_questions")
    if cached is not None:
        return cached
    from src.services.baseline_service import generate_baseline_questions
    kw: KeywordResult = st.session_state["nt_keywords"]
    with st.spinner("正在生成基线诊断题..."):
        questions = generate_baseline_questions(
            topic=st.session_state["nt_topic"],
            keywords=kw.keywords,
            must_cover_count=kw.must_cover_count,
            forbidden=kw.forbidden,
        )
    st.session_state["nt_questions"] = questions
    return questions


def _render_step3() -> None:
    _render_header(3)
    st.subheader("🎯 第 3 步：基线诊断（3 道题）")
    st.caption("不查资料，30 秒内作答。LLM 会判定每题掌握度并给出基线档位（高/中/低）。")

    questions = _ensure_questions()
    if questions is None:
        st.error("基线题生成失败，请返回上一步。")
        if st.button("← 返回", key="nt_step3_back_fail"):
            st.session_state["nt_step"] = 2
            st.rerun()
        return

    if questions.fallback_used:
        st.warning("⚠️ LLM 生成失败，已使用预置基线诊断题。")

    answers: list[str] = list(st.session_state["nt_answers"])
    if len(answers) != len(questions.questions):
        answers = [""] * len(questions.questions)

    for idx, question in enumerate(questions.questions):
        st.markdown(f"**Q{idx + 1}** · 维度：{question.dimension} · 难度：{'⭐' * max(1, min(3, question.difficulty))}")
        st.markdown(f"> {question.question}")
        st.caption(f"参考答案：{question.reference_answer}")
        answers[idx] = st.text_area(
            f"你的答案 Q{idx + 1}",
            value=answers[idx],
            key=f"nt_answer_{idx}",
            height=120,
            placeholder="不查资料，凭直觉作答",
        )

    st.session_state["nt_answers"] = answers

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← 返回", key="nt_step3_back", width='stretch'):
            st.session_state["nt_step"] = 2
            st.rerun()
    with col2:
        submit = st.button(
            "提交诊断并生成训练 →", key="nt_submit", type="primary", width='stretch'
        )

    if submit:
        if not all((a or "").strip() for a in answers):
            st.error("请完成 3 道题的作答后再提交。")
            return
        try:
            with st.spinner("正在评分基线 + 生成 10 份训练文件 + 写库..."):
                training = create_training(
                    topic=st.session_state["nt_topic"],
                    baseline_answers=answers,
                )
        except TrainerCreationError as exc:
            st.session_state["nt_error"] = exc
            st.error(f"创建失败（{exc.step}）：{exc.original}")
            return
        except Exception as exc:
            st.session_state["nt_error"] = exc
            st.error(f"创建失败：{exc}")
            return
        st.session_state["nt_result"] = training
        st.session_state["nt_training_id"] = training.id
        st.session_state["nt_step"] = 4
        st.rerun()


def _render_step4() -> None:
    _render_header(4)
    st.subheader("🎉 训练创建成功")

    training = st.session_state["nt_result"]
    if training is None:
        st.warning("未找到训练结果，请重试。")
        if st.button("← 重新创建", key="nt_step4_restart_empty"):
            _reset_state()
            st.rerun()
        return

    progress = st.progress(min(1.0, max(0.0, (training.baseline_score or 0.0) / 5.0)))
    cols = st.columns(3)
    level_value = (
        training.baseline_level.value
        if hasattr(training.baseline_level, "value")
        else str(training.baseline_level)
    )
    cols[0].metric("基线档位", level_value)
    cols[1].metric("基线评分", f"{training.baseline_score}/5")
    cols[2].metric("补强项数", len(training.review_items or []))

    if training.review_items:
        st.markdown("**补强复习项（partial_topics）：**")
        for item in training.review_items:
            st.markdown(f"- {item}")

    if training.pretrain_checklist:
        st.markdown("**预训练清单（基线低）：**")
        for entry in training.pretrain_checklist:
            concept = entry.get("concept", "")
            materials = entry.get("materials") or []
            materials_text = "、".join(materials) if materials else "（无推荐资料）"
            st.markdown(f"- **{concept}** — {materials_text}")

    st.markdown("**训练文件目录：**")
    st.code(str(training.directory))

    st.markdown(
        f"**训练 ID：`{training.id}`** · "
        f"**状态：** `{training.status.value if hasattr(training.status, 'value') else training.status}`"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            "查看训练详情 →",
            key="nt_goto_training_detail",
            type="primary",
            width='stretch',
        ):
            st.query_params["page"] = "detail"
            st.query_params["training_id"] = str(training.id)
            st.rerun()
    with col2:
        if st.button("再创建一个训练", key="nt_create_another", width='stretch'):
            _reset_state()
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
