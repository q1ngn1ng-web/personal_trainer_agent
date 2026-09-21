"""轻量页面组件：把"页面骨架"统一起来，避免每个页面各写一套标题/指标/卡片。"""
from __future__ import annotations

from typing import Iterable

import streamlit as st

_STATUS_TONE: dict[str, str] = {
    "ok": "tc-badge-ok",
    "run": "tc-badge-run",
    "wait": "tc-badge-wait",
    "warn": "tc-badge-warn",
    "done": "tc-badge-done",
}


def page_header(title: str, subtitle: str = "", chips: Iterable[str] = ()) -> None:
    """页面顶部：标题 + 一行说明 + 可选特性标签。"""
    chip_html = "".join(f'<span class="tc-chip">{chip}</span>' for chip in chips)
    st.markdown(
        f"""
        <div class="tc-hero">
          <h1>{title}</h1>
          <p class="tc-sub">{subtitle}</p>
          <div class="tc-chips">{chip_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str, hint: str = "") -> None:
    """分区标题（比 st.subheader 更紧凑，可带一句灰色说明）。"""
    hint_html = f'<span class="tc-hint">{hint}</span>' if hint else ""
    st.markdown(
        f'<div class="tc-section"><span class="tc-title">{title}</span>{hint_html}</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, tone: str = "wait") -> str:
    """返回一个状态徽标的 HTML 片段（用在 markdown 里）。"""
    return f'<span class="tc-badge {_STATUS_TONE.get(tone, "tc-badge-wait")}">{text}</span>'


def stat_cards(items: Iterable[tuple[str, object, str]]) -> None:
    """一行指标卡：``(标签, 值, 说明)``。"""
    entries = list(items)
    if not entries:
        return
    columns = st.columns(len(entries))
    for column, (label, value, hint) in zip(columns, entries):
        with column:
            st.metric(label, value)
            if hint:
                st.caption(hint)


def card():
    """带边框的卡片容器（配合 `with card():` 使用）。"""
    return st.container(border=True)


__all__ = ["badge", "card", "page_header", "section", "stat_cards"]
