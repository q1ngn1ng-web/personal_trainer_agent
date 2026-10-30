# 2026-10-31 · LLM 审计下沉统一客户端（llm-audit-unified-client）

> 类型：fix ｜ 对应 change：`llm-audit-unified-client` ｜ 关联审计：成熟度审计 Trainer P0-4

## 变更摘要

修复「新链路 LLM 成功调用不写 llm_calls」的审计缺口（P0-4）：

- `src/llm/client.py`：`complete()` 新增 `training_id` / `call_purpose` 可选参数，
  **成功 / 静态降级（fallback_used=1）/ 彻底失败**三类结果统一在客户端写 `llm_calls`；
  占位 training_id（≤0）守卫为 NULL；`log_llm_failure` 函数移除（单一写入点）；
- 11 个 service 文件：删除手写记账（7 个老链路 `record_llm_call` 块、6 个 `log_llm_failure` 调用点），
  16 个调用点全部传入 `training_id`；日常训练判分传 `call_purpose="daily_grade"`（与测验判分区分）；
- `explanation_service`：`explanations` 落库改用真实观测值（此前硬编码 v1.0.0/model=NULL）；
- `scripts/check_llm_logs.py`：`ALLOWED_PURPOSES` 扩展到全部 15 个 prompt + `daily_grade`；
- 新增 `tests/test_llm_audit.py`（5 用例：成功/降级/失败/占位 id/用途覆盖）与
  `scripts/audit_coverage_smoke.py`（可重复的全链路审计覆盖冒烟，无 key 可跑）。

## 影响范围

- 审计行为：全 15 个 prompt 链路（成功+失败）都有账；业务降级逻辑零变化
- 数据：`llm_calls` 从此后的每次调用都记录；历史行不动

## 验证

- `uv run pytest tests/test_llm_audit.py -q` → 5 passed
- `uv run python scripts/audit_coverage_smoke.py` → **12 purpose ALL COVERED（17 rows）**
- 全量回归 `uv run pytest tests/ -q` → **275 passed, 1 skipped, 30 subtests**（含 1 个既有测试 fake 签名补 **kwargs）

## 遗留

- 成本报表/看板属后续 change（数据已就绪）
