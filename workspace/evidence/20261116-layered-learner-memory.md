# 2026-11-16 · 分层学习者记忆验证（layered-learner-memory）

> 对应 change：`layered-learner-memory`（当日提案→当日实施归档）｜ 复现命令见各节

## 一、守卫测试

```
uv run pytest tests/test_learner_model.py -q   → 8 passed
```

覆盖：掌握度递推数学（起点 0.5 → 0.675 → 0.789，fail 立即回落，clamp）；
30 天半衰期衰减（含负天数按 0）；误解投影（wrong→concept_confusion、必答 missing→key_omission、
普通缺失不进清单）；record_attempt 集成（mastery/计数/知识点解析自题库）；
测验无明细→误解清单保持；**增量 == 全量重放收敛守卫**（单一事实源性质）；
读时衰减与 weak 排序 + 中文标签；端点契约（rebuild 回填 → 查询 → 幂等 → 404）。

## 二、关键性质证明

- **收敛性**：`test_rebuild_converges_with_incremental`——三次作答（两 fail 一 pass，含明细变化）
  后 rebuild 全量重放，mastery/misconceptions/attempts/passes 四列与增量路径完全一致。
- **表自动创建**：`init_db` 的 `IF NOT EXISTS` executescript 在全新库直接建表（测试验证）；
  存量生产库重启 trainer-api（init_db）即得表，随后 POST rebuild 回填存量。

## 三、全量回归

```
uv run pytest tests/ -q   → 351 passed, 1 skipped, 30 subtests（基线 343 → +8）
```
