# user-training-plan Specification

## ADDED Requirements

### Requirement: 澄清阶段收集用户投入参数

目标澄清步 SHALL 展示训练节奏控件（总时长周数、训练次数）供用户自定义，
值以 user_input 来源写入目标快照（horizon_days / session_count）。
系统 SHALL 依据知识点数量与目标等级给出推荐值与不足警告
（次数×单次容量低于"每项最少 2 次接触"的需求时 MUST 提示）。
澄清对话的 LLM MUST NOT 追问周期/频次/时长（界面控件负责收集）。

#### Scenario: 用户自定义两周三次

- **WHEN** 用户在节奏卡片设定总时长 2 周、训练 3 次
- **THEN** 快照记录 horizon_days=14、session_count=3（来源 user_input）
- **WHEN** 训练项 12 个、每项需 2 次接触、单次容量按每日目标时长计算不足
- **THEN** 卡片显示警告并给出建议（增加次数或延长时长）

### Requirement: 会话制覆盖分配

计划生成 SHALL 将训练项分配到 N 次会话：新知按阶段顺序靠前，
每个训练项 MUST 至少出现 2 次（首学+复习），单次清单总时长不超过每日目标；
未完成项顺延进后续会话。分配 SHALL 为纯函数（相同输入必得相同分配），
LLM MUST NOT 直接决定分配。

#### Scenario: 两周三次的分配

- **WHEN** 12 个训练项、3 次会话、horizon 14 天
- **THEN** 生成 3 份会话清单，每项至少出现 2 次，会话日期近似均匀分布
- **THEN** 相同输入重复生成，分配完全一致

### Requirement: 终测作为完成门

最后一次会话后 SHALL 触发终测（覆盖全部必修训练项）；
终测通过 → 训练 completed；终测不通过 → 系统按剩余 horizon 与未达标项重新生成计划
（已达标项与作答历史保留），horizon 用尽时 MUST 显式提示用户选择（延长或归档），
MUST NOT 静默无限延长。

#### Scenario: 终测通过完成训练

- **WHEN** 第 3 次会话后终测覆盖全部必修项且通过
- **THEN** trainings.status='completed'

#### Scenario: 终测不通过重来

- **WHEN** 终测未通过且 horizon 尚有余量
- **THEN** 未达标项重新分配进新会话，已达标项不重练
- **WHEN** horizon 用尽仍不通过
- **THEN** 提示用户选择延长 horizon 或归档为未完成
