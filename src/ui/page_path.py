"""训练路径页：查看阶段与训练项、微调投入参数、确认路径。

展示形态按 ADR-0009：**嵌套列表 + 进度**，不画模型生成的流程图。
"""
from __future__ import annotations

import streamlit as st

from src.core.goal import is_generation_ready
from src.db import queries
from src.services import path_service, source_service as svc

_TYPE_LABELS: dict[str, str] = {
    "memory": "记忆性",
    "comprehension": "理解性",
    "practice": "实践性",
    "prerequisite": "前置铺垫",
}

_STATUS_LABELS: dict[str, str] = {
    "pending": "⬜ 待练",
    "in_progress": "🔄 进行中",
    "practiced": "✅ 今天练过",
    "passed": "🏅 已达标（判定）",
    "failed": "❌ 未通过",
}


def _resolve_training() -> object | None:
    trainings = queries.list_trainings()
    if not trainings:
        st.info("还没有任何训练。请先到「新建」创建一个。")
        return None
    raw = st.query_params.get("training_id")
    if raw:
        try:
            training = queries.get_training(int(raw))
            if training is not None:
                return training
        except (TypeError, ValueError):
            pass
    options = {f"#{t.id} · {(t.topic or '未命名')[:24]}（{t.status}）": t for t in trainings}
    label = st.selectbox("选择训练", list(options), key="path_training_pick")
    return options[label]


def _flash(message: str, level: str = "success") -> None:
    st.session_state["path_flash"] = {"message": message, "level": level}


def _render_flash() -> None:
    payload = st.session_state.pop("path_flash", None)
    if not payload:
        return
    renderer = getattr(st, str(payload.get("level", "success")), None)
    (renderer if callable(renderer) else st.info)(str(payload.get("message", "")))


def _render_items(stage_id: int) -> None:
    items = path_service.load_items(stage_id)
    if not items:
        st.caption("该阶段还没有训练项。")
        return
    chunk_ids: list[int] = []
    for item in items:
        chunk_ids.extend(int(value) for value in (item.source_chunk_ids or []))
    provenance = {row["id"]: row for row in svc.get_chunks_by_ids(sorted(set(chunk_ids)))}

    for item in items:
        label = _TYPE_LABELS.get(item.item_type or "", item.item_type or "")
        status = _STATUS_LABELS.get(item.status, item.status)
        stars = "⭐" * max(1, min(4, item.difficulty_tier or 1))
        st.markdown(f"- {status} **{item.title}** · {label} · {stars}")
        if not (item.source_chunk_ids or []):
            st.caption("　🤖 AI 生成，无原文出处")
        if item.knowledge_point:
            st.caption(f"　知识点：{item.knowledge_point}")
        for chunk_id in (item.source_chunk_ids or [])[:2]:
            row = provenance.get(int(chunk_id))
            if row:
                st.caption(f"　出处：{row['source_title']} · {row['heading_path']}")


def _render_editor(training_id: int, path) -> None:
    from src.ui import components

    components.section(
        "调整投入",
        "每次时长现在是「单日负荷提示阈值」；周期与每周次数已不参与排期（ADR-0021）",
    )
    col1, col2, col3 = st.columns(3)
    horizon = col1.number_input("周期（周）", 1, 52, int(path.horizon_weeks or 2), key="path_horizon")
    frequency = col2.number_input("每周训练次数", 1, 14, int(path.weekly_frequency or 5), key="path_freq")
    minutes = col3.number_input("每次时长（分钟）", 5, 240, int(path.daily_budget_minutes or 30), key="path_minutes")

    preview_budget = horizon * frequency * minutes
    planned = int(path.planned_minutes or 0)
    st.caption(f"预算 {preview_budget} 分钟 · 路径预计 {planned} 分钟")
    if planned > preview_budget:
        st.error("当前投入无法容纳这条路径，请增加周期/频次/时长，或压缩路径。")

    if st.button("保存投入", key="path_save_budget", type="primary"):
        updated = path_service.adjust_budget(
            training_id,
            horizon_weeks=int(horizon),
            weekly_frequency=int(frequency),
            daily_budget_minutes=int(minutes),
        )
        if updated and planned > int(updated.budget_minutes or 0):
            _flash("已保存，但路径仍超出预算", "warning")
        else:
            _flash("投入已更新")
        st.rerun()


def _render_path(training_id: int) -> None:
    path = path_service.load_path(training_id)
    if path is None:
        st.info("这个训练还没有训练路径。")
        if st.button("生成路径草案", key="path_generate", type="primary"):
            training = queries.get_training(training_id)
            with st.spinner("正在生成路径..."):
                try:
                    skeleton, report = path_service.generate_skeleton(
                        training_id, topic=training.topic if training else "", goal=training.goal_json if training else None
                    )
                    saved = path_service.save_skeleton(skeleton)
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
                    return
            level = "warning" if not report.ok or report.too_light else "success"
            _flash(f"{report.message}（路径 #{saved.id} v{saved.version}）", level)
            st.rerun()
        return

    status_label = {"draft": "🟡 草案（待确认）", "confirmed": "✅ 已确认", "superseded": "🗄 已被取代"}.get(
        path.status, path.status
    )
    st.markdown(f"### 版本 v{path.version} · {status_label}")

    cols = st.columns(4)
    cols[0].metric("周期", f"{path.horizon_weeks} 周")
    cols[1].metric("每周次数", path.weekly_frequency)
    cols[2].metric("每次时长", f"{path.daily_budget_minutes} 分钟")
    cols[3].metric("预算占用", f"{path.planned_minutes or 0}/{path.budget_minutes or 0} 分钟")

    if (path.planned_minutes or 0) > (path.budget_minutes or 0):
        st.error("路径超出预算，请调整投入或压缩内容后再确认。")

    stages = path_service.load_stages(path.id)
    from src.services import mastery_service

    report = mastery_service.evaluate(training_id)
    stage_report = {item.stage_id: item for item in report.stages}
    components.section("达标进度")
    quiz_text = "已通过 ✅" if report.quiz_passed else "未通过 / 未做"
    st.caption(
        f"必修覆盖 {report.passed_items}/{report.total_items} 已达标 · 最终测验：{quiz_text}"
        f" · 模式：{'覆盖' if report.mode == mastery_service.COVERAGE_MODE else '达成'}"
    )
    if report.mastered:
        st.success("🎉 任务达标：必修覆盖 100% 且最终测验已通过，训练已置为 completed。")
    else:
        st.caption(f"距达标还差：{report.reason}")

    components.section("阶段与训练项")
    for stage in stages:
        items = path_service.load_items(stage.id)
        distribution: dict[str, int] = {}
        for item in items:
            key = _TYPE_LABELS.get(item.item_type or "", item.item_type or "其他")
            distribution[key] = distribution.get(key, 0) + 1
        distribution_text = " · ".join(f"{name} {count}" for name, count in distribution.items())
        # 锁定态来自 mastery_service 写回的 path_stages.status（不再永远 locked）
        verdict = stage_report.get(stage.id)
        if verdict is not None and verdict.mastered:
            lock_label = "✅ 已达标"
        elif verdict is not None and verdict.status == "active":
            lock_label = "▶ 进行中"
        else:
            lock_label = "🔒 待解锁"
        with st.expander(
            f"{lock_label} · {stage.ordinal}. {stage.title} — {len(items)} 项 · "
            f"约 {stage.estimated_minutes} 分钟 · {distribution_text}",
            expanded=stage.ordinal == 1,
        ):
            if stage.goal:
                st.caption(stage.goal)
            if verdict is not None:
                st.caption(
                    f"达标 {verdict.passed}/{verdict.total} 项 · {verdict.reason}"
                )
            _render_items(stage.id)

    if path.status == "draft":
        _render_editor(training_id, path)
        over_budget = (path.planned_minutes or 0) > (path.budget_minutes or 0)
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🗑 丢弃草案", key="path_discard"):
                st.session_state["path_discard_confirm"] = True
        with col2:
            if st.button("✅ 确认路径", key="path_confirm", type="primary", disabled=over_budget):
                confirmed = path_service.confirm_path(training_id)
                if confirmed:
                    from src.services import plan_service

                    plan = plan_service.generate_plan(training_id)
                    if plan.is_empty:
                        _flash("路径已确认，但这个训练还没有训练项，暂时无法排期。", "warning")
                    else:
                        _flash(
                            f"路径已确认。已排出 {plan.rounds} 轮计划（共 {plan.item_count} 道题 × 5 轮）："
                            f"第 1 轮到 {plan.last_due_date} 全部完成即训练结束。"
                        )
                st.rerun()
        if st.session_state.get("path_discard_confirm"):
            st.warning("丢弃草案会删除当前未确认的路径，确认请再点一次。")
            if st.button("确认丢弃", key="path_discard_yes"):
                st.session_state["path_discard_confirm"] = False
                _flash("（未实现删除，草案会保留到下次生成时被替换）", "info")
                st.rerun()
    else:
        st.caption("已确认的路径不会就地大改；需要重构时会产生新版本。")

    st.divider()
    components.section("其他操作")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🎯 重新定位理解边缘", key="path_redo_probe", width="stretch"):
            # 回到新建向导的第 3 步：会话状态是全局的，设置后跳页即可
            st.session_state["nt_training_id"] = training_id
            st.session_state["nt_step"] = 3
            st.session_state["nt_probe"] = None
            training = queries.get_training(training_id)
            st.session_state["nt_topic"] = training.topic if training else ""
            for key in list(st.query_params.keys()):
                del st.query_params[key]
            st.query_params["page"] = "new_training"
            st.rerun()
    with col2:
        if st.button("📅 今日任务", key="path_to_daily", width="stretch"):
            for key in list(st.query_params.keys()):
                del st.query_params[key]
            st.query_params["page"] = "daily"
            st.query_params["training_id"] = str(training_id)
            st.rerun()


def render() -> None:
    from src.ui import components

    components.page_header("🧭 训练路径", "阶段 → 训练项 → 每道题 5 轮 · 练到达标")
    _render_flash()
    training = _resolve_training()
    if training is None:
        return
    if (
        not is_generation_ready(training.status)
        and training.status not in ("active", "completed")
    ):
        st.warning(
            f"训练 #{training.id} 当前状态是 `{training.status}`。请先确认训练目标并选好资料。"
        )
        return
    st.caption(f"训练 #{training.id} · {training.topic}")
    _render_path(int(training.id))


__all__ = ["render"]
