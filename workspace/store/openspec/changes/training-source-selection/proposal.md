# training-source-selection · 训练资料来源选择

## Why

现在训练资料**全部由 AI 生成**，用户无法带入自己的教材、讲义、题库；生成的内容也没有出处，用户无法核对，我们自己也回答不了"这条训练项是从哪来的"。

下一步的「训练路径生成」需要两个并列输入：**已确认的目的**（`goal-clarification-confirm` 产出）与**可用的资料来源**。目的那一半已经设计完，来源这一半现在是空的。

## What Changes

- 新增 `sources` 与 `source_chunks` 两张表；训练项通过 `source_chunk_ids` **回指原文切片**
- 支持三种来源：**AI 生成** / **用户上传文件**（PDF、Markdown、txt）/ **用户粘贴文本**
- 解析 → 按标题层级与段落边界切片 → 写入 SQLite **FTS5 全文索引**
- 来源选择发生在**目的确认之后、路径生成之前**；未选来源不允许生成路径
- **增量重建**：内容 `checksum` 未变则不重跑解析；变更后列出受影响的训练项，由用户决定保留还是重练
- 明确**不引入向量库与 embedding**（依据见 `workspace/decisions/ADR-0007`）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| **SQLite FTS5 全文检索** | 向量检索 / 混合检索 | 当前单个训练 1-3 份资料、切片数百级；ADR-0002 写的触发条件（跨资料检索、相似题推荐、海量匹配）尚未满足。上向量库要额外引入阈值校准、缓存与调用成本三类问题 |
| 按标题层级 + 段落边界切片 | 固定字数切片 | 教材与讲义的章节结构本身就是语义边界，固定字数会把一个知识点劈成两半 |
| 先支持 PDF / Markdown / txt | 一次覆盖 Word / Excel / 网页抓取 / OCR | 每多一种格式就多一类解析失败模式；先验证"资料 → 训练项"这条链路本身 |
| 来源作为**独立 capability** | 直接修改 `trainer-generation` 的创建流程规格 | `goal-clarification-confirm` 正在修改同一条 Requirement，两边都改同一块会在归档时冲突 |

详见 `workspace/decisions/ADR-0007-资料检索先用FTS5不上向量库.md`。

## 假设（需用户确认）

以下三条是写这份 proposal 时的默认判断，确认后才进入实现：

1. 来源只有三类（AI 生成 / 上传文件 / 粘贴文本），**不做公开教材库或课程标准对接**
2. **允许中途追加来源**，走增量重建 + 影响面提示，而不是必须重建整个训练
3. 一个训练**可以有多个来源**；但一个训练项只回指它实际来源的那些切片

## 非目标（Non-goals）

- 不做向量库、不做 embedding、不做混合检索
- 不做网页抓取、不做扫描件 OCR、不做 Word / Excel
- 不做公开教材库、课程标准或权威知识图谱的对接
- 不做引用一致性校验（答案里每个论断能否回溯到原文）
- 不做多用户共享资料库与权限
- 不做资料的多语言处理

## Capabilities

### New Capabilities

- `source-management`: 资料来源管理——来源登记、解析切片、全文索引、训练项回指、增量重建与影响面提示

### Modified Capabilities

无。有意不改 `trainer-generation`，避免与进行中的 `goal-clarification-confirm` 在归档时冲突；
「来源必须在目的确认之后选择」这条约束写在 `source-management` 自己的 Requirement 里。

## Impact

- **代码**：`src/services/`（新增来源服务与解析管线）、`src/db/`（新增两张表 + FTS5 虚表 + 迁移）、
  `src/ui/`（新增来源选择与资料管理页面）
- **数据**：新增 `sources` / `source_chunks` 表与 FTS5 索引；`checksum` 用于增量重建；
  `data/trainer.db` 不提交 git
- **依赖**：PDF 解析需要引入解析库（具体选型见 ADR-0007，倾向复用 `PythonProject16` 已用过的方案）
- **API**：无（当前项目没有 API 层）
- **测试**：解析与切片、checksum 判定、影响面计算的纯函数单测
- **证据**：解析成功率、切片数分布、解析耗时——**待实测，当前标【待验证】**
