# 20260921 · chore · UI 视觉层（主题配置 + 全局样式 + 页面骨架组件）

## 变更摘要

用户反馈"现在的 UI 太丑"。按**前端路线 A**（留在 Streamlit、先把视觉做起来）做了一轮改造：

1. **新增主题配置** `.streamlit/config.toml`：主色 `#2563eb`、浅灰底、统一字体；
   顺带把 `server.headless/address/port` 写进配置——以后 `uv run streamlit run src/main.py` 不加参数也能正常对外访问。
2. **新增全局样式层** `src/ui/theme.py`：卡片（`st.container(border=True)`）圆角与阴影、指标卡、按钮、
   展开块、侧边栏、进度条统一；隐藏 `#MainMenu` / `footer` / 状态挂件等默认噪音；中英混排字号收敛。
3. **新增骨架组件** `src/ui/components.py`：`page_header` / `section` / `stat_cards` / `card` / `badge`，
   把"页面顶部、分区标题、指标行、卡片、状态徽标"统一成一套；页面不再各写一套标题与指标。
4. **重排首页**：hero 文案改成当前链路（不再是过期的"十份 md"），加特性标签；指标行改卡片；
   「今日训练」改成卡片 + 指标 + 主题徽标；训练列表加分区标题。
5. **重排今日任务卡**：标题 + 一句规则说明；顶部换成"今日任务 / 预计用时 / 计划进度"三张指标卡 + 进度条；
   分区编号理顺（1 待补、2 今天到期、3 回忆题、4 测验、5 完成度、6 感受、7 留言、8 奖励）。
6. **路径页**：标题与分区统一走组件；"调整投入"的说明改成 ADR-0021 后的真实含义
   （每次时长是"单日负荷提示阈值"，周期与每周次数已不参与排期）。

## 产出

| 文件 | 内容 |
|---|---|
| `.streamlit/config.toml`（新增） | 主题配色 + 启动参数 |
| `src/ui/theme.py`（新增） | `APP_CSS` 与 `inject()` |
| `src/ui/components.py`（新增） | `page_header` / `section` / `stat_cards` / `card` / `badge` |
| `src/main.py` | 每轮渲染前注入全局样式 |
| `src/ui/page_home.py` | hero、指标、今日训练、训练列表重排 |
| `src/ui/page_daily.py` | 页头 + 指标卡 + 分区编号理顺 |
| `src/ui/page_path.py` | 页头与分区标题统一，投入参数说明更新 |
| `tests/test_plan_page.py` | 首页「今日训练」断言改为兼容新的分区组件（不再依赖 `st.subheader`） |

## 验证

| 项 | 结果 |
|---|---|
| 全量单测 | **210 passed, 1 skipped, 30 subtests**（无回归） |
| 页面导入 | 七个页面 + `theme` / `components` / `main` 全部可导入 |
| 服务 | 已重启并验证 `/_stcore/health` = 200 |

## 影响范围

- **视觉**：整体配色、卡片、间距、图标与状态徽标统一；首页与任务卡是这轮改动最大的两页
- **交互**：无功能变化（除了分区编号更顺）；所有按钮 key、勾选行为、测验流程保持原样
- **部署**：`.streamlit/config.toml` 让"不带参数启动"也能对公网服务
- **未做（留给前端路线 C）**：真正的组件化重构与自由布局——那需要 Vue SPA + API 层（见 ADR-0022 待写）

## 相关文件路径

- 代码：见上表
- 前端路线：路线 A 的取舍见本记录；路线 C（Vue SPA + FastAPI）需要在动工前补 ADR-0022

## 关联 OpenSpec change id

无（仅视觉层，不涉及规格）；不影响进行中的 change
