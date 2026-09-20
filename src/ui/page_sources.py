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


def _flash(message: str, level: str = "success") -> None:
    """暂存一条提示，等 rerun 之后再显示（否则会被 rerun 冲掉）。"""
    st.session_state["src_flash"] = {"message": message, "level": level}


def _render_flash() -> None:
    payload = st.session_state.pop("src_flash", None)
    if not payload:
        return
    message = str(payload.get("message", ""))
    level = str(payload.get("level", "success"))
    renderer = getattr(st, level, None)
    if callable(renderer):
        renderer(message)
    else:
        st.info(message)


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
    """四类来源的添加入口（阶段 B 起包含网络来源）。"""
    tab_paste, tab_upload, tab_web, tab_ai = st.tabs(
        ["✏️ 粘贴文本", "📎 上传文件", "🌐 网络来源", "🤖 AI 生成"]
    )

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
                _flash(f"已导入并解析，共 {len(svc.list_chunks(parsed.id))} 个切片")
                st.rerun()

    with tab_upload:
        uploaded = st.file_uploader(
            "上传资料文件",
            type=["md", "markdown", "txt", "pdf", "docx", "xlsx"],
            key="src_upload_file",
            help="支持 Markdown / 文本 / PDF / Word / Excel（Excel 按表头识别题干、选项、答案、解析）",
        )
        if uploaded is not None and st.button("解析上传文件", key="src_upload_submit", type="primary"):
            source = svc.create_source_from_file(
                training_id, filename=uploaded.name, data=uploaded.read()
            )
            if source.parse_status == "ok":
                _flash(f"已解析 {uploaded.name}，共 {len(svc.list_chunks(source.id))} 个切片")
            elif source.parse_status == "unsupported":
                _flash(source.parse_error or "该格式暂不支持", "warning")
            else:
                _flash(source.parse_error or "解析失败", "error")
            st.rerun()
        st.caption("扫描件（图片型 PDF）暂不支持，需要 OCR。")

    with tab_web:
        st.caption("粘贴一个网址即可添加为知识来源。会保存当时的正文快照，之后页面变了可手动刷新。")
        url = st.text_input("网址", key="src_web_url", placeholder="https://…")
        if st.button("抓取并添加", key="src_web_submit", type="primary"):
            if not url.strip():
                st.error("请先填入网址")
            else:
                with st.spinner("正在抓取…"):
                    source = svc.fetch_web_source(training_id, url.strip())
                if source.parse_status == "ok":
                    chunks = len(svc.list_chunks(source.id, limit=1000))
                    _flash(f"已抓取 {source.origin_url}，共 {chunks} 个切片")
                else:
                    _flash(source.parse_error or "抓取失败", "error")
                st.rerun()
        st.caption("只抓你给出的这个网址：不跟随页面内链接、不做定时重抓、不绕过反爬。")

    with tab_ai:
        st.caption("选择后将由 AI 生成训练资料，本阶段仅登记来源，生成逻辑在路径阶段接入。")
        title = st.text_input("资料主题", key="src_ai_title", placeholder="例如：虚拟语气要点")
        if st.button("登记 AI 生成来源", key="src_ai_submit", type="primary"):
            source = svc.create_source(
                training_id, type="ai_generated", title=title or "AI 生成资料", origin="ai"
            )
            svc.parse_source(source.id)
            _flash("已登记 AI 生成来源（无原文，训练项将标记「AI 生成，无原文出处」）")
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
                "启用": "✅" if source.enabled else "⏸",
                "范围": source.scope,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

    toggle_labels = {
        f"{'⏸ 停用' if s.enabled else '▶ 启用'} #{s.id} · {s.title[:20]}": s for s in sources
    }
    picked = st.selectbox("启用 / 停用某个来源", ["（不操作）", *toggle_labels], key="src_toggle_pick")
    if picked != "（不操作）":
        source = toggle_labels[picked]
        if st.button("切换", key="src_toggle_apply"):
            svc.set_source_enabled(source.id, not bool(source.enabled))
            _flash("已切换（停用不会删除资料，只是不再参与检索与出题）")
            st.rerun()

    if any(source.type == "web_url" for source in sources):
        web_sources = {f"#{s.id} · {s.title[:24]}": s for s in sources if s.type == "web_url"}
        picked_web = st.selectbox("刷新网页快照", ["（不操作）", *web_sources], key="src_refresh_pick")
        if picked_web != "（不操作）" and st.button("重新抓取", key="src_refresh_apply"):
            with st.spinner("正在重新抓取…"):
                refreshed = svc.refresh_snapshot(web_sources[picked_web].id)
            if refreshed.parse_status == "ok":
                _flash("快照已刷新，切片已更新")
            else:
                _flash(refreshed.parse_error or "刷新失败", "error")
            st.rerun()

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
    _render_flash()
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
