# 2026-07-25 · fix · 新建训练后 daily 页只显示 placeholder，题目找不到

## 变更摘要

用户新建训练（id=8）后访问「今日训练」页，只看到 placeholder `N1: 今日训练 (待初始化)`，**没有任何实际任务 / 题目**。题目**确实存在**于 md 文件（`04_复习日历.md` / `05_主动回忆题.md`），但 DB 的 JSON 字段从未回灌。

### 根因（共两层）

1. **写入侧遗漏**：trainer_service 生成的 `materials_payload` 只有 `universal_materials / specialized_materials / i1_materials / principles` 四个键，缺 `recall_units`。`schedule_payload` 只有 `schedule_template / intervals / stage_phases`，缺 `units`。缺失的这两个键恰好是 daily 页读的两个字段
2. **持久化遗漏**：即使 LLM 生成了题目（写进 md 文件），trainer_service 没把这些题目写入 `materials.recall_units` JSON 字段

### 现有调用契约

- `services/schedule_service.py::extract_today_tasks` 读 `training.schedule.units` —— 找不到 units → 返回 placeholder
- `services/recall_service.py::get_today_recall_questions` 读 `training.materials.recall_units` —— 找不到 → 返回空列表

### 修复

**1. 新增 helper `_populate_schedule_and_recall`**（`src/services/trainer_service.py`）

根据已有的「LLM 已生成的素材名 + 3 道基线题」派生 DB 结构：

| 来源 | 变成 `schedule.units` | 变成 `materials.recall_units` |
|---|---|---|
| 3 道基线诊断题（in-memory） | unit #1: `name="基线诊断题"` | unit: `unit="基线诊断题"`, 3 questions |
| `materials.specialized_materials` 每项 | unit #N: `name=<素材名>` | (无) |

- 单位数 hard cap = `_MAX_UNITS_FROM_MATERIALS = 12`（保护 daily 卡可读性）
- `learned_date = today`：表示今天首次学到
- `review_count = 0` / `last_reviewed_date = null`：标准间隔起点

**2. 接线 `create_training`**（Step 10 之前）

```python
# Step 10: create training row
...
_schedule_and_materials_payload_setup...

# Persist structured units + recall questions so the daily page shows
# real tasks from day one (instead of the "今日训练 (待初始化)" placeholder).
_populate_schedule_and_recall(
    schedule_payload=schedule_payload,
    materials_payload=materials_payload,
    baseline_questions=baseline_questions,
    today=now[:10],
)
```

**3. 一次性迁移 id=8（用户现有训练）**

id=8 是用户之前的训练，没经过这个 helper。手动跑了一次等效迁移：

- 从 `materials.specialized_materials` 5 个素材派生 5 个 units
- `recall_units` 留空（原数据里没存 baseline questions，没法伪造）

## 影响范围

```
src/services/trainer_service.py         # +_populate_schedule_and_recall helper, +3 调用行
tests/test_units.py                     # +4 回归测试
data/trainer.db                        # id=8 schedule.units = 5 entries
```

## 相关文件路径

```
src/services/trainer_service.py
  :49-61    _MAX_UNITS_FROM_MATERIALS constant
  :63-131   _populate_schedule_and_recall function
  :580-588  调用点 (create_training Step 10 之前)
tests/test_units.py:478-580  TestPopulateScheduleAndRecall 4 个测试
data/trainer.db                   id=8 一次性迁移
```

## 关联的 OpenSpec change id

无（bug fix；trainer-mvp-v1 实施产物的设计遗漏修复）

## 验证

**现场验证（id=8 用户训练）**：
```
$ extract_today_tasks(8)
  review: 0
  new: 3
    N1: 进程 (dim=('concept', '概念'), source=03_资料库.md §1)
    N2: 线程
    N3: 多进程
（_MAX_NEW_ITEMS_PER_DAY=3 是有意上限；剩下 "锁"/"并行策略"明天/后天陆续出现）
```

```
$ uv run python -m pytest tests/test_units.py
  → 39 passed ✅ (35 + 4 new)
```

```
$ DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py
  → 11/11 passed ✅  (E2E 用 fallback 路径，会走 helper 但 baseline_questions 为空)
```

**用户体验验证**：用户新建训练后访问 `?page=daily&training_id=8` 现在能看到 3 个真实任务（之前只看到 placeholder "今日训练 (待初始化)"）。

## 新增的回归测试（`TestPopulateScheduleAndRecall`，4 个）

| 测试方法 | 锁住的不变量 |
|---|---|
| `test_units_populated_from_specialized_materials` | helper 把基线题+每个素材都转成 unit |
| `test_recall_units_seeded_from_baseline_questions` | 3 道基线题正确进入 recall_units，dimension 字段保留 |
| `test_handles_no_baseline_questions` | 用户跳过基线诊断时，helper 仍能派生 units（无基线 unit） |
| `test_units_capped_at_max` | 50 个素材只取前 12 个，保护 daily 卡可读性 |

## 局限与后续

1. **基线 dimension 升级** —— 当前所有 unit dimension = `concept`，基线题有 concept/read/write 三维。下次可基于题目的 dimension 主成分给 unit 打 label（`practitioner` heuristic），让 `DEFAULT_DAILY_RATIO` 分布生效
2. **特殊化召回** —— 现在每天只回 3 道基线题（占 1 个 unit）。当用户学完一个素材想深化时，需要自动从 `03_资料库.md` 提取 i+1 题目。这是 Phase 2 通用化的候选
3. **`04_复习日历.md` 周日历是模板占位** —— MD 里 `（按上面模板补充每周日历）` 是 Jinja2 模板字符串，LLM 没真正生成周历。要么 LLM 真生成周历，要么前端从 `schedule.units` 派生周历（更现实）

## Git

```
(待提交) fix(services): create_training 持久化 schedule.units + materials.recall_units，并迁移 id=8
```

## 启发

1. **写一处就别留单源真相** —— md 文件存在但 DB 没相应结构化字段，就是 "DB 看不到的 md"。任何让 UI 工作的数据**都必须在 DB 里有对应视图**
2. **`extract_today_tasks` 返回 placeholder 是预谋的"安全失败"** —— 比 crash 好，但用户感知不到。生产环境应加日志：`extract_today_tasks returned placeholder for training_id=X`（warn 级），开发者能监控到
3. **MVP 阶段的 hard cap** —— `_MAX_NEW_ITEMS_PER_DAY=3`（schedule_service）和 `_MAX_UNITS_FROM_MATERIALS=12`（本次新增）共同把"日任务卡片"控制在小屏可读范围。Phase 2 通用化时可以暴露成"每日最大新单元数"配置项

## 关联变更

- 之前 241fecb / ce65181 修 datetime 一致性
- 之前 f743d88 / dbc4693 修 UI 导航
- 本次：补**业务数据持久化层**遗漏 —— 让 daily 页能显示真实任务