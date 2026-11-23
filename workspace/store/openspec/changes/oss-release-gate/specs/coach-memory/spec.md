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

### Requirement: 用户偏好只影响呈现与节奏

偏好 SHALL 存于 app_settings（沿用既有键值先例）并提供读写端点（键白名单校验）。
偏好 MAY 影响：提示开关、每日时长目标、题型倾向（出题形式）。
偏好 MUST NOT 影响：出什么知识点、判分口径、达标条件、间隔算法参数
（合意困难边界——内容与标准不由舒适度决定）。

偏好 MUST 按用户隔离：存储键 MUST 带用户标识，一个用户修改偏好 MUST NOT 改变其他用户的
偏好；系统在决定是否给出连败提示等呈现行为时，MUST 读取当前用户本人的偏好。
读取顺序 SHALL 为「当前用户的键 → 未带用户标识的存量全局键 → 默认值」，写入只写当前用户的键。

#### Scenario: 偏好读写

- **WHEN** 用户 PUT daily_minutes_target=20
- **THEN** 之后 GET 返回 20；非法键或非法值返回 400

#### Scenario: 偏好不越界

- **WHEN** 用户设置题型倾向为 choice
- **THEN** 系统仅可让新题倾向以选择题形式出现，MUST NOT 只出简单题、
  MUST NOT 降低判分阈值或跳过薄弱知识点

#### Scenario: 双账号互不影响

- **WHEN** 张三把 coach_hint_enabled 设为 false，李四保持默认开启，李四对同一题第 3 次判分失败
- **THEN** 李四的 `submit_answer` 响应仍带 `coach_hint`；张三的 `GET /api/preferences` 只反映张三自己的设置

#### Scenario: 存量全局值仍可读

- **WHEN** 某用户从未写过偏好，而库里存在未带用户标识的存量全局值
- **THEN** 该用户读到的偏好等于存量全局值；其他用户写入自己的偏好后不影响他
