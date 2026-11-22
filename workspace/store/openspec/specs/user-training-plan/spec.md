# user-training-plan Specification

## Purpose
TBD - created by archiving change user-defined-training-plan. Update Purpose after archive.
## Requirements
### Requirement: 澄清阶段收集用户投入参数

目标澄清步 SHALL 展示训练节奏控件（总时长周数、训练次数）供用户自定义，
值以 user_input 来源写入目标快照（horizon_days / session_count）并纳入
missing_fields 校验。系统 SHALL 依据知识点数量与目标等级给出推荐值。
澄清对话的 LLM MUST NOT 追问周期/频次/时长（界面控件负责收集）；
提示词 SHALL 增加字段间自洽检查口径（content/level/acceptance 指向同一主题且难度匹配）。

#### Scenario: 用户自定义两周三次

- **WHEN** 用户在节奏卡片设定总时长 2 周、训练 3 次
- **THEN** 快照记录 horizon_days=14、session_count=3（来源 user_input）
- **THEN** 推荐值按知识点数量与等级显示；参数缺失时 missing_fields 纳管、不可确认

### Requirement: 会话配比：并集覆盖 + 重叠巩固 + 恒稳控制器

计划生成 SHALL 将训练项分配到 N 次会话，满足：
①跨会话并集 = 100% 覆盖（每项至少 1 次）；②单次占比随 N 递减、会话间重叠递增
（N=2：每次 70%，重叠 40% = 已知巩固与错题回炉；N≥3 依此类推，配比表实施校准）；
③重叠池的"已知:错题"构成由**正确率恒稳控制器**动态分配——目标带 80%±10%，
>90% 提高错题/新知占比，60-70% 为 25%:15%，<60% 为 30%:10%；
④桶内入选按五星"值得复习率"排序（错题 > 回归项 > 稳定答对，映射表实施校准）。
分配 SHALL 为纯函数（相同输入必得相同分配），LLM MUST NOT 直接决定分配或配比。

#### Scenario: 两周三次的分配

- **WHEN** 12 个训练项、3 次会话、horizon 14 天
- **THEN** 生成 3 份会话清单，并集覆盖全部 12 项，会话日期近似均匀分布
- **THEN** 相同输入重复生成，分配完全一致

#### Scenario: 正确率过低时配比偏巩固

- **WHEN** 最近一次会话正确率 58%（低于 60%）
- **THEN** 下一会话的重叠池按 30% 已知巩固 + 10% 错题回炉构成，
  判分口径与达标规则不受影响

### Requirement: 会话日期由系统安排并允许提前练

N 个会话的日期 SHALL 由系统在 horizon 内近似均匀摊开；
用户 MAY 提前练习未到期会话——提前完成 SHALL 解锁后续内容，
MUST NOT 改变其余会话的排期语义与历史轨迹记录。

#### Scenario: 提前练

- **WHEN** 张三在第 2 会话到期前主动完成它
- **THEN** 作答照常判分落库并进入配比数据；第 3 会话日期保持不变且解锁

### Requirement: 终测作为完成门，不通过追加周期

最后一个会话后 SHALL 触发终测（覆盖全部必修训练项）；终测通过 → 训练 completed；
终测不通过 → SHALL 追加一轮同规格会话周期（按恒稳控制器重新配比，
已稳定项进入已知巩固池），周期小测（每 14 天）与终测并存；
horizon 用尽仍不通过时 MUST 显式提示用户选择（延长或归档），MUST NOT 静默无限延长。
存量训练 SHALL 按 schedule_mode 隔离，MUST NOT 被迁移到新模型。

#### Scenario: 终测通过完成训练

- **WHEN** 第 3 次会话后终测覆盖全部必修项且通过
- **THEN** trainings.status='completed'

#### Scenario: 终测不通过追加一轮

- **WHEN** 终测未通过
- **THEN** 追加一轮 N 次会话：已稳定项进入已知巩固池，未达标项按配比进错题/新知池
- **THEN** 周期小测按每 14 天继续；终测再次把关

#### Scenario: 存量训练隔离

- **WHEN** 旧模型创建的训练仍处于活跃状态
- **THEN** 其排期与完成语义保持 ADR-0021 口径，不受本 change 影响

