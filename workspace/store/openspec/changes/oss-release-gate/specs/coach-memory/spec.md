# coach-memory Specification

## MODIFIED Requirements

### Requirement: 训练日会话小结

系统 SHALL 支持按 (training_id, 日期) 聚合当天判分作答，输出结构化小结：
练习题数、通过率、错误要点频次、最弱知识点、各题连败状态。
小结 SHALL 以只读端点提供（MUST 过训练可见性守卫），聚合 MUST 为读时计算（零新表）；
人话叙述默认由规则模板拼接，LLM 叙述 MUST 为开关预留（默认关）。

聚合 MUST NOT 依赖 `plan_items` 上不存在的列。知识点名的解析顺序 SHALL 为：
`question_bank.knowledge_point`（按 training_id + item_key）→ `training_items.knowledge_point`
（经 item_key 关联最新确认路径下的训练项）→ 回落 item_key 本身；出题要点清单取
`plan_items.points`。单条作答的元数据缺失 MUST NOT 导致整份小结失败。
"当天"的时区口径 MUST 与 `local_today()` 一致（`TRAINER_TZ`，默认 Asia/Shanghai），
MUST NOT 依赖数据库进程的系统时区。

#### Scenario: 练完当天任务看小结

- **WHEN** 张三完成当天 4 题后请求会话小结
- **THEN** 返回题数 4、通过率、错误要点频次（如「AOF 被说成日志 ×2」）、最弱知识点与各题连败状态

#### Scenario: 空日期

- **WHEN** 该日期没有任何判分作答
- **THEN** 返回空小结（题数 0），MUST NOT 报错

#### Scenario: 日常训练作答（带计划项）当天看小结

- **WHEN** 张三当天通过「今日任务」作答 3 题（`practice_attempts.plan_id` 指向真实计划项），其中「RDB 触发条件」错了 2 次
- **THEN** 请求会话小结返回 200，题数 3，`weakest_knowledge_point` 为「RDB 触发条件」且 `fail_count` 为 2
- **THEN** 响应中各题的连败状态与要点频次照常给出

#### Scenario: 部署在 UTC 服务器上跨日练习

- **WHEN** 部署环境的系统时区为 UTC、`TRAINER_TZ=Asia/Shanghai`，张三在北京时间 23:30 与次日 00:30 各作答 1 题
- **THEN** 北京时间当天的会话小结只含 23:30 那一题，次日的小结只含 00:30 那一题
