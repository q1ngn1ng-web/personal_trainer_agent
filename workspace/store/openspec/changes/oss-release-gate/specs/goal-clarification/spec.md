# goal-clarification Specification

## ADDED Requirements

### Requirement: 追问原文随对话历史留存

澄清对话的每一条历史记录 SHALL 同时保存「系统问了什么」与「用户答了什么」。
系统发起追问时 SHALL 把待答问句落到会话状态；用户回答后，该问句 MUST 原样进入
`history`，供下一轮 LLM 调用的 `history` 变量使用。存量没有问句的历史记录 MUST 保持
可读（按空问句渲染），MUST NOT 报错。本要求 MUST NOT 改变追问的软限、硬限与规则层
对"是否继续追问"的判定。

#### Scenario: 第二轮调用能看到第一轮问句

- **WHEN** 第 1 轮系统追问「你希望达到什么程度？」，用户回答「能用就行」
- **THEN** 第 2 轮 `goal_clarification` 调用的 history 文本含「第 1 轮追问: 你希望达到什么程度？」与「用户回答: 能用就行」

#### Scenario: 页面刷新后继续回答

- **WHEN** 用户在第 1 轮被追问后刷新页面，再提交回答
- **THEN** 新增的历史记录仍带第 1 轮的问句

#### Scenario: 存量数据兼容

- **WHEN** 训练的历史状态里没有待答问句（本要求落地之前写入的数据）
- **THEN** 继续澄清不报错，history 文本里该轮的问句为空
