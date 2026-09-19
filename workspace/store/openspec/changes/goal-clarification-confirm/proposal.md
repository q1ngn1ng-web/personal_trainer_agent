# goal-clarification-confirm · 目标澄清与确认

## Why

用户描述学习内容时天然不完整："我想学虚拟语气"没有说明目标等级、周期、应用场景和验收标准。
现有流程只做一次性"主题是否具体"校验（`src/services/topic_validation.py`），**不能追问**，
于是计划生成只能退化为固定模板——这正是"训练路径不随目标变化"的根因。

但追问不是收参数的唯一手段：**用户的投入承诺（练多久、每周几次、每次多久）是选择，不是知识问题**，
应该让用户在前端几秒选完，而不是让 AI 一轮轮问出来。AI 真正需要追问的只有两件事：
练到什么程度、怎么算学会。

## What Changes

- 前端新增**投入参数选择**：周期、每周训练次数、每次时长（单选 + 默认值，用户可直接跳过）
- 新增**目标澄清会话**：只针对 `level`（目标等级）与 `acceptance`（验收标准）追问，
  **软限 2 轮、硬限 3 轮**（软限到达后给出建议值并提示可直接采用）
- 确定参数优先级铁律：**前端显式选择 > 追问得到 > AI 推断**；AI MUST NOT 覆盖用户显式给定的值，
  推断值在快照里标 `inferred`
- AI 负责**生成训练计划**：把「周期 × 每周次数」拆成阶段与训练项（属于下一次 change 的路径生成）
- 新增**用户确认节点**：确认落库并生成快照，未确认不得进入后续生成
- `trainings` 表新增 `draft` / `pending_confirm` 状态与 `goal_json`、`goal_confirmed_at`、`clarification_rounds`
- 新增 LLM 用途 `goal_clarification`，走统一客户端 + JSON Schema + `llm_calls` 审计
- 修改 `trainer-generation`：新建训练必须先经过澄清与确认
- 不变：**LLM 只产出草案与追问，状态迁移由规则层执行**（沿用 ADR-0001）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 投入参数走前端结构化选择 | 全部用追问获取 | 周期/次数/时长是用户的承诺而非知识问题，追问等于把设计问题推给用户；同类产品普遍用结构化控件 |
| 只对 `level` 与 `acceptance` 追问 | 五个字段全部追问 | 每一轮追问都是一次流失机会，把能选的变成问的最不划算 |
| 软限 2 轮 + 硬限 3 轮 | 单一硬上限 5 轮 | 只有硬限时用户到第 5 轮才发现白问；软限在第 2 轮就给默认值并允许直接采用 |
| 状态机显式加 `pending_confirm` | UI 层一个"已确认"复选框 | 状态不落库就无法阻止后续步骤被跳过，也无法追溯评测是按哪个目标算的 |

详见 `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md` 与
`workspace/decisions/ADR-0005-投入参数走前端选择追问只用于语义澄清.md`。

## 非目标（Non-goals）

- 不做语音、面部表情等多模态输入
- **不做"由 AI 自由决定训练周期"**——周期由用户选择，AI 只能填用户没给的默认值
- 不做训练资料来源选择（下一次 change）
- 不做训练路径动态生成（下一次 change，本 change 只把目标与参数准备好）
- 不引入 embedding / RAG——本 change 不触发 ADR-0002 的重评估条件
- 不做多用户、多租户、权限体系
- 不重构 `src/` 下的 demo 代码

## Capabilities

### New Capabilities

- `goal-clarification`: 目标澄清与确认——前端投入参数选择、针对语义字段的多轮追问、
  结构化目标草案、用户确认与快照落库

### Modified Capabilities

- `trainer-generation`: 新建训练入口增加"必须先确认目标"的前置约束

## Impact

- **代码**：`src/ui/page_new_training.py`（改造为「参数选择 → 追问 → 确认」三步）、
  `src/services/`（新增澄清服务 + 参数合并逻辑）、`src/llm/prompts.py` 与 `src/llm/schema.py`
  （新增用途）、`src/db/`（迁移）
- **数据**：`trainings` 表新增 `goal_json`（含 `horizon` / `weekly_frequency` / `daily_budget` /
  `level` / `acceptance` / `field_sources` / `schema_version`）、`goal_confirmed_at`、
  `clarification_rounds`；需要迁移脚本，`data/trainer.db` 不提交 git
- **依赖**：无新增第三方依赖
- **API**：无（当前项目没有 API 层）
- **测试**：状态机迁移、参数合并优先级、追问轮次上限的纯函数单测
- **证据**：澄清完成率、平均追问轮次、默认值采用率、用户事后修改率——**待实现后测量，当前一律标【待验证】**
