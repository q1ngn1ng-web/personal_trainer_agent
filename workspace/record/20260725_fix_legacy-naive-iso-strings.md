# 2026-07-25 · fix · 历史遗留 naive ISO 时间戳 + 防御性 parser

## 变更摘要

用户在「今日训练」页（`?page=daily&training_id=2`）又触发同样的 TypeError，尽管前面的 `241fecb` 已经修了写入侧。

### 真实根因

先前的 `241fecb` 只修了**写入侧**（统一 `datetime.now(timezone.utc)`），但**没审查数据库里已有的历史行**。检查发现：

```
trainings.id=2  (Python asyncio)  created_at = '2026-07-25T22:16:31'         ← naive
trainings.id=3  (test_coercion)  created_at = '2026-07-25T14:57:29.957743+00:00'  ← tz-aware
trainings.id=8  (用户学习Python)  created_at = '2026-07-25T15:35:12.264744+00:00'  ← tz-aware
```

id=2 是早期代码（`datetime.now().isoformat(timespec="seconds")`，无 tz 后缀）创建的。后续所有修复只确保新写入路径产生 tz-aware 字符串，但已存在的行没回填。

`_parse_created_at` 用 `datetime.fromisoformat(...)`，对无 tz 后缀的字符串返回 naive datetime，导致与 `datetime.now(timezone.utc)` 相减时 TypeError。

### 修复（防御 + 主动两层）

**1. 防御性 parser（未来兼容）**——3 个 parse 点都加 naive → UTC 兜底：

| 文件 | 函数 | 改法 |
|---|---|---|
| `src/ui/page_daily.py` | `_parse_created_at` | 加 `if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)` |
| `src/ui/page_review.py` | (inline 解析) | 同上 |
| `src/services/progress_service.py` | `_parse_dt` | 同上，并补 `timezone` import |

未来即使再出现 naive 数据也不会崩。

**2. 数据迁移（一次性清洗）**——扫所有时间戳字段，对 naive ISO 字符串 append `+00:00`：

```sql
UPDATE trainings 
SET created_at = created_at || '+00:00'
WHERE created_at NOT LIKE '%+%' AND created_at NOT LIKE '%Z' AND instr(created_at,'T') > 0
```

跑了实际迁移：
- `trainings.created_at`：id=2 from `'2026-07-25T22:16:31'` → `'2026-07-25T22:16:31+00:00'` ✅
- 其它 naive 字段扫描 0 命中

## 影响范围

```
src/ui/page_daily.py              # _parse_created_at 加防御 fallback
src/ui/page_review.py             # inline 解析加防御 fallback
src/services/progress_service.py # _parse_dt 加防御 fallback + 补 timezone import
data/trainer.db                   # 1 行数据迁移（无 schema 变更）
tests/test_units.py               # +1 回归测试
```

## 相关文件路径

```
src/ui/page_daily.py:40-53        # _parse_created_at 加 defensive fallback
src/ui/page_review.py:40-50       # inline parse 加 defensive fallback
src/services/progress_service.py:62-76  # _parse_dt 加 defensive fallback + import
tests/test_units.py:457-479       # test_naive_iso_string_subtraction_does_not_raise
data/trainer.db                   # id=2 created_at 一行迁移
```

## 关联的 OpenSpec change id

无（与 commit `241fecb` 同根因 ——「时间戳一致性」—— 同一类内务修正，触发根因为"半截修复 + 漏检历史数据"）

## 验证

```
$ grep '2026-07-25T22:16:31[^+]'
  → 0 hits（确认 naive 行已迁移）✅

uv run streamlit run src/main.py --server.headless true
  → 启动无 traceback ✅

$ uv run python -m pytest tests/test_units.py
  → 35 passed ✅ (34 + 1 new regression test)

DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py
  → 11/11 passed ✅
```

**用户体验验证**：之前打开 `?page=daily&training_id=2` 直接 traceback，现在正常渲染"坚持天数"指标。

## 新增的回归测试

`tests/test_units.py::TestDatetimeSubtraction::test_naive_iso_string_subtraction_does_not_raise`：

- 用 `assertRaises(TypeError)` 显式断言 naive datetime 与 tz-aware `datetime.now(timezone.utc)` 相减会崩（保留负面 reference，防止未来有人无意中"修了"减法容忍）
- 用 `.replace(tzinfo=timezone.utc)` 把 naive 转 UTC，验证防御性修复后相减不崩

## Git

```
(待提交) fix(ui/services/migration): 历史遗留 naive ISO 时间戳 + 防御性 parser + 数据迁移
```

## 三层时间戳防御现状

```
                    ┌── 写入侧 (commit 241fecb) — datetime.now(timezone.utc) / _now_iso()
                    │   所有模块统一 UTC tz-aware 写入
                    │
时间戳一致性 ──────┼── 读取侧 (commit 241fecb) — 修比较侧的 naive datetime.now()
                    │   page_daily / page_review / core/training / trainer_service
                    │
                    └── 历史数据 + 防御 parser (本次) — 防御 naive 输入 + 迁移已有 naive 行
                        三处 parser 加 fallback / 一次性 UPDATE 修复 id=2 created_at
```

至此三层防御齐全：
1. 写入侧规范（不再产生 naive）
2. 读取侧规范（不再 naive 比较）
3. 旧数据 + 防御（兼容已有 legacy + 未来再出现）

## 启发

1. **「半截修复」真实发生过** —— `241fecb` 只扫了写入路径，没扫 DB 内容。下次类似修复必须 grep **写入路径 + 已存数据** 两个维度
2. **保留负面 reference 测试** —— `with assertRaises(TypeError)` 锁住"naive 与 aware 不能相减"这个 Python 行为本身。防止未来有人误以为减法被"修复"了
3. **数据迁移脚本应该 idempotent** —— 本次 1 行 SQL 检查 `NOT LIKE '%+%' AND NOT LIKE '%Z'` 后再 append，未来再跑一次也无害（已经迁移的行不会再被改）

## 关联变更

- `729d44e` — 同根因前置修复 #1（写入侧 _now_iso 一致化）
- `241fecb` — 同根因前置修复 #2（读取/比较侧）
- 本次 — 同根因前置修复 #3（历史数据 + 防御 parser）

总账：项目时间戳约定自此完整覆盖**写入 / 比较 / 历史**三方面。