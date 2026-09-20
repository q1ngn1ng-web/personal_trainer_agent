# 20260920 · feat · 训练路径生成

## 变更摘要

实现 `training-path-generation` 的核心：骨架生成、预算硬校验、训练项落库与来源回指、版本管理、路径页。
这是个人版闭环里最关键的一块——**没有它就没有训练项**。

## 实现内容

| 层 | 文件 | 内容 |
|---|---|---|
| 数据 | `src/db/tables.sql` | 新增 `training_paths` / `path_stages` / `training_items` 三张表 |
| 数据 | `src/db/models.py` | 新增 `TrainingPath` / `PathStage` / `TrainingItem` |
| 数据 | `src/db/migrate.py` | `llm_calls` 去掉 `call_purpose` 的 CHECK（以后新增用途不再需要重建表） |
| LLM | `src/llm/schema.py` / `prompts.py` | 新增用途 `path_skeleton` |
| 服务 | `src/services/path_service.py` | 骨架生成、预算校验、落库、确认、版本、投入微调、回指校验 |
| 服务 | `src/services/source_service.py` | 新增 `existing_chunk_ids_for_training`（解锁 A4.1） |
| UI | `src/ui/page_path.py` | 路径页：阶段与训练项嵌套列表、题型分布、预算占用、投入微调、确认 |
| UI | `src/main.py` | 注册 `path` 路由 + 侧边栏「🧭 路径」 |

## 落地的设计约束

1. **预算由规则算**：周期 × 每周次数 × 每次时长，超支直接拒绝并要求模型压缩重试一次
2. **已掌握跳过、边缘重点、未达先铺垫**：直接消费理解边缘定位的结果
3. **训练项回指来源切片**：`source_chunk_ids` 落库并在路径页显示出处；没有回指的显式标注「AI 生成，无原文出处」，不静默留空
4. **不让模型排日期**：路径只表达阶段与顺序
5. **版本不覆盖**：确认后再生成会产生新版本，旧的标 `superseded`
6. **展示形态按 ADR-0009**：嵌套列表 + 阶段锁定态，不用模型生成的流程图

## A4.1 解锁说明

`training-source-selection` 里那条「训练项增加 `source_chunk_ids`」一直卡着，因为 `training_items` 表属于本 change。
现在表建好了，回指字段与校验（`validate_item_chunk_links`）都已落地并有测试覆盖。

## 影响范围

- 测试：**137 passed, 1 skipped**（本 change 新增 9 项）
- 规格：`training-path-generation` 完成 **16/29**；`training-source-selection` 的 A4.1 解锁
- 数据：生产库新增三张表（`CREATE TABLE IF NOT EXISTS`，无需迁移）

## 未完成（13 项，均已在 tasks.md 留痕）

- 阶段细节滚动生成（`stage_items`）：当前骨架一次生成全部训练项
- 覆盖模式的知识点覆盖校验、超时调整
- 就地微调、难度按作答校准、骨架编辑页
- 难度人工复核与预算偏差统计（需要真实使用数据）

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/path_service.py` | 新增 |
| `src/ui/page_path.py` | 新增 |
| `src/db/tables.sql`、`src/db/models.py`、`src/db/migrate.py` | 修改 |
| `src/llm/schema.py`、`src/llm/prompts.py` | 修改 |
| `src/main.py`、`src/ui/page_new_training.py` | 修改 |
| `tests/test_path_service.py` | 新增 |

## 关联 OpenSpec change id

`training-path-generation`（进行中，16/29）
