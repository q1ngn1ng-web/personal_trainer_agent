# Spec: daily-execution

## ADDED Requirements

### Requirement: 系统呈现今日任务卡
系统 SHALL 根据「复习日历」（05_主动回忆题 + 04_复习日历）抽取当前日期的待办任务，以单一页面（今日任务卡）呈现。

#### Scenario: 任务抽取
- **WHEN** 用户打开任意训练主页（status=active）
- **THEN** 系统读取该训练的复习日历，抽取今天应复习 / 新学的内容
- **THEN** 任务卡展示：复习项、新学项、主动回忆题、训练进度摘要

#### Scenario: 间隔算法生效
- **WHEN** 训练已运行 N 天（N ≥ 1）
- **THEN** 复习项按 SM-2 简化间隔（1-3-7-15-30）从最后学习日 + 间隔 ≤ 今天的项目中抽取
- **THEN** 不存在今日应复习项时，新学项成为主要任务

#### Scenario: 内容维度分布
- **WHEN** 抽取今日任务
- **THEN** 概念 / 读代码 / 写代码三类任务按 3:4:3 比例分配（若该日任务 ≥ 5）

### Requirement: 用户能勾选完成任务并填写三省
系统 SHALL 在任务卡上提供：任务勾选（复习项 + 新学项）、三省打卡输入（忠于目标 / 方法有效 / 付诸实践，每项 0-100 字）。

#### Scenario: 任务勾选持久化
- **WHEN** 用户勾选某任务
- **THEN** 系统写入 `daily_logs` 表：training_id、log_date、task_id、completed=true、completed_at

#### Scenario: 三省提交
- **WHEN** 用户点击「保存三省」
- **THEN** 三省文本与覆盖字段写入 `daily_logs.three_reflections`（JSON），提交时间写入 `daily_logs.reflection_submitted_at`

#### Scenario: 当日首次进入
- **WHEN** `daily_logs` 中当日无记录
- **THEN** 系统为该训练自动创建一条 `log_date=today, completed_count=0` 的占位记录

### Requirement: 系统根据回忆题正确率动态微调
系统 SHALL 在用户完成主动回忆题自评后，记录正确率（0-1）到 `daily_logs.recall_success_rate`。

#### Scenario: 正确率记录
- **WHEN** 用户在任务卡上勾选「回忆题 X 答对 / 答错」
- **THEN** 系统计算当日回忆题正确率（答对数 / 总题数）写入 daily_logs

#### Scenario: 周复盘数据可用
- **WHEN** 周复盘模块汇总本周数据
- **THEN** `recall_success_rate` 可直接被读取，无需重算

### Requirement: 完成任务后引导领取奖励
系统 SHALL 在用户当日所有必做任务勾选完成且三省提交后，展示奖励领取入口。

#### Scenario: 满足条件显示奖励按钮
- **WHEN** 用户当日所有必做任务勾选完成且三省提交
- **THEN** 任务卡显示「领取今日奖励」按钮，点击后跳转 `07_奖励机制.md` 对应小节

#### Scenario: 未满足条件不显示
- **WHEN** 必做任务未全部完成 或 三省未提交
- **THEN** 任务卡不显示「领取今日奖励」按钮，显示「还需完成 X 项 / 提交三省」提示