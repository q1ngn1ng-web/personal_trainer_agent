# 2026-07-25 · feat · main.py 加常驻 sidebar 全局导航

## 变更摘要

之前每个页面各自管自己的"返回"按钮，但只有 `page_training` 顶部有。用户从新建训练 → 详情 → 今日训练 → 周复盘走一遍后，没有便捷路径回到首页，需要手动改 URL 或返回浏览器历史。

### 改动

在 `src/main.py` 加 `_render_sidebar()` 和 `_goto()` helper：

- **常驻侧边栏**（`st.sidebar`）—— 所有页面共享
  - 📍 主导航：🏠 首页 / ➕ 新建
  - 📚 训练列表：最近 8 个训练一键跳转，active 训练高亮
- **`_goto(page, training_id)`** helper —— 清空旧 query_params、设新目标、`st.rerun()`

### 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 导航放哪里 | 侧边栏 | Streamlit 原生支持、所有页面可见、不需要每页重复写 |
| 跳转机制 | `query_params` + `st.rerun()` | 与现有路由一致，不引入 `st.switch_page`（那是 Streamlit 多页 app 模式，本项目用单文件 + query_params 自管） |
| 训练列表展示几个 | 8 | 超出后用 caption 提示「…还有 N 个」，避免 sidebar 太长 |
| active 训练如何高亮 | `type="primary"` + `●` 前缀 | 视觉 + 语义双信号 |
| `_goto` 是否清除所有 params | 是 | 避免跨页面状态泄漏（如 `?training_id` 残留在首页） |

## 影响范围

```
src/main.py                  # +_render_sidebar / +_goto / 调用 _render_sidebar
src/main.py:set_page_config  # initial_sidebar_state="expanded"（已存在）
```

未触及：`src/ui/` 下 5 个 page 模块（它们之前各自实现的"返回"按钮保留作为冗余，但 sidebar 是主导航）。

## 相关文件路径

```
src/main.py:13-22    # docstring 加侧边栏说明
src/main.py:48-49    # _SIDEBAR_MAX_TRAININGS 常量
src/main.py:61-77    # _goto helper
src/main.py:80-122   # _render_sidebar
src/main.py:128      # main() 调用 _render_sidebar
```

## 关联的 OpenSpec change id

无（UX 增强，不改 spec 行为边界）

## 验证

```
uv run streamlit run src/main.py --server.headless true
  → 启动无 traceback ✅
  → 侧边栏可见，包含 📍 导航 + 📚 训练列表 ✅
```

回归：30 单测 ✅。

## 启发

1. **路由一致性**：所有跳转走 `_goto()` helper，未来加页面只需更新 PAGES 字典 + sidebar 一处。如果未来有更多路由需求（如 URL 直跳），`_goto` 是单一收敛点
2. **侧边栏 vs 页内按钮**：本次保留 `page_training` 的"← 返回首页"按钮（冗余但不冲突），保证 sidebar collapse 时仍可导航。Phase 2 通用化时再决定要不要去掉冗余

## 后续 TODO

- [ ] Sidebar 加「⚙️ 设置」（暂未做，未来加 prompt 版本切换、模型选择等）
- [ ] Sidebar 训练列表超过 8 个时改为可滚动 `st.container(height=...)`
- [ ] 加「🔍 搜索训练」输入框（>20 个训练时有用）

## Git

```
(待提交) feat(ui): main.py 加常驻 sidebar 导航（主导航 + 训练列表）
```