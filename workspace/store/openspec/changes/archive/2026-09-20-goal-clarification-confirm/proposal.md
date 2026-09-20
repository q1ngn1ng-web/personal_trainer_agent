# goal-clarification-confirm · 目标澄清与确认

## Why

用户描述学习内容时天然不完整："我想学虚拟语气"没有说明目标等级、应用场景和验收标准。
现有流程只做一次性"主题是否具体"校验（`src/services/topic_validation.py`），**不能追问**，
于是后续生成只能退化为固定模板。

这里要划清一条界线：

- **澄清阶段问的是「目的」**：学什么、到什么程度、怎么算学会
- **路径阶段给的是「手段」**：多久、每周几次、每次多久、分几个阶段、每个阶段练什么

把手段塞进澄清阶段，是让用户在还不清楚自己要什么的时候先承诺投入方式；
正确的顺序是**先确认目的，再让 AI 给手段草案、由用户微调**。

本 change 只做**澄清与目的确认**，且必须为下一次 change（训练路径生成）预留好输入。

## What Changes

- 新增**目标澄清会话**：只针对 `level`（目标等级）与 `acceptance`（验收标准）追问，
  **软限 2 轮、硬限 3 轮**（软限到达后给出建议值并提示可直接采用）
- 新增**用户确认节点**：确认目的后落库并生成快照，未确认不得进入后续生成
- `trainings` 表新增 `draft` / `pending_confirm` 状态与 `goal_json`、`goal_confirmed_at`、
  `clarification_rounds`
- 新增 LLM 用途 `goal_clarification`，走统一客户端 + JSON Schema + `llm_calls` 审计
- 修改 `trainer-generation`：新建训练必须先经过澄清与目的确认
- **为下一次 change 预留**：`goal_json` 一旦确认即冻结，训练路径生成以它为唯一输入
- 不变：**LLM 只产出草案与追问，状态迁移由规则层执行**（沿用 ADR-0001）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 澄清阶段**不碰投入参数** | 在澄清页放周期/频次/时长控件 | 那是路径阶段的手段；用户还没确认目的就先填手段，顺序颠倒，且会让澄清页变成表单 |
| 追问范围限定为 `level` 与 `acceptance` | 多个字段都追问 | 只有这两项是"只有用户自己知道、AI 猜不出"的；其余都有合理默认值 |
| 软限 2 轮 + 硬限 3 轮 | 单一硬上限 5 轮 | 只有硬限时用户要到第 5 轮才发现白问；软限在第 2 轮就给建议值并允许直接采用 |
| 状态机显式加 `pending_confirm` | UI 层一个"已确认"复选框 | 状态不落库就无法阻止后续步骤被跳过，也无法追溯后续评测是按哪个目的算的 |

详见 `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md` 与
`workspace/decisions/ADR-0006-投入参数归路径阶段由AI生成用户微调.md`。

## 非目标（Non-goals）

- **不做训练路径生成**——周期、每周次数、每次时长、阶段划分、训练项都属于下一次 change；
  本 change 只负责把它们的输入（已确认的目的）准备好
- 不做训练资料来源选择（更后面的 change）
- 不做语音、面部表情等多模态输入
- 不做"由 AI 单方面决定一切"——路径阶段产出的是**草案**，必须经过用户微调与确认
- 不引入 embedding / RAG——本 change 不触发 ADR-0002 的重评估条件
- 不做多用户、多租户、权限体系
- 不重构 `src/` 下的 demo 代码

## Capabilities

### New Capabilities

- `goal-clarification`: 目标澄清与确认——自由文本输入、针对语义字段的多轮追问、
  结构化目的草案、用户确认与快照落库

### Modified Capabilities

- `trainer-generation`: 新建训练入口增加"必须先确认目的"的前置约束

## Impact

- **代码**：`src/ui/page_new_training.py`（改造为「描述 → 追问 → 目的确认」）、
  `src/services/`（新增澄清服务）、`src/llm/prompts.py` 与 `src/llm/schema.py`（新增用途）、
  `src/db/`（迁移）
- **数据**：`trainings` 表新增 `goal_json`（含 `content` / `level` / `acceptance` /
  `field_sources` / `schema_version`）、`goal_confirmed_at`、`clarification_rounds`；
  需要迁移脚本，`data/trainer.db` 不提交 git
- **依赖**：无新增第三方依赖
- **API**：无（当前项目没有 API 层）
- **测试**：状态机迁移、追问轮次上限、字段来源标记的纯函数单测
- **证据**：澄清完成率、平均追问轮次、草案修改率——**待实现后测量，当前一律标【待验证】**
