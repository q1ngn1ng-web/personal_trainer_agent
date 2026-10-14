# on-demand-explanation Specification

## ADDED Requirements

### Requirement: 解析按需生成

系统 SHALL 在用户对某道题请求解析时才生成解析内容，MUST NOT 在出题或作答阶段预先生成。

#### Scenario: 用户请求解析

- **WHEN** 用户在某道题上请求查看解析
- **THEN** 系统基于该题的要点清单与关联资料生成解析

### Requirement: 解析必须引用资料来源

解析内容 SHALL 引用该题关联的资料原文片段作为依据，MUST NOT 仅凭模型自身知识作答。

#### Scenario: 解析可溯源

- **WHEN** 系统生成解析
- **THEN** 解析中包含可回指到资料切片的原文片段

#### Scenario: 无资料可用时如实说明

- **WHEN** 该题没有关联资料片段
- **THEN** 系统 MUST 明确说明依据不足，不得编造来源

### Requirement: 查看解析记录为学习信号

系统 SHALL 记录用户查看解析的行为，并可据此判断知识点困难度。

#### Scenario: 统计解析查看

- **WHEN** 用户查看了某题的解析
- **THEN** 系统记录该行为，并可按题目或知识点统计查看次数
