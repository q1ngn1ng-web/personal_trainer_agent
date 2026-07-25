"""训练教练 MVP · Streamlit 主入口与路由

根据 ?page= 查询参数路由到对应的页面渲染器：
  - home (default)         → page_home
  - new_training           → page_new_training
  - detail + ?training_id  → page_training
  - daily + ?training_id   → page_daily
  - review + ?training_id  → page_review

启动：uv run streamlit run src/main.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# 项目根目录 = src 的父目录
ROOT = Path(__file__).resolve().parent.parent

# 确保 DB schema 在启动时存在
from src.db.sqlite import init_db

init_db()


PAGES: dict[str, callable] = {}


def _register_pages() -> None:
    """延迟导入页面模块以减少冷启动时间。"""
    global PAGES
    if PAGES:
        return
    from src.ui.page_home import render as render_home
    from src.ui.page_new_training import render as render_new_training
    from src.ui.page_training import render as render_training
    from src.ui.page_daily import render as render_daily
    from src.ui.page_review import render as render_review

    PAGES = {
        "home": render_home,
        "new_training": render_new_training,
        "detail": render_training,
        "daily": render_daily,
        "review": render_review,
    }


def main() -> None:
    """Streamlit 入口：按 query param 路由到对应页面。"""
    st.set_page_config(
        page_title="训练教练 MVP",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _register_pages()

    page = st.query_params.get("page", "home")

    if page in PAGES:
        PAGES[page]()
    else:
        # 未知 page → 回退首页并清理参数
        st.query_params["page"] = "home"
        st.warning(f"未知页面 '{page}'，已重定向到首页。")
        PAGES["home"]()


if __name__ == "__main__":
    main()