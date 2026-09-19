# goal-clarification Specification

## ADDED Requirements

### Requirement: 用户能用自然语言描述学习内容

系统 SHALL 在新建训练入口提供自由文本输入框，接收用户对学习内容的自然语言描述，
并 MUST 把原始描述完整保留到目标草案的 `content` 字段，不做摘要式改写。

#### Scenario: 接收模糊描述

- **WHEN** 用户在新建训练页输入「我想学虚拟语气」并提交
- **THEN** 系统创建一条 `status=draft` 的训练记录
- **THEN** 原始描述被完整保存，未经过 LLM 摘要

#### Scenario: 输入为空

- **WHEN** 用户提交空白描述
- **THEN** 系统拒绝提交并提示「请用一句话描述你想训练的内容」

### Requirement: 前端必须提供投入参数选择，且允许跳过

系统 SHALL 在新建训练页提供三个结构化控件：`horizon`（周期）、`weekly_frequency`（每周训练次数）、
`daily_budget`（每次训练时长）。每个控件 MUST 带默认值，用户 MUST 可以直接跳过并开始。
系统 MUST NOT 把这三个参数作为追问内容。

#### Scenario: 用户显式选择参数

- **WHEN** 用户在新建训练页选择「2 周 / 每周 5 次 / 每次 30 分钟」
- **THEN** 三个值写入 `goal_json`，`field_sources` 中对应字段标为 `ui_select`

#### Scenario: 用户跳过参数选择

- **WHEN** 用户不修改任何控件直接提交描述
- **THEN** 系统采用默认值（周期 2 周 / 每周 5 次 / 每次 30 分钟）
- **THEN** 对应字段在 `field_sources` 中标为 `default`
- **THEN** 系统不因这三个参数发起追问

### Requirement: 系统只对语义字段追问，且追问有软限与硬限

系统 SHALL 仅对 `level`（目标等级）与 `acceptance`（验收标准）两个语义字段发起追问，
这两项 MUST NOT 由系统默认值替代而不告知用户。

追问 **软限 2 轮**：达到后系统 SHALL 给出建议值，并明确提示「可以直接用系统建议，也可以自己改」。
追问 **硬限 3 轮**：达到后系统 MUST 强制收口，输出草案并对仍缺失的字段标注来源为 `inferred`。

**是否继续追问 MUST 由规则层依据缺失字段与轮次判定，不得由 LLM 自行决定停止。**

#### Scenario: 缺语义字段时追问

- **WHEN** 用户描述「我想学虚拟语气」且草案缺少 `acceptance`
- **THEN** 系统提出一个针对 `acceptance` 的追问，并把 `clarification_rounds` 加 1
- **THEN** 系统不进入关键词生成与训练文件生成阶段

#### Scenario: 到达软限

- **WHEN** 追问轮次达到 2 轮且仍有语义字段缺失
- **THEN** 系统给出建议值并提示「可以直接用系统建议，也可以自己改」
- **THEN** 用户可以直接确认，不被迫继续回答

#### Scenario: 到达硬限

- **WHEN** 追问轮次达到 3 轮且仍有语义字段缺失
- **THEN** 系统输出草案，把缺失字段的来源标为 `inferred`
- **THEN** 系统进入 `pending_confirm` 状态，允许用户直接修改

#### Scenario: LLM 调用失败降级

- **WHEN** `goal_clarification` 用途的 LLM 调用重试后仍失败
- **THEN** 系统降级为表单式追问模板，逐字段向用户提问
- **THEN** 失败记录写入 `llm_calls` 表，但流程不阻塞

### Requirement: 参数优先级固定为用户显式值优先

系统 SHALL 按 **前端显式选择 > 追问得到 > AI 推断** 的优先级合并目标参数。
系统 MUST NOT 让 LLM 输出覆盖用户在界面上显式给定或通过追问确认的值。
每个字段的来源 MUST 记录在 `goal_json.field_sources` 中，取值为
`ui_select` / `user_reply` / `default` / `inferred`。

#### Scenario: AI 不得覆盖用户显式值

- **WHEN** 用户在前端选择「每次 30 分钟」，而 LLM 输出草案给出「每次 60 分钟」
- **THEN** 系统保留 30 分钟，丢弃 LLM 的该字段
- **THEN** `field_sources.daily_budget` 为 `ui_select`

#### Scenario: 推断值必须可识别

- **WHEN** 某字段由系统推断得出
- **THEN** 该字段在草案界面上带「系统建议」标识
- **THEN** `field_sources` 中对应字段为 `inferred`

### Requirement: 用户必须确认目标后才能进入后续流程

系统 SHALL 把目标确认实现为显式状态迁移：训练处于 `draft` 或 `pending_confirm` 状态时，
MUST NOT 生成关键词白名单、MUST NOT 渲染训练文件。确认动作 SHALL 由规则层执行并落库。

#### Scenario: 未确认时阻止后续步骤

- **WHEN** 训练状态为 `draft` 或 `pending_confirm`
- **THEN** 系统不调用关键词生成，也不创建任何训练文件
- **THEN** 页面提示「请先确认训练目标」

#### Scenario: 用户确认目标

- **WHEN** 用户点击「确认目标」
- **THEN** 训练状态由 `pending_confirm` 变为 `confirmed`
- **THEN** 系统写入 `goal_confirmed_at` 时间戳
- **THEN** 系统允许进入关键词生成与文件生成阶段

#### Scenario: 用户修改目标

- **WHEN** 用户在 `pending_confirm` 状态下修改任一目标字段
- **THEN** 系统重新生成草案并保持 `pending_confirm` 状态
- **THEN** `goal_confirmed_at` 保持为空

#### Scenario: 非法状态迁移被拒绝

- **WHEN** 代码尝试把 `confirmed` 直接迁回 `draft`
- **THEN** 状态迁移函数拒绝该操作并记录一条警告日志

### Requirement: 目标确认后必须留存快照

系统 SHALL 在确认时把目标草案以 JSON 形式写入 `trainings.goal_json`，并 MUST 在快照内包含
`schema_version` 字段，以便后续结构变更时做兼容读取。

#### Scenario: 快照写入

- **WHEN** 用户确认目标
- **THEN** `trainings.goal_json` 包含 `content` / `level` / `horizon` / `weekly_frequency` /
  `daily_budget` / `acceptance` / `field_sources` / `schema_version`
- **THEN** 读取该训练的任意页面都能取到确认时的目标，不受后续 LLM 生成结果影响

#### Scenario: 确认后可追溯

- **WHEN** 用户或开发者查看该训练
- **THEN** 可看到 `goal_confirmed_at`、`clarification_rounds`、完整目标快照与各字段来源
