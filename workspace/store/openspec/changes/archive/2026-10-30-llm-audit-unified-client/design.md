# llm-audit-unified-client · 设计

## D1 为什么记账放客户端而不是包装器/装饰器

`complete()` 是全部 15 个 prompt 链路的唯一出口（文件 docstring 即此约束）。放客户端：

1. 天然覆盖未来新增链路（新调用方零成本获得审计）；
2. 拿得到全部观测字段（latency/tokens/retry/version 在 `_run_once` 返回值里），无需二次传递；
3. 不会出现"新增 service 忘记记账"——遗漏类别在结构上消失。

## D2 三类结果的账面语义

| 结果 | validation_result | fallback_used | retry_count | failure_reason |
| --- | --- | --- | --- | --- |
| 成功 | pass（有 output_json）/ fail（无） | 0 | 实际重试数 | NULL |
| 静态降级 | pass（fallback 载荷） | **1** | 实际尝试数 | NULL |
| 彻底失败（re-raise） | fail | 0 | 3（max_attempts） | `异常类型: 消息`（截 500 字符） |

`input_text` 记调用方传入的 variables（剥掉客户端注入的 `schema` 与 `__feedback__`），截 4000 字符——
与历史手写记录的口径一致，便于前后对比。

## D3 training_id 的 FK 守卫

`llm_calls.training_id` 带 FK 且 `foreign_keys` 开启。老流程（十要素一代）在训练创建前调用，
历史上传 0 或不传。客户端统一守卫：`<=0` 或非法值记 NULL（spec 本就允许 training_id 为空）。

## D4 日常判分与测验判分的用途区分

两者共用 `quiz_grade` prompt。审计用途不同：日常训练判分传 `call_purpose="daily_grade"`，
测验判分保持 `quiz_grade`——token 成本才能按"日常 vs 测验"拆分。`ALLOWED_PURPOSES` 同步登记。

## D5 回滚

revert 单次提交即可；service 层不再有记账代码，回滚后新链路重新变回"无账"状态（回到修复前行为，不会更糟）。
