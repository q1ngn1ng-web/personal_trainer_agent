# performance-driven-scheduling Specification

## ADDED Requirements

### Requirement: 复习间隔随作答表现扩张或重置

每个训练项 SHALL 维护阶梯位置 step（0..4，间隔 [1,3,7,15,30] 天），
由 `practice_attempts` 历史推导（MUST NOT 由 LLM 参与推导）：
轮完成且判 pass → step 前进一档，下一轮到期 = 完成日 + 新档间隔；
轮完成且判 fail → step 归零，下一轮到期 = 完成日 + 1 天；
practice-only 不改变 step。后续轮次的 due_date 在完成事件时重算，
MUST 保留 original_date 记录生成时口径，且重算 MUST 幂等（同一历史重放结果一致）。

#### Scenario: 答对推进阶梯

- **WHEN** 某训练项处于 step 1（间隔 3 天），用户在第 D 天完成该轮且规则层判 pass
- **THEN** step 推进为 2，下一轮到期日为 D+7

#### Scenario: 答错重置阶梯

- **WHEN** 某训练项处于 step 3，用户判 fail
- **THEN** step 归零，下一轮到期日为次日；其后连续通过按阶梯从短间隔重新爬升

#### Scenario: 只练不判不动阶梯

- **WHEN** 用户对该轮选择 practice-only
- **THEN** step 与后续轮次到期日均不变

### Requirement: 首轮到期按每日预算错峰

计划生成时，各训练项**首轮**到期日 SHALL 按阶段顺序与每日时长上限摊开
（同日到期总量不超过预算），MUST NOT 将全部训练项堆在同一日；
后续轮次到期由表现驱动派生，不再对齐统一轮次日。

#### Scenario: 十二题路径的错峰

- **WHEN** 路径含 12 个训练项、每日预算 30 分钟、单项 10-20 分钟
- **THEN** 首轮到期分布在连续多日（每日 2-3 项），而非创建日+1 当天 12 项全量

### Requirement: 达标后剩余轮次转为可选巩固

训练项达标（连续 2 次 pass）或测验补练通过后，其剩余轮次 SHALL 转为**可选巩固**：
今日清单默认不含，用户可手动发起；MUST NOT 因状态迁移丢失任何已生成的计划行或作答历史。

#### Scenario: 提前达标不再罚站

- **WHEN** 某训练项在第 2 次通过后达标，第 3/4/5 轮尚未到期
- **THEN** 这些轮次默认不再出现在今日清单；用户从训练详情可手动练

### Requirement: 调度纯规则且与测验节奏不互扰

阶梯推导与到期重算 SHALL 为纯函数（相同作答历史必得相同排期），LLM MUST NOT 参与调度；
测验计划项（kind='assessment'）的 14 天节奏 SHALL 维持日历驱动，不受训练项阶梯影响。

#### Scenario: 确定性

- **WHEN** 两个训练拥有完全相同的作答历史（时间与结论一致）
- **THEN** 两者推导出的 step 与后续到期日完全一致

#### Scenario: 测验不受影响

- **WHEN** 训练项因 fail 重置阶梯
- **THEN** 已排期的测验项到期日不变
