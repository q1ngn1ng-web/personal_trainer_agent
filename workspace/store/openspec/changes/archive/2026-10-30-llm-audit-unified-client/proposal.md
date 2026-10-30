# llm-audit-unified-client · LLM 审计下沉统一客户端

## Why

`llm-observability` spec 明确要求「每次 LLM 调用完成后（含成功与失败）都在 `llm_calls` 写一行」，
但实现只做到了一半——记账由各 service 手写，于是：

| 链路 | 成功落账 | 失败落账 |
| --- | --- | --- |
| topic_validation / keyword_generation / baseline_q / baseline_scoring / weekly_calibration / pretrain_checklist / goal_clarification | ✅（手写） | ✅（手写） |
| train_question / quiz_variant / quiz_grade（两个调用方）/ edge_probe / edge_probe_grade / path_skeleton | ❌ | ✅（手写 log_llm_failure） |
| explanation | ❌ | ❌（连失败都只有 logger.warning） |

后果：核心学习闭环（出题、判分、探测、路径、变式）的**成功调用完全没有账**——
token 成本、重试率、延迟分布、prompt 版本对比全部无从谈起，spec 要求形同虚设。
手写记账的根因是「记账散落在调用方」：谁手写谁遗漏。

## What Changes

- **记账下沉到统一客户端**：`complete()` 新增 `training_id` / `call_purpose` 两个可选参数，
  在客户端内部对**成功 / 静态降级 / 彻底失败**三类结果统一写 `llm_calls`；
  `call_purpose` 默认取 `prompt_name`（日常训练判分显式传 `daily_grade` 以区别测验判分）
- `training_id` 守卫：0 或负数（老流程占位值）记 NULL，不触发 FK
- **删除全部 service 层手写记账**（7 个老链路的 `record_llm_call` 块、6 个 `log_llm_failure` 调用点），
  `log_llm_failure` 函数从客户端移除——单一写入点
- `scripts/check_llm_logs.py` 的 `ALLOWED_PURPOSES` 扩展到全部 15 个 prompt + `daily_grade`
- `explanation_service` 落库 `explanations` 时改用真实观测值（prompt_name/prompt_version/model），不再硬编码
- 新增守卫测试 `tests/test_llm_audit.py`（5 用例：成功/降级/失败/占位 training_id/用途覆盖）
- 新增可重复冒烟 `scripts/audit_coverage_smoke.py`：临时库走「老链路 + 学习闭环主链」全旅程，
  断言 12 个 purpose 每个都有账（无 key 即可跑，全部走降级路径）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 客户端内记账 + 删 service 手写 | 客户端记账 + service 保留（双份） | 同一次调用两行账，统计全部失真 |
| 失败也记账（含彻底失败） | 只记成功 | 失败诊断（配额、超时、schema 不合）恰恰是最需要账的场景 |
| baseline_q 逐尝试记账（每次 attempt 一行） | service 汇总成一行 | 每次尝试都是真实 API 调用、真实 token 消耗；汇总行会掩盖重试率 |
| 审计失败只打日志 | 审计失败抛出 | 账本不能反过来挡业务主流程 |

## 非目标（Non-goals）

- 不做成本报表/看板（数据就绪后属后续 change）
- 不改任何 prompt 模板与业务降级逻辑
- 不迁移历史 llm_calls 数据（历史行保持原样）

## Capabilities

### Modified Capabilities

- `llm-observability`：把「调用完成后记账」的实现锚点从"各 service 手写"改为"统一客户端内记账"，
  并把覆盖范围钉死为全部 prompt 链路的成功/降级/失败三类结果

## Impact

- **代码**：`src/llm/client.py`（记账 + 删 log_llm_failure）；11 个 service 文件（删手写记账 + 传 training_id）；`scripts/check_llm_logs.py`（枚举扩展）；`scripts/audit_coverage_smoke.py`（新增）
- **测试**：新增 `tests/test_llm_audit.py`；1 个既有测试的 fake 签名补 `**kwargs`
- **风险**：低——记账路径全部 try/except 包裹；业务逻辑与降级行为零变化（全量回归验证）
- **证据**：`scripts/audit_coverage_smoke.py` 输出（12 purpose 全覆盖）+ 守卫测试
