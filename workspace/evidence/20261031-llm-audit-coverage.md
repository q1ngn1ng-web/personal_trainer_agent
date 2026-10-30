# 2026-10-31 · LLM 审计覆盖验证（llm-audit-unified-client）

> 对应 change：`llm-audit-unified-client` ｜ 复现命令见每节

## 一、审计覆盖冒烟（无 API key，全部走降级路径）

```
DEEPSEEK_API_KEY= uv run python scripts/audit_coverage_smoke.py

call_purpose           rows
topic_validation          1  OK
keyword_generation        1  OK
baseline_q                6  OK   （两次生成 × 每次 3 个真实尝试，逐尝试记账）
baseline_scoring          1  OK
goal_clarification        1  OK
pretrain_checklist        1  OK
edge_probe                1  OK
path_skeleton             1  OK
train_question            1  OK
quiz_variant              1  OK
explanation               1  OK
weekly_calibration        1  OK
Total: 17 rows across 12 purpose(s)
audit coverage smoke: ALL COVERED
```

## 二、守卫测试

```
uv run pytest tests/test_llm_audit.py -q
5 passed
```

覆盖：成功入账（tokens/latency/training_id 真实）、静态降级 fallback_used=1、
彻底失败 failure_reason 落账、占位 training_id=0 记 NULL、call_purpose 覆盖（daily_grade）。

## 三、枚举一致性

`set(PROMPT_REGISTRY) ⊆ ALLOWED_PURPOSES`（scripts/check_llm_logs.py）——15 个 prompt + daily_grade，无遗漏。

## 四、全量回归

```
uv run pytest tests/ -q
275 passed, 1 skipped, 30 subtests passed in 210.41s
```
