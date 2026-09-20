# daily-execution Specification

## MODIFIED Requirements

### Requirement: 用户能完成任务并提交学习反馈
系统 SHALL 在任务卡上提供：任务勾选（复习项 + 新学项）、四个快捷信号标签（太简单 / 太难 / 太多了 / 太宽泛）、可选自由文本框，以及三省打卡输入（忠于目标 / 方法有效 / 付诸实践，每项 0-100 字）。
**三省为可选项，信号标签与任务勾选为必做**，任一缺失不得阻塞当日流程。

#### Scenario: 任务勾选持久化
- **WHEN** 用户勾选某任务
- **THEN** 系统写入 `daily_logs` 表：training_id、log_date、task_id、completed=true、completed_at

#### Scenario: 信号一键提交
- **WHEN** 用户点击任一快捷信号标签
- **THEN** 系统写入 `learning_signals` 一条记录，包含信号类型、训练项、提交时间
- **THEN** 不要求用户补充说明

#### Scenario: 三省提交（可选）
- **WHEN** 用户点击「保存三省」
- **THEN** 三省文本与覆盖字段写入 `daily_logs.three_reflections`（JSON），提交时间写入 `daily_logs.reflection_submitted_at`

#### Scenario: 当日首次进入
- **WHEN** `daily_logs` 中当日无记录
- **THEN** 系统为该训练自动创建一条 `log_date=today, completed_count=0` 的占位记录
- **THEN** 当日未提交三省不影响进度统计

### Requirement: 系统依据客观表现与主观信号共同调整
系统 SHALL 在用户完成主动回忆题自评后，记录正确率（0-1）到 `daily_logs.recall_success_rate`。
难度与题量的调整 MUST 同时参考客观表现（准确率、耗时、作答次数）与主观信号。
当两者冲突时，系统 MUST 以客观表现为准，并提示用户存在的差异。

#### Scenario: 正确率记录
- **WHEN** 用户在任务卡上勾选「回忆题 X 答对 / 答错」
- **THEN** 系统计算当日回忆题正确率（答对数 / 总题数）写入 daily_logs

#### Scenario: 双通道调整
- **WHEN** 用户提交信号且该训练项有足够的客观数据
- **THEN** 系统按冲突规则决定调整动作，并写入调整日志

#### Scenario: 冲突时以客观为准
- **WHEN** 用户提交 `too_easy` 但准确率低于 0.6
- **THEN** 系统不提升难度，并提示自评与正确率的差异

#### Scenario: 周复盘数据可用
- **WHEN** 周复盘模块汇总本周数据
- **THEN** `recall_success_rate`、信号记录与测验结果可直接被读取，无需重算
