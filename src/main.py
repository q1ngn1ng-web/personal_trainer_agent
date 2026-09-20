"""训练教练 MVP · Streamlit 主入口与路由

根据 ?page= 查询参数路由到对应的页面渲染器：
  - home (default)         → page_home
  - new_training           → page_new_training
  - sources + ?training_id → page_sources
  - detail + ?training_id  → page_training
  - daily + ?training_id   → page_daily
  - review + ?training_id  → page_review

侧边栏（常驻导航）：所有页面都可见，提供主导航 + 训练列表入口。

启动：uv run streamlit run src/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 把项目根目录放到 sys.path 最前，让 `from src.X import Y` 能解析。
# Streamlit 子进程不一定会继承 uv run 注入的 PYTHONPATH，显式注入最稳。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 项目根目录 = src 的父目录
ROOT = _PROJECT_ROOT

import streamlit as st  # noqa: E402

# 确保 DB schema 在启动时存在
from src.db.sqlite import init_db  # noqa: E402

init_db()


PAGES: dict[str, callable] = {}
_SIDEBAR_MAX_TRAININGS: int = 8


def _register_pages() -> None:
    """延迟导入页面模块以减少冷启动时间。"""
    global PAGES
    if PAGES:
        return
    from src.ui.page_home import render as render_home
    from src.ui.page_new_training import render as render_new_training
    from src.ui.page_sources import render as render_sources
    from src.ui.page_training import render as render_training
    from src.ui.page_daily import render as render_daily
    from src.ui.page_review import render as render_review

    PAGES = {
        "home": render_home,
        "new_training": render_new_training,
        "sources": render_sources,
        "detail": render_training,
        "daily": render_daily,
        "review": render_review,
    }


def _goto(page: str, training_id: int | None = None) -> None:
    """清空 query_params、设置新目标、触发 rerun。sidebar 跳转统一走这里。"""
    for key in list(st.query_params.keys()):
        del st.query_params[key]
    st.query_params["page"] = page
    if training_id is not None:
        st.query_params["training_id"] = str(training_id)
    st.rerun()


def _render_sidebar() -> None:
    """常驻侧边栏：主导航 + 训练列表入口。所有页面共享。"""
    from src.db.queries import list_trainings

    current_page = str(st.query_params.get("page", "home"))
    current_training_id = str(st.query_params.get("training_id", ""))

    with st.sidebar:
        st.markdown("## 🎯 训练教练")
        st.caption(f"当前页：`{current_page}`")
        st.markdown("---")

        # 主导航
        st.markdown("### 📍 导航")
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "🏠 首页",
                key="nav_home",
                width='stretch',
                type="primary" if current_page == "home" else "secondary",
            ):
                _goto(page="home")
        with col2:
            if st.button(
                "➕ 新建",
                key="nav_new",
                width='stretch',
                type="primary" if current_page == "new_training" else "secondary",
            ):
                _goto(page="new_training")

        if st.button("📚 资料", key="nav_sources", width="stretch",
                     type="primary" if current_page == "sources" else "secondary"):
            _goto(page="sources", training_id=int(current_training_id) if current_training_id else None)

        st.markdown("---")

        # 训练列表
        st.markdown("### 📚 训练列表")
        trainings = list_trainings()
        if not trainings:
            st.caption("（还没有训练）")
        else:
            for t in trainings[:_SIDEBAR_MAX_TRAININGS]:
                is_active = current_training_id == str(t.id)
                topic_label = (t.topic or "未命名")[:18]
                prefix = "●" if is_active else "○"
                if st.button(
                    f"{prefix} {topic_label}",
                    key=f"nav_t_{t.id}",
                    width='stretch',
                    type="primary" if is_active else "secondary",
                    help=f"id={t.id} · status={t.status} · baseline={t.baseline_score}",
                ):
                    _goto(page="detail", training_id=int(t.id))
            if len(trainings) > _SIDEBAR_MAX_TRAININGS:
                st.caption(f"…还有 {len(trainings) - _SIDEBAR_MAX_TRAININGS} 个训练")


def main() -> None:
    """Streamlit 入口：按 query param 路由到对应页面。"""
    st.set_page_config(
        page_title="训练教练 MVP",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _register_pages()
    _render_sidebar()

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
