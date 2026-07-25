# llm-observability Specification

## Purpose
TBD - created by archiving change trainer-mvp-v1. Update Purpose after archive.
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
系统 SHALL 在每次 LLM 调用完成后（含成功与失败），在 `llm_calls` 表写入一行：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | INTEGER PK | 是 | 自增 |
| training_id | INTEGER FK | 否 | 关联的训练主题（新建训练前可为空） |
| call_purpose | TEXT | 是 | 用途：topic_validation / keyword_generation / baseline_q / baseline_scoring / weekly_calibration / md_generation 等 |
| prompt_name | TEXT | 是 | prompt 模板名（如 `validation_v1`） |
| prompt_version | TEXT | 是 | 版本号（如 `v1.0.0`） |
| model | TEXT | 是 | 实际调用的模型名 |
| input_text | TEXT | 是 | 完整 prompt（变量替换后） |
| output_text | TEXT | 否 | LLM 返回文本（失败时为空） |
| output_json | TEXT | 否 | 解析后的 JSON（若适用） |
| validation_result | TEXT | 否 | JSON Schema 校验结果（pass/fail + 错误信息） |
| retry_count | INTEGER | 是 | 重试次数（0 表示一次成功） |
| latency_ms | INTEGER | 是 | 调用耗时（毫秒） |
| tokens_in | INTEGER | 是 | 输入 token 数 |
| tokens_out | INTEGER | 是 | 输出 token 数 |
| created_at | DATETIME | 是 | 调用时间 |

#### Scenario: 调用成功入库
- **WHEN** LLM 返回成功
- **THEN** `llm_calls` 写入一行，所有字段完整

#### Scenario: 调用失败也入库
- **WHEN** LLM 调用抛异常或超时
- **THEN** `llm_calls` 仍写入一行，output_text/validation_result 为空，retry_count 记录实际重试次数
- **THEN** failure_reason 写入单独的 `error_log` 字段或 notes 字段

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

