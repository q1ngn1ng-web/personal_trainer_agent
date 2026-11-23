# learner-memory Specification

## MODIFIED Requirements

### Requirement: 掌握度随时间衰减并可查询

查询学习者模型时，系统 SHALL 按读时计算返回 `decayed_mastery = mastery × 0.5^(距 last_seen 天数/30)`
与 weak 标记（decayed < 0.8）；结果按 decayed 升序排列，误解以中文标签呈现。
"距 last_seen 天数" MUST 是真实流逝时间：带时区的时间戳按其时区解释，不带时区的
时间戳按 UTC 解释，再与当前时刻在同一时间基准上相减；MUST NOT 因去掉时区而把时区
偏移量算进流逝时间。未经训练可见性授权的请求 MUST 拒绝（403/404）。

#### Scenario: 三十天未练

- **WHEN** 某知识点 mastery=0.8 且 last_seen 为 30 天前
- **THEN** 查询返回 decayed_mastery≈0.4 并标记 weak

#### Scenario: 只读 API

- **WHEN** 可见该训练的账号请求 GET /api/trainings/{id}/learner-model
- **THEN** 返回全部知识点画像（mastery/decoded/weak/误解/last_seen/次数），不产生任何写副作用

#### Scenario: 刚作答完立即查询

- **WHEN** 服务器系统时区为 Asia/Shanghai，某知识点刚完成一次判分作答（last_seen 是带 `+00:00` 的 UTC 时间戳）
- **THEN** 距 last_seen 天数约为 0，decayed_mastery 等于 mastery（差异只来自真实流逝的秒数，而非 8 小时）
