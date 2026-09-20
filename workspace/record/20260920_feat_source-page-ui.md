# 20260920 · feat · 资料来源页 UI（阶段 A 的 A5）

## 变更摘要

实现资料来源页：三类静态来源的导入入口、资料列表、切片预览。阶段 A 的 UI 部分完成。

## 实现内容

| 文件 | 内容 |
|---|---|
| `src/ui/page_sources.py`（新增） | 资料页：训练选择、来源列表、三个来源 Tab、切片按标题分组展示 |
| `src/main.py` | 注册 `sources` 路由 + 侧边栏「📚 资料」入口 |
| `tests/test_source_page.py`（新增） | 4 项 UI 回归测试（Streamlit AppTest） |

## 验收对应（A5.1–A5.4）

| 项 | 实现 | 验证方式 |
|---|---|---|
| A5.1 三类来源入口 + 资料列表 | 三个 Tab（粘贴 / 上传 / AI 生成）+ `st.dataframe` 列表（ID / 标题 / 类型 / 切片数 / 状态 / 范围） | UI 测试断言 Tab 数量与标签 |
| A5.2 按标题层级展示切片 | 按 `heading_path` 分组，`st.expander` 折叠，每段显示序号与字数 | 导入后断言切片路径为 `第一章 > 1.1 小节` |
| A5.3 未确认目的不给导入入口 | `is_generation_ready(status)` 为假时只显示警告并 return | UI 测试断言 draft 状态下 Tab 数为 0 |
| A5.4 不出现网络来源入口 | 阶段 A 只暴露三类静态来源 | UI 测试断言标签中不含"网络""网址" |

## 影响范围

- 代码：新增 1 个页面模块 + 1 个测试文件，修改 `main.py` 路由
- 测试：累计 **93 passed, 1 skipped, 20 subtests**
- 规格：阶段 A 的 A5 四项完成，剩余 21 项（PDF/Word/Excel 解析、训练项回指落字段、阶段 A 收尾、阶段 B）
- 证据：`workspace/evidence/20260920-资料来源阶段A.md`

## 已知限制

- **PDF / Word / Excel 未接入**：页面上已明确写出"需要额外依赖"，不做静默失败
- 上传只支持 Markdown / txt（UTF-8 或可忽略解码）
- 切片预览每段最多显示 800 字，超出截断（查看完整内容留待后续）

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/ui/page_sources.py` | 新增 |
| `tests/test_source_page.py` | 新增 |
| `src/main.py` | 修改（路由 + 侧边栏） |
| `workspace/store/openspec/changes/training-source-selection/tasks.md` | A5 四项勾选 |

## 关联 OpenSpec change id

`training-source-selection`（阶段 A 接近完成，change 进行中）
