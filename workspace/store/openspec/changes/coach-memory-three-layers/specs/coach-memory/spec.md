# coach-memory Specification

## ADDED Requirements

### Requirement: 训练日会话小结

系统 SHALL 支持按 (training_id, 日期) 聚合当天判分作答，输出结构化小结：
练习题数、通过率、错误要点频次、最弱知识点、各题连败状态。
小结 SHALL 以只读端点提供（MUST 过训练可见性守卫），聚合 MUST 为读时计算（零新表）；
人话叙述默认由规则模板拼接，LLM 叙述 MUST 为开关预留（默认关）。

#### Scenario: 练完当天任务看小结

- **WHEN** 张三完成当天 4 题后请求会话小结
- **THEN** 返回题数 4、通过率、错误要点频次（如「AOF 被说成日志 ×2」）、最弱知识点与各题连败状态

#### Scenario: 空日期

- **WHEN** 该日期没有任何判分作答
- **THEN** 返回空小结（题数 0），MUST NOT 报错

### Requirement: 连败自动反馈

对同一训练项的连续判分失败（verdict=fail ⟺ score<0.8 或必答缺失；practice-only 不计入），
系统 SHALL 在 `submit_answer` 响应中附加 `failure_streak`（连续 fail 次数，pass 即清零）；
当 streak ≥ 3 且提示开关开启时，MUST 附加 `coach_hint` 人话提示（含历次分数与深度解析引导）。
连败计数 SHALL 为纯规则（MUST NOT 调用 LLM），且该数据 MUST 可供
回炉题（adaptive-practice-composition）与调度（performance-driven-scheduling）消费。

#### Scenario: 第四次答错收到提示

- **WHEN** 张三对同一题已连续 3 次 fail，第 4 次提交仍 fail
- **THEN** 响应 failure_streak=4，coach_hint 含历次分数列表与「建议深度解析看共同错因」
- **THEN** 判分结果本身（verdict/score/point_results）不受提示影响

#### Scenario: 答对清零且不提示

- **WHEN** 连败 2 次后本次 pass
- **THEN** failure_streak=0，无 coach_hint

#### Scenario: 提示开关关闭

- **WHEN** 偏好 coach_hint_enabled=false 且 streak≥3
- **THEN** failure_streak 仍返回（数据可用），coach_hint 为空串

### Requirement: 用户偏好只影响呈现与节奏

偏好 SHALL 存于 app_settings（沿用既有键值先例）并提供读写端点（键白名单校验）。
偏好 MAY 影响：提示开关、每日时长目标、题型倾向（出题形式）。
偏好 MUST NOT 影响：出什么知识点、判分口径、达标条件、间隔算法参数
（合意困难边界——内容与标准不由舒适度决定）。

#### Scenario: 偏好读写

- **WHEN** 用户 PUT daily_minutes_target=20
- **THEN** 之后 GET 返回 20；非法键或非法值返回 400

#### Scenario: 偏好不越界

- **WHEN** 用户设置题型倾向为 choice
- **THEN** 系统仅可让新题倾向以选择题形式出现，MUST NOT 只出简单题、
  MUST NOT 降低判分阈值或跳过薄弱知识点
