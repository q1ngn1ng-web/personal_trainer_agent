# llm-observability Specification

## Purpose
让每一次 LLM 调用可追溯：统一客户端自动记账（成功/降级/失败），成本、重试与版本对比有数据可依。
## Requirements
### Requirement: 所有 LLM 调用必须经过统一客户端
系统 SHALL 提供统一的 LLM 客户端（`src/llm/client.py`），任何 LLM 调用 MUST 走该客户端，不允许业务代码直接调用 DeepSeek API。

#### Scenario: 客户端封装
- **WHEN** 业务模块需要调用 LLM
- **THEN** 调用 `llm_client.complete(prompt_name, variables, schema=...)` 接口
- **THEN** 客户端自动注入：model、temperature、max_tokens、prompt_version

#### Scenario: 未来模型切换
- **WHEN** 需要切换到 Claude/GPT
- **THEN** 仅修改客户端实现；业务模块无需改动
- **THEN** 所有历史调用日志保留（不丢失追溯数据）

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

### Requirement: LLM 输出必须经过 JSON Schema 校验
系统 SHALL 为每种 LLM 用途定义 JSON Schema，受 schema 约束的输出 MUST 通过 `jsonschema` 校验。

#### Scenario: Schema 校验失败重试
- **WHEN** LLM 返回文本无法被解析为合法 JSON，或不满足 schema
- **THEN** 系统重试 LLM 调用（最多 3 次），每次重试的 prompt MUST 包含上一次失败原因
- **THEN** 重试次数写入 `llm_calls.retry_count`

#### Scenario: 校验成功仍记录
- **WHEN** LLM 返回通过校验
- **THEN** `validation_result='pass'`，`output_json` 写入解析后对象

### Requirement: 关键词白名单的覆盖率校验独立于 JSON Schema
系统 SHALL 在 baseline_diagnosis 用途中，对 LLM 生成的 3 道诊断题做关键词覆盖率校验（每题 ≥ 1 个关键词命中）。

#### Scenario: 覆盖率不达标重试
- **WHEN** 某题不覆盖关键词白名单
- **THEN** 该题判定失败，整批重试（最多 3 次）

#### Scenario: 3 次仍不达标降级
- **WHEN** 3 次覆盖率校验仍失败
- **THEN** 走 fallback 路径，使用预置的 2 道概念题 + 1 道应用题（写入数据库与 md，但 `llm_calls` 标注 `fallback_used=true`）

### Requirement: prompt 版本可追溯
系统 SHALL 在 `src/llm/prompts.py` 集中管理所有 prompt 模板，每个模板 MUST 含版本号常量。

#### Scenario: 版本号写入调用日志
- **WHEN** 业务模块调用 `llm_client.complete('baseline_q', variables)`
- **THEN** 客户端从 `prompts.BASELINE_Q_PROMPT_VERSION` 读取版本号（如 `v1.0.0`）写入 `llm_calls.prompt_version`

#### Scenario: prompt 变更后版本号升级
- **WHEN** 修改 `prompts.py` 中某 prompt 模板
- **THEN** 必须同步更新对应版本号常量
- **THEN** 旧版本日志仍可查询（按 `prompt_version` 过滤）

### Requirement: 提供 harness 化的查询入口
系统 SHALL 在 `src/db/queries.py` 提供至少以下查询接口（Phase 2 harness 化用）：

- `get_calls_by_purpose(call_purpose: str) -> list[LLMCall]`
- `get_calls_by_prompt_version(prompt_name: str, version: str) -> list[LLMCall]`
- `get_success_rate_by_prompt_version() -> dict[prompt_name, dict[version, float]]`
- `get_avg_latency_by_model() -> dict[model, float]`

#### Scenario: 查询可执行
- **WHEN** harness 脚本调用上述接口
- **THEN** 正确返回数据
- **THEN** 单次查询 < 100ms（在 10000 条 llm_calls 数据规模下）

