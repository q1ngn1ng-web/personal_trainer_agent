# 2026-07-25 · fix · datetime 比较混用 naive/aware 触发 TypeError

## 变更摘要

Streamlit 启动后访问「今日训练」页（`?page=daily&training_id=N`）时报：

```
TypeError: can't subtract offset-naive and offset-aware datetimes
  at src/ui/page_daily.py:60
```

### 根因

之前的 commit `729d44e` 只修复了**时间戳的写入路径**（4 个 `_now_iso()` 统一为 UTC tz-aware），但**没审查时间戳的读取与比较路径**。DB 里的 `created_at` / `last_active_at` 是 tz-aware UTC ISO 字符串，UI 模块读到内存里也是 tz-aware `datetime` 对象。但 UI 比较时仍用 `datetime.now()`（naive 本地时间），导致减法 TypeError。

`page_daily.py:60` 是用户能直接看到 crash 的那个。其他 3 处是同根因的潜伏 bug：

| 文件 | 行 | 原代码 | 潜在影响 |
|---|---|---|---|
| `src/ui/page_daily.py` | 60 | `(datetime.now() - created_at).days` | **用户可见 crash**（打开今日训练页直接挂） |
| `src/ui/page_review.py` | 45 | `(datetime.now() - datetime.fromisoformat(...).days)` | **用户可见 crash**（打开周复盘页） |
| `src/core/training.py` | 40, 43 | `(datetime.now() - self.created_at).days` 等 | **潜伏**（`days_since_creation` 调用时崩） |
| `src/services/trainer_service.py` | 603 | `last_active_at=datetime.now()` | **潜伏**（写入字段类型为 datetime，是 naive 值；与同模块 `_now_iso()` 不一致） |
| `src/services/trainer_service.py` | 174 | `today = datetime.now().date().isoformat()` | **次要**（生成 04_复习日历 用，本地日 vs UTC 日可能差 1 天） |

### 修复

所有 `datetime.now()`（naive）→ `datetime.now(timezone.utc)`：

```python
# page_daily.py
from datetime import date, datetime, timezone  # 加 timezone
days = (datetime.now(timezone.utc) - created_at).days if created_at else 0

# page_review.py
from datetime import datetime, timezone         # 加 timezone
days = (datetime.now(timezone.utc) - datetime.fromisoformat(str(created).replace("Z", "+00:00"))).days

# core/training.py
from datetime import datetime, timezone         # 加 timezone
def days_since_creation(self) -> int:
    return (datetime.now(timezone.utc) - self.created_at).days
def needs_weekly_review(self, now: datetime | None = None) -> bool:
    reference = now or datetime.now(timezone.utc)
    ...

# trainer_service.py
today = datetime.now(timezone.utc).date().isoformat()
last_active_at=datetime.now(timezone.utc)  # 字段类型是 datetime，必须传对象
```

## 影响范围

```
src/ui/page_daily.py:6, 60
src/ui/page_review.py:10, 45
src/core/training.py:6, 40, 43
src/services/trainer_service.py:174, 603
tests/test_units.py:380-460 (新增 TestDatetimeSubtraction 类，4 个测试)
```

## 相关文件路径

```
src/ui/page_daily.py:60    # user-visible crash
src/ui/page_review.py:45   # user-visible crash
src/core/training.py:40-45 # latent
src/services/trainer_service.py:174, 603  # latent
tests/test_units.py:380+   # 4 regression tests
```

## 关联的 OpenSpec change id

无（bug fix；与 commit 729d44e 同根因 ——「时间戳一致性」—— 但 729d44e 只解决了写入侧，本次补上读取/比较侧）

## 验证

```
DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py
  → e2e summary: 11/11 passed ✅

uv run python -m pytest tests/test_units.py
  → 34 passed, 13 subtests passed ✅ (was 30, +4 new)

uv run streamlit run src/main.py --server.headless true
  → 启动无 traceback ✅
```

**用户体验验证**：之前打开 `?page=daily&training_id=8` 直接 traceback，现在正常渲染「坚持天数」指标。

## 新增的回归测试

`tests/test_units.py::TestDatetimeSubtraction`（4 个测试）：

| 测试方法 | 锁住的不变量 |
|---|---|
| `test_domain_training_days_since_creation_with_tz_aware` | `Training.days_since_creation` 在 created_at 为 tz-aware 时不崩 |
| `test_domain_training_needs_weekly_review_with_tz_aware` | 同上 but `needs_weekly_review` |
| `test_db_iso_string_subtracts_from_utc_now_without_typeerror` | 与 `page_daily.py:60` 完全相同的减法模式 |
| `test_trainer_service_now_iso_used_throughout` | 正则扫描 `src/services/trainer_service.py`，禁止新出现的 `datetime.now(<非 utc>)` |

第 4 个测试是**未来防御** —— 任何人新写代码用了 `datetime.now()`（naive）就会被 CI 抓出。

## Git

```
(待提交) fix(ui/core/services): 时间戳比较/写入统一 UTC tz-aware，修复 TypeError
```

## 启发

1. **类型一致性修复要"全链路扫"** — 之前 729d44e 只看了 `_now_iso` 的 4 个生产点，没扫比较侧。本次的根因正是「半截修复」。下次类似的修复任务应先 grep `datetime.now()` 全文，看完再动手
2. **防御性回归测试** — `test_trainer_service_now_iso_used_throughout` 用正则扫源码，防的是未来开发者无意中用 naive `datetime.now()`。这是"修一处漏洞 + 防止同类再发"的完整闭环
3. **domain Training 的 created_at 默认工厂**也建议改为 tz-aware（本 commit 已修），但要小心这影响 `Training.empty()` 调用者的预期（无变化，因为都 naive datetime）

## 关联变更

- 同根因前置修复：729d44e「一致化 UTC tz-aware 时间戳」（已记录于 `20260725_fix_timestamp-consistency-and-weekly-active-at.md`，仅修了写入路径）
- 本次：补读取/比较路径的 4 处遗漏
- 总账：项目时间戳处理现已统一为 UTC tz-aware 单一约定