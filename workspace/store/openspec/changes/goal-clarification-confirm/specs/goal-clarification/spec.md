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

### Requirement: 系统必须追问以补全目标字段

系统 SHALL 使用 LLM 从用户描述中抽取目标草案，草案包含 `content`、`level`、`horizon`、
`daily_budget`、`acceptance` 五个必填字段。当存在缺失字段时，系统 SHALL 针对缺失字段追问，
单次澄清会话追问轮次上限为 5 轮。**是否继续追问 MUST 由规则层依据缺失字段与轮次判定，不得由 LLM 自行决定停止。**

#### Scenario: 字段缺失时追问

- **WHEN** 用户描述「我想学虚拟语气」且草案缺少 `horizon` 与 `acceptance`
- **THEN** 系统提出一个针对缺失字段的追问，并把 `clarification_rounds` 加 1
- **THEN** 系统不进入关键词生成阶段

#### Scenario: 达到追问上限

- **WHEN** 追问轮次已达 5 轮且仍有缺失字段
- **THEN** 系统输出草案，并对每个缺失字段标注来源为「系统假设」
- **THEN** 系统进入 `pending_confirm` 状态，允许用户直接修改

#### Scenario: LLM 调用失败降级

- **WHEN** `goal_clarification` 用途的 LLM 调用重试后仍失败
- **THEN** 系统降级为表单式追问模板，逐字段向用户提问
- **THEN** 失败记录写入 `llm_calls` 表，但流程不阻塞

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
- **THEN** `trainings.goal_json` 包含五个目标字段与 `schema_version`
- **THEN** 读取该训练的任意页面都能取到确认时的目标，不受后续 LLM 生成结果影响

#### Scenario: 确认后可追溯

- **WHEN** 用户或开发者查看该训练
- **THEN** 可看到 `goal_confirmed_at`、`clarification_rounds` 与完整目标快照
