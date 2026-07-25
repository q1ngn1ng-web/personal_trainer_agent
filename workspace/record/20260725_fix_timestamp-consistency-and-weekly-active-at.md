# 2026-07-25 · fix · 时间戳一致性 + 周复盘 last_active_at bump

## 变更摘要

通过 codegraph 复查 `trainer-mvp-v1` 实施产物，发现两类 bug 并修复：

### Bug 1：跨模块时间戳格式不一致
- **现象**：`src/services/trainer_service._now_iso()` 使用 `datetime.now().isoformat(timespec="seconds")`（naive 本地时间），而 `src/db/queries._now()` / `src/services/review_service._now_iso()` / `src/services/daily_log_service._now_iso()` 三个模块使用 `datetime.now(timezone.utc).isoformat()`（UTC tz-aware）
- **影响**：写入 `trainer.db` 的 `trainings.last_active_at` / `created_at` 等字段在 4 个模块间格式不统一，导致跨行排序、跨表比较时产生歧义（特别是非 UTC 时区的用户）
- **修复**：`_now_iso()` 改为 `datetime.now(timezone.utc).isoformat()`，并补 `timezone` 导入

### Bug 2：`apply_weekly_review` 不 bump `last_active_at`
- **现象**：`src/services/review_service._apply_state_changes()` 在 updates dict 中只设 `last_review_at`，未设 `last_active_at`
- **影响**：用户周复盘后，该训练在首页按 `last_active_at DESC` 排序时位置异常（看起来"不活跃"），与"刚刚做了复盘"的事实相悖
- **修复**：updates dict 增加 `"last_active_at": now_iso`

## 影响范围

- `src/services/trainer_service.py` — `_now_iso()` 实现 + 顶部 `import`
- `src/services/review_service.py` — `_apply_state_changes()` 的 updates 字典
- `tests/test_units.py` — 新增 `TestTimestampConsistency`（4 测试）+ `TestProgressCoercion`（2 测试）
- `data/trainer.db` — 已有行的 `last_active_at` 不会自动迁移（无 schema 变更，仅影响后续写入）

## 相关文件路径

```
src/services/trainer_service.py:8          # 新增 `timezone` import
src/services/trainer_service.py:57-59      # _now_iso() 重写
src/services/review_service.py:158-166     # _apply_state_changes updates dict
tests/test_units.py:280-380                # 新测试类 TestTimestampConsistency + TestProgressCoercion
```

## 关联的 OpenSpec change id

`trainer-mvp-v1`（已归档为 `2026-07-25-trainer-mvp-v1`）

本次修复不产生新的 OpenSpec change —— 它是 trainer-mvp-v1 实施产物的内务修正，未改变任何 spec 行为。

## 验证

```
DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py
  → e2e summary: 11/11 passed ✅

uv run python -m pytest tests/test_units.py -v
  → 30 passed, 13 subtests passed ✅
  (24 个旧测试 + 4 个 timestamp 一致性 + 2 个 enum coercion)
```

新测试覆盖：

| 测试类 | 测试方法 | 锁住的不变量 |
|---|---|---|
| TestTimestampConsistency | test_trainer_service_now_iso_is_utc_aware | trainer 的 _now_iso 是 UTC tz-aware |
| TestTimestampConsistency | test_queries_now_is_utc_aware | queries._now 是 UTC tz-aware |
| TestTimestampConsistency | test_review_service_now_iso_is_utc_aware | review 的 _now_iso 是 UTC tz-aware |
| TestTimestampConsistency | test_daily_log_service_now_iso_is_utc_aware | daily_log 的 _now_iso 是 UTC tz-aware |
| TestProgressCoercion | test_empty_progress_uses_enums | _empty_progress 返回 enum 类型 |
| TestProgressCoercion | test_compute_training_progress_handles_known_db_status | DB 字符串 status → enum 强制转换 |

## Git

```
729d44e fix: 一致化 UTC tz-aware 时间戳 + 周复盘 bump last_active_at
```

## 复查中已确认**不构成 bug** 的项目（避免后续误判）

- `progress_service.compute_training_progress` 给 `TrainingProgress.status`（typed `TrainingStatus`）赋字符串值 → **不会发生**。该模块已有 `_coerce_status()` / `_coerce_level()` / `_parse_dt()` 三个显式 coerce 函数（progress_service.py:62-94），从 DB 读到内存一律先转 enum/datetime
- `src/db/models.py::Training.status` 用 `str` 而非 `TrainingStatus` → **正确**。这是 DB 行映射（与 SQLite schema 一致），domain 模型 `src/core/training.py::Training` 才用 enum，两层职责分离是有意设计

## 复查中发现的**非紧急设计缺口**（留作后续 OpenSpec change）

1. `trainer_service.create_training` 不往 `trainings.schedule.units` 写入 unit 数据 → `extract_today_tasks` 永远走 placeholder 分支 → 间隔算法从未真正生效。需定义"schedule.units 的初始化契约"（什么时候填、按什么 schema 填、谁负责维护 review_count 增量）
2. `apply_weekly_review` 写死 `"{}"` 当 `dimension_scores` → spec 里的"知识面/深度/量 三维度评分"从未落地。需先在基线诊断里采集维度评分
3. `check_task` 不更新 `training.schedule.units[*].review_count` → 即使 schedule.units 有数据，间隔算法的"复习过几次"也不会增长

以上 3 项属于 trainer-mvp-v1 设计遗漏，建议在下一个 change（如 `trainer-mvp-v1-followup`）里集中处理。