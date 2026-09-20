# 20260920 · feat · 网络来源（阶段 B）

## 变更摘要

实现资料来源的阶段 B：网络来源的抓取、正文抽取、快照保存、失败显式化、启用/停用与手动刷新。
阶段 A + B 的代码部分完成，change **未归档**（还有 3 项依赖外部条件）。

## 实现内容

| 文件 | 内容 |
|---|---|
| `src/services/web_source.py`（新增） | 抓取（15s 超时、浏览器 UA）、正文抽取（stdlib HTMLParser，跳过 script/nav/footer）、失败分类 |
| `src/services/source_service.py` | 新增 `fetch_web_source` / `refresh_snapshot` / `set_source_enabled`；`create_source` 支持 `origin_url`；检索过滤停用来源 |
| `src/db/tables.sql` + `migrate.py` | `sources` 新增 `enabled` 字段；迁移沿用重建表的三件套 |
| `src/ui/page_sources.py` | 新增「🌐 网络来源」Tab、启用/停用切换、刷新快照入口 |
| `tests/test_web_source.py`（新增） | 13 项：正文抽取去噪、URL 校验、空正文判 SPA、快照落库、失败留痕、停用不参与检索、刷新仅限网络来源 |

## 写死的边界（ADR-0008）

1. **只抓用户给出的那一个 URL**：代码里不存在递归抓链接的逻辑
2. **不做定时重抓**：刷新只能由用户在界面上点
3. **不绕过反爬**：401/403/429 直接报"目标站点拒绝访问"，不尝试伪装
4. **正文为空判失败**：提示"该页面需要浏览器渲染，暂不支持"，绝不产出空的可用来源
5. **失败也留记录**：先落一条来源再标 `failed` + 原因，用户在列表里看得到

## 真实抓取验证（非构造数据）

| 网址 | 结果 |
|---|---|
| `https://docs.ankiweb.net/deck-options.html` | ✅ 抽取正文 **37,874 字** |
| `https://example.com` | ✅ 抽取正文 147 字 |
| `https://support.google.com/notebooklm/` | ❌ 明确报错「无法访问该网址：Network is unreachable」 |

第三条正是调研期失败过的站点，现在失败信息可直接展示给用户。

## 关于 `enabled` 字段的坦白

阶段 A 设计时我说"建表就把阶段 B 需要的字段都备好，阶段 B 不用迁移"——
**这个说法不准确**：`enabled`（来源开关）当时没预见，仍然补了一次迁移。
好在迁移三件套（`foreign_keys=OFF` + `legacy_alter_table=ON` + 显式事务）已经验证过，
本次在生产库上执行成功：训练 7 条未变、外键检查 0 问题。

## 影响范围

- 测试：**117 passed, 1 skipped**（本次新增 13 项）
- 数据：生产库 `sources` 表补 `enabled` 字段（该表当时为空，无数据风险）
- 规格：`training-source-selection` 完成 **36/40** 项
- 证据：`workspace/evidence/20260920-资料来源阶段A.md`（阶段 B 数据待并入）

## 未完成（3 项，均依赖外部条件）

| 项 | 阻塞原因 |
|---|---|
| A4.1 训练项落 `source_chunk_ids` | `training_items` 表属 `training-path-generation`，未建 |
| A6.2 真实资料解析统计 | 需要你提供真实 PDF / Word / Excel 样本 |
| B3.2 FTS5 召回对照实验 | 需要真实资料 + 人工标注的问题集 |

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/web_source.py` | 新增 |
| `src/services/source_service.py` | 修改 |
| `src/db/tables.sql`、`src/db/migrate.py` | 修改（`enabled` 字段） |
| `src/ui/page_sources.py` | 修改 |
| `tests/test_web_source.py` | 新增 |
| `tests/test_source_page.py` | 修改（Tab 由 3 个变 4 个） |

## 关联 OpenSpec change id

`training-source-selection`（阶段 A + B 代码完成，未归档）
