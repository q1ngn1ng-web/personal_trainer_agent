"""全局视觉层：主题 CSS 与页面骨架样式。

前端路线 A（留在 Streamlit、先把视觉做起来）：主题配置在 `.streamlit/config.toml`，
细节样式集中在这里注入，页面只负责结构与内容。
"""
from __future__ import annotations

import streamlit as st

APP_CSS = """
<style>
/* ---------- 布局与留白 ---------- */
.block-container {
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1180px;
}
h1, h2, h3 { letter-spacing: -0.01em; }
h1 { font-size: 1.9rem !important; margin-bottom: 0.2rem !important; }
h2 { font-size: 1.25rem !important; margin-top: 0.4rem !important; }
h3 { font-size: 1.05rem !important; }
hr { margin: 1.4rem 0 !important; border-color: #e5e9f0; }

/* ---------- 顶部 hero ---------- */
.tc-hero {
    padding: 4px 0 12px 0;
}
.tc-hero h1 {
    margin: 0 0 6px 0;
    font-size: 1.95rem;
    font-weight: 700;
}
.tc-hero .tc-sub {
    color: #64748b;
    font-size: 0.95rem;
    margin: 0;
}
.tc-chips { margin-top: 12px; }
.tc-chip {
    display: inline-block;
    background: #eef2ff;
    color: #3730a3;
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 0.78rem;
    margin-right: 6px;
    margin-bottom: 6px;
}

/* ---------- 分区标题 ---------- */
.tc-section {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin: 6px 0 2px 0;
}
.tc-section .tc-title { font-size: 1.15rem; font-weight: 650; }
.tc-section .tc-hint { color: #94a3b8; font-size: 0.82rem; }

/* ---------- 指标卡 ---------- */
div[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e8ecf3;
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
div[data-testid="stMetricLabel"] p { font-size: 0.82rem !important; color: #64748b !important; }
div[data-testid="stMetricValue"] { font-size: 1.35rem !important; }

/* ---------- 卡片容器（st.container(border=True)） ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid #e8ecf3 !important;
    border-radius: 14px !important;
    background: #ffffff;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    padding: 4px 6px;
}

/* ---------- 按钮 ---------- */
.stButton > button, .stDownloadButton > button {
    border-radius: 9px;
    border: 1px solid #dfe5ee;
    font-weight: 550;
}
.stButton > button[kind="primary"] {
    border: none;
    box-shadow: 0 1px 2px rgba(37, 99, 235, 0.25);
}

/* ---------- 展开块 ---------- */
div[data-testid="stExpander"] {
    border: 1px solid #e8ecf3;
    border-radius: 12px;
    margin-bottom: 8px;
    overflow: hidden;
}
div[data-testid="stExpander"] summary { font-weight: 550; }

/* ---------- 侧边栏 ---------- */
[data-testid="stSidebar"] {
    background: #f8fafc;
    border-right: 1px solid #e8ecf3;
}
[data-testid="stSidebar"] .stButton > button { text-align: left; }

/* ---------- 提示条 ---------- */
div[data-testid="stAlert"] { border-radius: 10px; }

/* ---------- 进度条 ---------- */
div[data-testid="stProgress"] > div > div > div { background: #2563eb; }

/* ---------- 隐藏默认噪音（注意：只有这里没被隐藏时侧边栏才能被重新展开） ---------- */
#MainMenu,
footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
    visibility: hidden;
}
/* 顶部条保留但透明：侧边栏的展开/收起按钮在它里面，整块隐藏会让侧边栏收不回来 */
header[data-testid="stHeader"] {
    background: transparent;
    box-shadow: none;
}
/* 侧边栏折叠时的展开按钮必须始终可点 */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"] {
    visibility: visible !important;
    display: flex !important;
    opacity: 1 !important;
}

/* ---------- 状态徽标 ---------- */
.tc-badge {
    display: inline-block;
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 0.76rem;
    font-weight: 600;
}
.tc-badge-ok   { background: #dcfce7; color: #166534; }
.tc-badge-run  { background: #dbeafe; color: #1d4ed8; }
.tc-badge-wait { background: #f1f5f9; color: #475569; }
.tc-badge-warn { background: #fef3c7; color: #92400e; }
.tc-badge-done { background: #ede9fe; color: #5b21b6; }
</style>
"""


def inject() -> None:
    """注入全局样式（每次脚本运行调用一次即可）。"""
    st.markdown(APP_CSS, unsafe_allow_html=True)


__all__ = ["APP_CSS", "inject"]
