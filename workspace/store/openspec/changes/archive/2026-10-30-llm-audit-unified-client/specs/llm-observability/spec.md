# llm-observability Specification

## MODIFIED Requirements

### Requirement: LLM 调用必须记录到 `llm_calls` 表

系统 SHALL 在统一客户端 `src/llm/client.py` 的 `complete()` 内部完成记账：
每次调用返回（成功、静态降级）或彻底失败时，MUST 在 `llm_calls` 表写入恰好一行。
业务 service 层 MUST NOT 手写调用记录——单一写入点 MUST 位于客户端。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | INTEGER PK | 是 | 自增 |
| training_id | INTEGER FK | 否 | 关联的训练主题（训练创建前的调用为空；0/负数占位值视为空） |
| call_purpose | TEXT | 是 | 用途；默认等于 prompt_name，允许业务语义覆盖（如日常判分用 `daily_grade`） |
| prompt_name | TEXT | 是 | prompt 模板名 |
| prompt_version | TEXT | 是 | 版本号（如 `v1.0.0`） |
| model | TEXT | 是 | 实际调用的模型名 |
| input_text | TEXT | 是 | 调用方输入变量（剥去 schema/反馈注入），截 4000 字符 |
| output_text | TEXT | 否 | LLM 返回文本（彻底失败时为空） |
| output_json | TEXT | 否 | 解析后的 JSON（若适用） |
| validation_result | TEXT | 否 | pass（有结构化输出）/ fail |
| retry_count | INTEGER | 是 | 重试次数（0 表示一次成功） |
| latency_ms | INTEGER | 是 | 调用耗时（毫秒；彻底失败为 0） |
| tokens_in | INTEGER | 是 | 输入 token 数 |
| tokens_out | INTEGER | 是 | 输出 token 数 |
| failure_reason | TEXT | 否 | 彻底失败时的异常类型与消息（截 500 字符） |
| fallback_used | INTEGER | 是 | 1 表示本次返回来自静态降级载荷 |
| created_at | DATETIME | 是 | 调用时间 |

覆盖范围：`PROMPT_REGISTRY` 中的**每一个** prompt 链路，无论新旧。
记账自身的失败 MUST NOT 阻塞业务主流程（仅记录日志）。

#### Scenario: 调用成功入库

- **WHEN** 任一 service 通过 `complete()` 成功拿到结构化输出
- **THEN** `llm_calls` 新增一行：`validation_result='pass'`、`fallback_used=0`、tokens/latency 为真实观测值
- **THEN** 出题（train_question）、判分（quiz_grade/daily_grade）、探测（edge_probe/edge_probe_grade）、路径（path_skeleton）、变式（quiz_variant）、解析（explanation）等全部链路同样有账

#### Scenario: 调用失败也入库

- **WHEN** LLM 重试耗尽且无降级载荷，`complete()` 抛出异常
- **THEN** `llm_calls` 仍写入一行：`validation_result='fail'`、`failure_reason` 含异常类型与消息
- **THEN** 业务层随后捕获该异常做降级时，MUST NOT 再重复记账

#### Scenario: 静态降级入账

- **WHEN** LLM 重试耗尽且该 prompt 配有静态降级载荷
- **THEN** `llm_calls` 写入一行且 `fallback_used=1`，`output_json` 为降级载荷

#### Scenario: 训练创建前的调用

- **WHEN** topic_validation 等在训练尚不存在时调用（training_id 未定）
- **THEN** `llm_calls.training_id` 为 NULL，其余字段完整

#### Scenario: 覆盖完整性可验证

- **WHEN** 在无 API key 环境运行 `scripts/audit_coverage_smoke.py`
- **THEN** 脚本走完全部链路的降级路径后，断言每个注册 prompt 的 purpose 在 `llm_calls` 至少有一行
