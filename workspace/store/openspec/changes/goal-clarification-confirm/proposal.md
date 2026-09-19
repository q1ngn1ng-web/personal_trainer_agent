# goal-clarification-confirm · 目标澄清与确认

## Why

用户描述学习内容时天然不完整："我想学虚拟语气"没有说明目标等级、周期、应用场景和验收标准。
现有流程只做一次性"主题是否具体"校验（`src/services/topic_validation.py`），**不能追问**，
于是计划生成只能退化为固定模板——这正是"训练路径不随目标变化"的根因。

先把最前面这一步做实，后面的路径生成、资料选择才有可信输入。

## What Changes

- 新增**目标澄清会话**：自由文本输入 → 最多 5 轮追问 → 产出结构化目标草案
- 新增**用户确认节点**：确认动作落库并生成快照，未确认不得进入后续生成
- `trainings` 表新增 `draft` / `pending_confirm` 状态与目标快照字段（目标 JSON、确认时间、澄清轮次）
- 新增 LLM 用途 `goal_clarification`，走统一客户端 + JSON Schema + `llm_calls` 审计
- 修改 `trainer-generation`：新建训练必须先经过澄清与确认
- 不变：**LLM 只产出草案与追问，状态迁移由规则层执行**（沿用 ADR-0001）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 多轮追问 | 一次性表单收全字段 | 用户说不清自己要什么，表单只能收已知信息，等于把拆解工作还给用户 |
| 澄清结果以 JSON 快照存在 `trainings` | 新建独立目标表 | 当前一个训练只有一个目标，独立表只增加 join 成本；等出现"一训练多目标"再拆 |
| 状态机显式加 `pending_confirm` | UI 层一个"已确认"复选框 | 状态不落库就无法阻止后续步骤被跳过，也无法追溯评测是按哪个目标算的 |

详见 `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md`。

## 非目标（Non-goals）

- 不做语音、面部表情等多模态输入
- 不做训练资料来源选择（下一次 change）
- 不做训练路径动态生成（下一次 change）
- 不引入 embedding / RAG——本 change 不触发 ADR-0002 的重评估条件
- 不做多用户、多租户、权限体系
- 不重构 `src/` 下的 demo 代码

## Capabilities

### New Capabilities

- `goal-clarification`: 目标澄清与确认——自由文本输入、多轮追问、结构化目标草案、用户确认与快照落库

### Modified Capabilities

- `trainer-generation`: 新建训练入口增加"必须先确认目标"的前置约束

## Impact

- **代码**：`src/ui/page_new_training.py`（改造）、`src/services/`（新增澄清服务）、
  `src/llm/prompts.py` 与 `src/llm/schema.py`（新增用途）、`src/db/`（迁移）
- **数据**：`trainings` 表新增字段，需要迁移脚本；`data/trainer.db` 不提交 git
- **依赖**：无新增第三方依赖
- **API**：无（当前项目没有 API 层）
- **测试**：新增状态机迁移与目标字段校验的纯函数单测
- **证据**：澄清完成率、平均追问轮次、用户修改草案比例——**待实现后测量，当前一律标【待验证】**
