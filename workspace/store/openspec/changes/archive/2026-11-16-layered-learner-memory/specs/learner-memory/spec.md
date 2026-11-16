# learner-memory Specification

## ADDED Requirements

### Requirement: 判分作答增量更新学习者模型

每次系统判分的作答（日常与测验）经 `record_attempt` 落库时，系统 SHALL 在同一事务内
更新 `learner_knowledge` 中该 `(training_id, item_key)` 的掌握度：
`mastery += K×(outcome−mastery)`（K=0.35，起点 0.5，outcome 为要点得分或二元结果，结果 clamp 到 [0,1]）；
attempts/passes 计数与 last_seen_at 同步更新；活跃误解清单 SHALL 由最近一次带要点明细的判分
整体替换生成（`wrong`→concept_confusion；必答 `missing`→key_omission，含要点文本）。
更新 MUST NOT 调用 LLM；派生层更新失败 MUST NOT 阻塞作答事实记录。
学习者模型 SHALL 可由 `practice_attempts` 全量重放重建，且重放结果与增量更新收敛一致。

#### Scenario: 连续两次通过推高掌握度

- **WHEN** 某题 mastery 从起点起连续两次判分通过（score=1.0）
- **THEN** mastery 依次约为 0.675、0.789（K=0.35 递推），passes 计数为 2

#### Scenario: 概念混淆进入活跃误解清单

- **WHEN** 最近一次判分 detail 中某要点 verdict=wrong（evidence 已核验标记）
- **THEN** 该要点的文本与 concept_confusion 进入 misconceptions；此前清单整体被替换

#### Scenario: 重放收敛

- **WHEN** 对同一训练先增量更新、再执行 rebuild 全量重放
- **THEN** 两者得到的 mastery/计数/误解清单完全一致

### Requirement: 掌握度随时间衰减并可查询

查询学习者模型时，系统 SHALL 按读时计算返回 `decayed_mastery = mastery × 0.5^(距 last_seen 天数/30)`
与 weak 标记（decayed < 0.8）；结果按 decayed 升序排列，误解以中文标签呈现。
未经训练可见性授权的请求 MUST 拒绝（403/404）。

#### Scenario: 三十天未练

- **WHEN** 某知识点 mastery=0.8 且 last_seen 为 30 天前
- **THEN** 查询返回 decayed_mastery≈0.4 并标记 weak

#### Scenario: 只读 API

- **WHEN** 可见该训练的账号请求 GET /api/trainings/{id}/learner-model
- **THEN** 返回全部知识点画像（mastery/decayed/weak/误解/last_seen/次数），不产生任何写副作用
