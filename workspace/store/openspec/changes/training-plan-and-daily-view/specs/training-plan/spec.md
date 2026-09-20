# training-plan Specification

## ADDED Requirements

### Requirement: 路径确认后生成训练计划（排期）

系统 SHALL 在用户确认训练路径后生成训练计划，把路径中的训练项排到具体日期。
排期 MUST 由规则层计算，MUST NOT 由 LLM 决定或由 LLM 输出日期。

排期 MUST 以**训练创建日期**为锚点，按距锚点的相对天数计算练习日：
第 1 次练习 SHALL 落在创建日的次日，之后按 `7 / weekly_frequency` 天的节奏递推；当 `weekly_frequency < 7` 时 MUST 存在休息日。
练习日 MUST NOT 依赖自然周的星期几，也 MUST NOT 对周末做特殊处理。
排期生成时若锚点已过去，系统 MUST 跳过已经过去的练习日并从当天起继续对齐，MUST NOT 把训练项排进过去的日期。
每个练习日的计划项总预计时长 MUST NOT 超过 `daily_budget_minutes`；阶段顺序 MUST 作为硬约束（前一阶段尚有未排期的项时，后一阶段的项 MUST NOT 排在更早的日期）。

#### Scenario: 按距创建日的相对天数排出练习日

- **WHEN** 一个训练在 9 月 20 日创建、路径的 `weekly_frequency = 3`
- **THEN** 练习日为 9 月 21、23、26、28、30 日、10 月 3 日……
- **THEN** 任意连续 7 天内恰好有 3 个练习日，其余日期为休息日

#### Scenario: 锚点已过去

- **WHEN** 训练在 9 月 20 日创建，用户在 9 月 26 日才确认路径并生成计划
- **THEN** 计划中不存在早于 9 月 26 日的计划项
- **THEN** 从 9 月 26 日起继续按同一节奏对齐练习日

#### Scenario: 单日不超预算

- **WHEN** 某练习日的 `daily_budget_minutes = 30`
- **THEN** 该日计划项的预计时长合计不超过 30 分钟
- **THEN** 超出容量的训练项被排到下一个练习日，而不是挤进当天

#### Scenario: 路径偏松

- **WHEN** 全部训练项排完后仍有剩余练习日
- **THEN** 系统提示"可增加内容或减少投入"，MUST NOT 自动补题

### Requirement: 计划项以日期为键，可跨训练聚合

系统 SHALL 以 `plan_items` 记录（日期 × 训练 × 训练项）的计划项，并 SHALL 支持按 `plan_date` 跨训练聚合查询。
每一计划项 MUST 记录所属训练、训练项、类型（新学 / 复习 / 测验）、状态与预计时长。

#### Scenario: 跨训练聚合

- **WHEN** 两个训练在同一天各有计划项
- **THEN** 系统能一次查出该日全部计划项，并按训练分组呈现
- **THEN** 合计时长可被计算

#### Scenario: 计划项去重

- **WHEN** 同一训练项在同一日期被重复生成
- **THEN** 系统 MUST NOT 产生两条计划项

### Requirement: 间隔复习由计划插入

当某训练项被标记为「练过」时，系统 SHALL 以**练过当天**为起点，把该训练项的复习项写入训练计划：
复习日期 SHALL 为练过日 + 1 / + 3 / + 7 / + 15 / + 30 天。
复习项 MUST 按上述日期直接落位，MUST NOT 因为该日不是练习日而挪动（复习当日即成为练习日）。
若当日复习项与已排新学项合计超出 `daily_budget_minutes`，系统 MUST 顺延**新学项**，MUST NOT 挪动复习项。
当日复习项的条数 MUST NOT 超过当日计划项总数的一半，且 MUST NOT 超过 2 条。

#### Scenario: 复习从练过当天起算

- **WHEN** 某训练项在 9 月 20 日被标记为「练过」
- **THEN** 系统在 9 月 21、23、27 日、10 月 5 日、10 月 20 日安排复习项

#### Scenario: 复习落在休息日

- **WHEN** 按间隔算出的复习日不是练习日
- **THEN** 该日仍安排这条复习项（当日成为练习日）

#### Scenario: 复习与新学撞车

- **WHEN** 复习项要插入的那一天容量不足以同时容纳新学项
- **THEN** 被顺延的是新学项，复习项的日期不变

### Requirement: 勾选表示「练过」，达标由判定写入

用户勾选计划项 SHALL 表示**练过**：系统 SHALL 把计划项标记为 `practiced` 并把对应训练项标记为 `practiced`，
同时记录 `practiced_at`。系统 MUST NOT 因用户勾选而把训练项标记为「达标」。
「达标」状态 SHALL 只能由达标判定写入。

取消勾选 SHALL 把计划项恢复为 `planned`，且 MUST NOT 抹掉已有的 `practiced_at` 历史。

#### Scenario: 勾选不产生达标

- **WHEN** 用户勾选某个计划项
- **THEN** 计划项状态为 `practiced`，训练项状态为 `practiced`
- **THEN** 训练项 MUST NOT 变为 `passed`

#### Scenario: 取消勾选保留历史

- **WHEN** 用户取消勾选一个之前勾过的计划项
- **THEN** 计划项状态回到 `planned`
- **THEN** 该计划项的 `practiced_at` 仍可查到

### Requirement: 未完成的计划项必须显式顺延，顺延方式由用户选择

到期未被勾选的计划项 MUST 继续出现在任务卡中（作为"待补"），MUST NOT 被自动删除、跳过或静默改期。
用户 SHALL 能选择：把待补项顺延到今天、保持原位、或标记跳过（跳过 MUST 记录原因）。
系统 MUST NOT 自动延长训练周期或自动减少训练项总量。

#### Scenario: 待补不消失

- **WHEN** 用户昨天有 2 项未勾选
- **THEN** 今天任务卡显示这 2 项为待补，并能直接勾选

#### Scenario: 跳过不等于知识点完成

- **WHEN** 用户标记某计划项跳过
- **THEN** 系统记录跳过原因
- **THEN** 该训练项 MUST NOT 因此被计为已覆盖 / 已达标

### Requirement: 训练计划变更必须留痕

任何计划重排（生成 / 投入参数变更 / 结构性调整 / 用户手动顺延）SHALL 记录触发原因与调整前后的取值，
并 SHALL 保留已练过的计划项与其日期不变。

#### Scenario: 重排保留历史

- **WHEN** 用户把每周次数从 3 改为 5
- **THEN** 已标记为「练过」的计划项日期不变
- **THEN** 未练的计划项按新频率重排，且能查到变更原因

#### Scenario: 结构性调整落到排期

- **WHEN** 规则层裁定 `reduce_load`（用户反馈"太多了"且满足触发条件）
- **THEN** 次日计划项条数下降，被削减的项顺延而不是删除
- **THEN** 调整日志记录调整前后的条数
