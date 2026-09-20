# 20260920 · feat · 资料来源阶段 A（静态层）

## 变更摘要

实现 `training-source-selection` 的阶段 A：资料来源的静态层。
**change 未归档**，阶段 B（网络来源）待做。

## 实现内容

| 层 | 文件 | 内容 |
|---|---|---|
| 数据 | `src/db/tables.sql` | 新增 `sources` / `source_chunks` / `source_chunks_fts`，含同步触发器与索引 |
| 数据 | `src/db/models.py` | 新增 `Source` / `SourceChunk` dataclass |
| 领域 | `src/core/source.py` | 切片、checksum、影响面、切片 ID 校验，全部纯函数 |
| 服务 | `src/services/source_service.py` | 登记 / 解析 / 列表 / 检索 / 影响面 / 回指校验 |
| 测试 | `tests/test_source_service.py` | 17 项：切片纯函数 + 服务 + 边界 |

## 关键设计落地

1. **阶段 A 建表即包含 `web_url` 与 `unsupported`**：阶段 B 只写行为，不需要改数据模型或迁移
2. **FTS5 用 `trigram` 分词**：`unicode61` 会把中文整句当成一个词，中文子串检索必须用 trigram
3. **解析幂等**：`checksum` 未变且上次成功则跳过，不重复切片
4. **解析失败显式化**：`parse_status=failed` + `parse_error`，不阻塞其他来源
5. **检索纯本地**：`search_chunks` 不产生任何 LLM 调用（单测用会抛异常的 `complete` 验证）
6. **影响面只给清单**：`compute_impact` 不删除任何训练项

## 过程中的两次修正

| 问题 | 原因 | 处理 |
|---|---|---|
| `compute_impact` 递归调用自己 | 服务层与领域层同名函数，模块级名字被覆盖 | 领域函数改用 `_core_compute_impact` 别名导入 |
| `compute_impact` 只收 checksum 算不出差异 | 没有新内容就无法比对切片 | 签名改为 `compute_impact(source_id, new_content=None)`，并同步更新 `design.md` |

## 影响范围

- 代码：新增 3 个模块 + 修改 2 个模块；新增 17 项测试（累计 90 项全绿）
- 数据：`data/trainer.db` 执行过一次建表（新增 3 张表，训练数据 3 条未变，外键检查 0 问题）
- 规格：`training-source-selection` 阶段 A 的 15 项任务完成，**25 项待做**
- 证据：`workspace/evidence/20260920-资料来源阶段A.md`

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/core/source.py` | 新增 |
| `src/services/source_service.py` | 新增 |
| `tests/test_source_service.py` | 新增 |
| `src/db/tables.sql`、`src/db/models.py` | 修改 |
| `workspace/store/openspec/changes/training-source-selection/design.md` | 同步 `compute_impact` 签名；取消"冻结"流程表述 |
| `workspace/HANDOFF.md` | 会话分工改为可选，去掉冻结 gate |

## 关联 OpenSpec change id

`training-source-selection`（阶段 A 完成，change 进行中，未归档）
