"""训练资料来源页：选择/导入资料，并查看解析后的切片。

对应 OpenSpec change ``training-source-selection`` 阶段 A 的 UI 部分：
三类静态来源（粘贴文本 / 上传文件 / AI 生成）、资料列表、切片详情。
阶段 A 不提供网络来源入口（留到阶段 B）。
"""
from __future__ import annotations

import streamlit as st

from src.core.goal import is_generation_ready
from src.db import queries
from src.services import source_service as svc

_TEXT_SUFFIXES: tuple[str, ...] = (".md", ".markdown", ".txt")

_TYPE_LABELS: dict[str, str] = {
    "user_paste": "粘贴文本",
    "user_upload": "上传文件",
    "ai_generated": "AI 生成",
}

_STATUS_LABELS: dict[str, str] = {
    "pending": "⏳ 待解析",
    "ok": "✅ 已就绪",
    "failed": "❌ 解析失败",
    "unsupported": "⚠️ 暂不支持",
}


def _resolve_training() -> object | None:
    """从 query param 或下拉框确定当前训练。"""
    trainings = queries.list_trainings()
    if not trainings:
        st.info("还没有任何训练。请先到「新建」创建一个训练。")
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
    label = st.selectbox("选择训练", list(options), key="src_training_pick")
    return options[label]


def _render_add_forms(training_id: int) -> None:
    """三类静态来源的添加入口。"""
    tab_paste, tab_upload, tab_ai = st.tabs(["✏️ 粘贴文本", "📎 上传文件", "🤖 AI 生成"])

    with tab_paste:
        title = st.text_input("标题", key="src_paste_title", placeholder="例如：虚拟语气讲义")
        body = st.text_area("内容", key="src_paste_body", height=200, placeholder="粘贴 Markdown 或纯文本…")
        if st.button("保存并解析", key="src_paste_submit", type="primary"):
            if not body.strip():
                st.error("内容不能为空")
            else:
                source = svc.create_source(
                    training_id,
                    type="user_paste",
                    title=title or "粘贴文本",
                    origin="剪贴板",
                    content=body,
                )
                parsed = svc.parse_source(source.id)
                st.success(f"已导入并解析，共 {len(svc.list_chunks(parsed.id))} 个切片")
                st.rerun()

    with tab_upload:
        uploaded = st.file_uploader("上传 Markdown / 文本文件", type=["md", "markdown", "txt"], key="src_upload_file")
        if uploaded is not None and st.button("解析上传文件", key="src_upload_submit", type="primary"):
            raw = uploaded.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="ignore")
                st.warning("文件不是 UTF-8，已按可读部分导入")
            source = svc.create_source(
                training_id,
                type="user_upload",
                title=uploaded.name,
                origin=uploaded.name,
                content=text,
            )
            parsed = svc.parse_source(source.id)
            st.success(f"已解析 {uploaded.name}，共 {len(svc.list_chunks(parsed.id))} 个切片")
            st.rerun()
        st.caption("PDF / Word / Excel 的解析尚未接入（需要额外依赖）。")

    with tab_ai:
        st.caption("选择后将由 AI 生成训练资料，本阶段仅登记来源，生成逻辑在路径阶段接入。")
        title = st.text_input("资料主题", key="src_ai_title", placeholder="例如：虚拟语气要点")
        if st.button("登记 AI 生成来源", key="src_ai_submit", type="primary"):
            source = svc.create_source(
                training_id, type="ai_generated", title=title or "AI 生成资料", origin="ai"
            )
            svc.parse_source(source.id)
            st.success("已登记 AI 生成来源（无原文，训练项将标记「AI 生成，无原文出处」）")
            st.rerun()


def _render_source_list(training_id: int) -> None:
    sources = svc.list_sources(training_id)
    if not sources:
        st.info("还没有资料。用下面的入口添加一份。")
        return

    rows = []
    for source in sources:
        chunk_count = len(svc.list_chunks(source.id, limit=1000))
        rows.append(
            {
                "ID": source.id,
                "标题": source.title,
                "类型": _TYPE_LABELS.get(source.type, source.type),
                "切片数": chunk_count,
                "状态": _STATUS_LABELS.get(source.parse_status, source.parse_status),
                "范围": source.scope,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)
    if any(source.parse_status == "failed" for source in sources):
        for source in sources:
            if source.parse_status == "failed":
                st.error(f"#{source.id} {source.title} 解析失败：{source.parse_error or '未知原因'}")


def _render_source_detail(training_id: int) -> None:
    sources = svc.list_sources(training_id)
    if not sources:
        return

    labels = {f"#{s.id} · {s.title}": s for s in sources}
    picked = st.selectbox("查看切片", list(labels), key="src_detail_pick")
    source = labels[picked]

    if source.type == "ai_generated" and not source.snapshot_text:
        st.caption("🤖 AI 生成来源没有原文，训练项会标记「AI 生成，无原文出处」。")
        return

    chunks = svc.list_chunks(source.id, limit=1000)
    if not chunks:
        st.caption("该来源还没有切片。")
        return

    grouped: dict[str, list] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.heading_path or "（未分节）", []).append(chunk)

    st.caption(f"共 {len(chunks)} 个切片，分布在 {len(grouped)} 个标题下")
    for heading, items in grouped.items():
        with st.expander(f"{heading}（{len(items)} 段）", expanded=False):
            for chunk in items:
                st.markdown(f"**#{chunk.ordinal}** · {chunk.char_count} 字")
                st.text(chunk.text[:800] + ("…" if chunk.char_count > 800 else ""))


def render() -> None:
    """渲染资料来源页。"""
    st.title("📚 训练资料来源")
    training = _resolve_training()
    if training is None:
        return

    if not is_generation_ready(training.status):
        st.warning(
            f"训练 #{training.id} 当前状态是 `{training.status}`。"
            "请先在「新建」里确认训练目标，确认后才能选择或导入资料。"
        )
        return

    st.caption(f"训练 #{training.id} · {training.topic} · 状态 `{training.status}`")
    st.markdown("### 已有资料")
    _render_source_list(training.id)

    st.markdown("### 添加资料")
    _render_add_forms(int(training.id))

    st.markdown("### 切片预览")
    _render_source_detail(int(training.id))


__all__ = ["render"]
