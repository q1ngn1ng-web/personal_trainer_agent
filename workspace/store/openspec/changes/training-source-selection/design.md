# training-source-selection · 设计文档

## Context

### 背景

现有流程的资料**全部由 AI 生成**，`tables.sql` 里 6 张表没有任何与"来源"相关的字段。
后果有两个：用户无法带入自己的教材与讲义；训练项没有出处，既无法核对，也无法在资料更新后追溯影响范围。

同时，下一次 change（训练路径生成）需要两个并列输入——已确认的目的、可用的资料来源。本 change 负责后者。

### 当前状态

- `trainings` 只记录 `topic` 与关键词白名单，没有来源概念
- 训练内容由 `src/services/trainer_service.py` 按固定模板生成
- 无任何检索能力（既没有向量检索，也没有全文检索）
- `goal-clarification-confirm` 已确定：目的确认后才允许进入后续阶段

### 约束

- 沿用 ADR-0001：LLM 只做语义，解析/切片/索引/判定由确定性代码做
- 沿用 ADR-0002：不引入 embedding，除非触发条件满足（本 change 判断为**未触发**）
- 存储仍是 SQLite，不新增外部服务
- 所有 Python 脚本用 uv 运行

### 利益相关方

- 用户本人（自用 + 面试演示）

## Goals / Non-Goals

**Goals:**

- 用户能把教材 / 讲义 / 笔记带进来，并看到它们被拆成了什么
- 每个训练项能回指到原文具体切片，点得回去
- 资料变更后能知道影响了哪些训练项

**Non-Goals:**

- 不做向量检索与混合检索
- 不做 Word / Excel / 网页抓取 / OCR
- 不做引用一致性校验

## Decisions

### D1 表结构

```
sources
  id, training_id, type(ai_generated|user_upload|user_paste),
  title, origin(文件名或说明), checksum, imported_at, parse_status

source_chunks
  id, source_id, ordinal, heading_path, text, char_count

source_chunks_fts        -- FTS5 虚表，索引 text 与 heading_path
  (rowid 关联 source_chunks.id)

training_items（后续路径阶段新建）
  ..., source_chunk_ids   -- JSON 数组，回指来源切片
```

### D2 解析与切片

1. 解析：PDF → Markdown（保留标题层级）；Markdown / txt 直接读取
2. 切片：**先按标题层级切，再按段落边界切**，不用固定字数
3. 每个切片记录 `heading_path`（如 `第三章 > 3.2 虚拟语气 > 用法一`），用于溯源与展示
4. 切片过长（超过设定上限）时递归按段落再切，保留标题前缀
5. 解析失败不阻塞：`parse_status` 记为 `failed` 并保留原始文件路径，界面提示可重试

### D3 检索：SQLite FTS5（本 change 的核心取舍）

| 方案 | 结论 | 理由 |
|---|---|---|
| FTS5 全文检索 | **采用** | 零新增依赖、结果可解释、可单测；当前资料规模（1-3 份、数百切片）完全够用 |
| 向量检索 | 暂不 | 引入 embedding 依赖、阈值校准、缓存与调用成本；ADR-0002 的触发条件未满足 |
| 混合检索 | 暂不 | 是向量检索的超集，同上 |

**重评估触发条件**：当出现"跨多份资料找同类知识点""相似题推荐""单训练切片量超过数千"时，重新评估并新写 ADR。

### D4 训练项回指来源

训练项保存 `source_chunk_ids`，界面上可展开查看原文片段。
由 AI 生成训练项时，**必须把候选切片一并传入 prompt**，并要求模型在输出里标注使用了哪些切片 ID；
模型标注不存在的 ID 时，该标注被丢弃并记一条日志（与字段来源标记同样的处理思路）。

### D5 增量重建与影响面

1. 导入时计算 `checksum`（文件内容或文本的哈希）
2. `checksum` 未变 → 跳过解析，直接复用已有切片
3. 变了 → 重新解析，比对切片集合：新增 / 删除 / 修改
4. 对受影响的训练项给出清单，让用户选择"保留旧训练项"或"标记为重练"
5. **不自动删除**任何训练项——删除是用户的决定

### D6 在流程中的位置

```
描述 → 澄清 → ✅确认目的 → 【本 change：选择/导入来源】→ 生成训练路径 → ...
```

约束：训练处于 `confirmed` 且**没有可用来源**时，不允许进入路径生成。
来源为空与"用户明确选择 AI 生成"是两种不同状态，前者是未完成，后者是有效选择。

### D7 与 `goal-clarification-confirm` 的边界

两个 change 都要参与"新建训练"的流程，但**不改同一条 Requirement**：

- `goal-clarification-confirm` 修改 `trainer-generation` 的「用户能创建新训练主题」
- 本 change 把"来源选择必须在目的确认之后"写进自己的 `source-management` 规格

这样两个 change 可以各自归档，不会产生 delta 冲突。

## Risks / Trade-offs

| 风险 | 影响 | 处理方式 |
|---|---|---|
| FTS5 无法命中同义表达 | 召回不足 | 先量化影响（用真实资料做对照测试）；确认严重再触发 embedding 重评估 |
| 解析质量参差（扫描件、复杂版式） | 切片不可用 | `parse_status` 显式暴露失败；先只支持可解析的 PDF，扫描件明确不支持 |
| AI 标注的切片 ID 不存在 | 回指失效 | 校验 ID 存在性，无效标注丢弃并记日志 |
| 单个切片过长挤占上下文 | 生成质量下降 | 设切片长度上限，超限递归切分 |
| 资料多来源时训练项归属混乱 | 追溯困难 | 一个训练项只回指它实际使用的切片，不绑定"主来源" |

## 关联决策记录

- `workspace/decisions/ADR-0001-llm负责语义-规则负责状态.md`
- `workspace/decisions/ADR-0002-评测用组合分-暂不上embedding.md`（本 change 判断触发条件未满足）
- `workspace/decisions/ADR-0007-资料检索先用FTS5不上向量库.md`（本 change 的核心选型）

## 验收方式

- 单测：切片按标题层级正确分层、checksum 判定、影响面计算、无效切片 ID 被丢弃
- 手动场景：上传一份 PDF，能看到按章节切好的切片列表；训练项点开后能看到对应原文
- 手动场景：重复上传同一文件，第二次应跳过解析（日志可验证）
- 指标：解析成功率、切片数分布、解析耗时、FTS5 命中率——**待实测，当前标【待验证】**
