# llm-audit-unified-client · 任务清单

- [x] 1.1 `complete()` 增加 `training_id` / `call_purpose` 可选参数；成功、降级（fallback_used=1）、彻底失败三类结果统一写 `llm_calls`；占位 training_id（≤0）记 NULL
  - 验收：`tests/test_llm_audit.py` 5 用例全绿
- [x] 1.2 删除 7 个老链路 service 的手写 `record_llm_call` 块与 6 个 `log_llm_failure` 调用点；移除 `log_llm_failure` 函数
  - 验收：`grep -rn "log_llm_failure\|record_llm_call" src/services/` 零命中
- [x] 1.3 全部 16 个 `complete()` 调用点传入 `training_id`（创建前链路传 None）；日常训练判分传 `call_purpose="daily_grade"`
  - 验收：审计覆盖冒烟中各链路行的 `training_id` 正确
- [x] 1.4 `scripts/check_llm_logs.py` 的 `ALLOWED_PURPOSES` 扩展到全部 prompt + `daily_grade`
  - 验收：`set(PROMPT_REGISTRY) - ALLOWED_PURPOSES` 为空
- [x] 1.5 新增 `scripts/audit_coverage_smoke.py` 可重复冒烟
  - 验收：无 key 运行输出 `12 purpose ALL COVERED`
- [x] 1.6 全量回归 + 收尾
  - 验收：`uv run pytest tests/ -q` 全绿；证据回填；`workspace/record/` 记录；归档 change
