# training-plan-and-daily-view · 设计文档

## Context

### 背景

训练场景里"今天练什么"是一等公民。用户的真实心智是：**创建主题 → AI 把题目排进计划表 → 首页看今天要练哪些主题的哪些题 → 勾选练过 → 到期的复习自己回来**。

现在缺的正是这层。路径只表达顺序与阶段（`training_paths` / `path_stages` / `training_items`），
"今天"由 `path_service.today_tasks()` 用**游标**现算：当前阶段待练项前 5 条 + 当前阶段已通过项前 2 条。

### 当前状态

- `daily-execution` spec 要求"按当前日期从复习日历抽取 + 1-3-7-15-30 间隔"，但其载体（十份 md）已按 ADR-0017 废弃 → **需求与载体脱节**
- `schedule_service.extract_today_tasks()` 仍保留老实现（读 `trainings.schedule` 里的 units 做间隔复习），但新链路 `schedule` 为空，实际走 `path_service.today_tasks()` 兜底（`schedule_service.py:153-188`）
- `training_paths` 已有 `horizon_weeks` / `weekly_frequency` / `daily_budget_minutes` / `budget_minutes`，但只有预算乘法在用
- 勾选把 `training_items.status` 写成 `passed`（`page_daily.py:93-95`）
- 信号限频用 UTC 日期、打卡用本地日期（`signal_service.py:78-79` vs `daily_log_service.py:38-39`）

### 约束

- 沿用 ADR-0001：**LLM 不排日期**，排期是规则层的确定性计算（纯函数，可单测）
- 沿用 ADR-0011：总量与单次负荷分离；未完成项**顺延由用户决定**，系统不擅自改总量
- 沿用 ADR-0017：结构化数据是唯一真相，md 只是导出物
- 沿用 ADR-0009：主视图是列表 + 进度，不画模型生成的图
- 不做达标判定、不做作答记录（属 `training-execution-feedback`）

### 利益相关方

- 用户本人：打开首页就知道今天练哪些主题的哪些题，不想逐个主题找
- 背八股 / 背算法题的自学者：多主题并行，主题之间要能同一天共存
- 面试讲解：需要能说清"排期为什么由规则算、复习间隔从哪来"

## Goals / Non-Goals

**Goals:**

- "今天练什么"由**计划表**回答，且一眼能看到多个主题在同一份今日训练里
- 每周期望次数（`weekly_frequency`）真正影响排期，**有休息日**
- 复习按间隔自动回来，不是"留在当前阶段"
- "练过"与"达标"在数据上分开
- 没做完的项**不会被悄悄吞掉**

**Non-Goals:**

- 不做日历月视图、拖拽改期
- 不做通知推送、不做 Agent 侧交付形态
- 不做跨训练的总负荷再平衡（只展示合计，不自动削减）
- 不做达标判定与作答记录

## Decisions

### D1 计划表是日期的唯一载体：`plan_items`

```sql
plan_items(
  id, training_id, item_id,          -- item_id -> training_items.id
  plan_date TEXT NOT NULL,           -- 本地日期 YYYY-MM-DD（Asia/Shanghai）
  kind TEXT CHECK (kind IN ('new','review','assessment')),
  ordinal INTEGER,                   -- 当日顺序
  status TEXT CHECK (status IN ('planned','practiced','deferred','skipped')),
  planned_minutes INTEGER,
  practiced_at DATETIME,
  generated_from TEXT,               -- 'path_confirm' | 'reschedule' | 'review_interval' | 'manual'
  reason TEXT,                       -- 重排原因，供留痕
  created_at DATETIME NOT NULL,
  UNIQUE (training_id, item_id, plan_date)
)
```

**为什么以日期为键**：唯一能表达"哪一天练什么"的键就是日期；
`daily_logs` 是**打卡记录**（用户点了什么），不是计划，两者不能互相代替。

复习项的 `item_id` 指向**同一个** `training_items`，不复制题目：复习是同一题的第二次出现，靠 `kind='review'` 区分。

### D2 排期生成：练习日按"距创建日的相对天数"递推

> **2026-09-20 更正**：初稿写的是"按自然周的星期几均匀分布（周一/周三/周五）"，与实际设计不符。
> 练习日**锚定训练创建日期**，按相对天数计算，与"这周周几"无关。

输入：`trainings.created_at`（锚点）、`weekly_frequency`、`daily_budget_minutes`、路径下全部 `training_items`（含阶段顺序）。

规则（纯函数，可单测）：

1. **练习日序列**：设锚点为创建日 `D0`。**第 1 次练习在创建日次日**（偏移 `1` 天），之后按 `7 / weekly_frequency` 天的节奏递推：

   ```
   offset(k) = 1 + round_half_up((k - 1) * 7 / weekly_frequency)     # k = 1, 2, 3, ...
   练习日 = D0 + offset(k) 天
   ```

   例：`weekly_frequency = 3` → 偏移 `1, 3, 6, 8, 10, 13, 15, ...`（任意连续 7 天内恰好 3 次）；
   `weekly_frequency = 7` → 每天；`weekly_frequency = 1` → 偏移 `1, 8, 15, ...`（每周一次）。
   用 **round half up**，不用 Python 内建 `round()`（银行家舍入会让 `2 次/周` 出现 `3.5 → 4` 这类跳档）。
2. **休息日** = 练习日序列之外的日期；不按自然周末特殊处理（锚点是创建日，周末只是普通一天）。
3. 每个练习日的容量 = `daily_budget_minutes`；按 `training_items` 的顺序与阶段依赖依次填入，单项预估时长缺失时用题型默认值（`memory=10 / comprehension=15 / practice=20 / prerequisite=15`，与 `check_budget` 的口径一致）。
4. 一个练习日填满容量或达到**每日条数上限**（默认 6）即停，余下的顺序顺延到下一个练习日。
5. **阶段顺序是硬约束**：前一阶段还有未排入日期的项时，后一阶段的项不得先排进更早的日期。
6. **锚点已过去时的对齐**：排期在"确认路径"时生成，而用户可能创建后隔了几天才确认。此时**跳过已经过去的练习日**，从今天起按同一公式继续对齐（保持"每 7 天 `weekly_frequency` 次"的节奏），MUST NOT 把训练项排进过去的日期。
7. 全部排完后若还有剩余练习日（说明路径偏松，与 `check_budget` 的 `too_light` 对应），MUST 在计划页提示"可增加内容或减少投入"，不得自动塞题。

**为什么锚定创建日而不是"确认路径日"**：创建日是用户可预期、不会因流程快慢而漂移的起点（"我 9 月 20 日建的训练，第二天开始练"）。用确认路径日会让同一条路径因为用户多花了 3 天选资料而完全不同。

**为什么一次排完骨架**：用户承诺的投入参数只在"确认路径"那一刻是确定的；排完骨架才能回答"哪天练完""这周有几天的空档"，也才能把休息日算进去。后续新增/变更（复习插入、结构性调整、用户改投入）都是对骨架的**增量重排**。

**取消老 spec 的 3:4:3 硬比例**：新链路的题型由路径生成决定（`memory/comprehension/practice/prerequisite`），
硬比例会与"覆盖模式必须覆盖全部必修知识点"（ADR-0011）冲突。题型分布改为**展示维度**（计划页显示当日题型构成），不再是排期约束。

### D3 复习插入：以"练过那天"为起点按间隔阶梯落位

> **2026-09-20 更正**：间隔的起算点是**练过的那一天**（不是练习日序列、也不是创建日），"后面一天、第三天、第七天"依此类推。

- 计划项被标记 `practiced` 时，记录 `practiced_at`，并以**当天**为起点 `T0`；
- 复习项日期 = `T0 + 1`、`T0 + 3`、`T0 + 7`、`T0 + 15`、`T0 + 30` 天（沿用 `STANDARD_INTERVALS`），次数上限 5 次；超出后不再自动复习，只保留在"我可重练"入口；
- **复习日直接落位、不挪动**：复习间隔是时间敏感的学习机制，即使落在休息日，也在当天出现（那天就不再是休息日）；
- **新学让位给复习**：若某天的复习项 + 已排新学项超出 `daily_budget_minutes`，把**当天的新学项**顺延到下一个练习日，不挪动复习项（并在计划页显示"复习挤压"提示）；
- **复习项占当日常量上限**：不超过当日计划项总数的 1/2，且不超过 2 条（避免复习压垮单日负荷）；
- 同一训练项在同一日期只允许一条计划项（`UNIQUE(training_id, item_id, plan_date)`），重复标记练过不产生重复复习项。

### D4 勾选语义：`practiced` ≠ `passed`

- 勾选计划项 → `plan_items.status='practiced'` + `training_items.status='practiced'`（新增状态值）+ `practiced_at`；
- 取消勾选 → 回到 `planned` / `pending`，但**保留 `practiced_at` 历史**（不抹掉证据）；
- `passed` **只能**由达标判定写入（`training-execution-feedback` 5.1：判据满足且连续 2 次达标）；
- 达标判定落地前，UI 文案 MUST 用"今天练过"，MUST NOT 出现"已达标"（现状 `page_path.py:20` 的「✅ 已达标」需改）。

`training_items.status` 枚举需要新增值 → **SQLite 无法改 CHECK 约束，必须重建表**：
沿用 HANDOFF 第 5 节的迁移三件套（`isolation_level=None` + `foreign_keys=OFF` + `legacy_alter_table=ON` + 显式事务 + `foreign_key_check`）。

### D5 顺延：显式出现，由用户决定怎么补

- 到期未勾选的计划项，次日进入"待补"区（`status` 仍为 `planned`，`plan_date` 不改，UI 按 `plan_date < today` 聚合为"待补"）；
- 用户可选三种处理：**顺延到今天**（改 `plan_date`，写 `reason`）、**保持原样**（继续挂在待补区）、**标记跳过**（`skipped`，必须记原因，且**不减少覆盖**——覆盖模式下跳过只是延后，不代表知识点完成）；
- 系统 MUST NOT 自动把待补项删掉或挪到别处；也 MUST NOT 自动延长截止日（ADR-0011 决策 4）。

### D6 今日视图：跨训练聚合为主入口

- **首页顶部**新增「今日训练」区块：`SELECT ... WHERE plan_date = 今天`，按训练分组，显示每组条数与预计时长，以及跨训练合计；
- 首页区块提供两个入口：进入**今日任务卡（跨训练）**、进入某个训练的**单训练视图**；
- 「今日任务卡」保持单页，但增加"全部 / 仅某训练"的范围切换；
- 今天没有任何计划项时，首页显示「今天是休息日（下次：X 月 X 日，预计 N 项）」——**空态必须是有信息的空态**；
- 主页面的指标区保持只读（`progress-dashboard` 的「仪表盘只读」requirement 不变）。

与 `org-and-roles` 的边界：企业版回答"**谁**要练"（培训任务分配给人），本 change 回答"**哪天**练什么"（题目排到日期）。两者不重叠。

### D7 与 `learning-signal` 的分工：动作落在排期上

`learning-signal` 定义"信号 → 动作方向"，本 change 提供动作的**执行点**：

| 动作 | 执行点 |
|---|---|
| `reduce_load`（太多了） | 次日计划条数 = `ceil(当日条数 / 2)`（下限 1），把被削减的项顺延；写 `reason='too_much'` |
| `raise_difficulty` / `lower_difficulty` | 改 `training_items.difficulty_tier`（±1，限制 1..4，保留 `difficulty_basis` 原值），**不改排期日期** |
| `expand_scope`（太窄了） | 在**下一个练习日**插入来源中相邻知识点的计划项（从同来源未排入的 `training_items` 里取）；若路径里没有相邻项，则只记录并提示"需要补充资料" |
| `light_hint` / `none` | 不动排期，只写日志 |

所有执行点都必须写 `adjustment_log` 的**调整前后取值**（该表已有 `detail` 字段，缺的是取值对比，本 change 补齐）。

### D8 日期口径统一为本地时区

全部"今天"的判定统一走一个函数（如 `src/core/clock.py: today_local()`，时区 `Asia/Shanghai`，可用环境变量覆盖），
`plan_items.plan_date`、`daily_logs.log_date`、信号限频的"当天"都用它。
修掉现在"信号限频按 UTC、打卡按本地"的分叉。

## Migration / 兼容

- 新增表 `plan_items` 走 `tables.sql` + `migrate.py`；**注意**：本轮审计已发现两份 DDL 会漂移（`workspace/evidence/20260920-服务层代码审计.md` S3），实现时 SHOULD 只保留一份真相，或至少加一条"两份必须一致"的检查
- `training_items.status` 新增 `practiced` → 重建表（迁移三件套）
- 老训练（已 confirmed、有路径、无计划）：首次进入首页/训练时按当前路径生成一次计划，MUST 幂等（`UNIQUE(training_id, item_id, plan_date)` + 生成前检查该训练是否已有计划）
- 老训练（无路径）：不生成空计划，首页显示"尚未生成训练计划"
- `schedule_service` 的老文件式分支：新链路不再走，保留代码但标注为 legacy（不删，遵循"企业版/老流程后置不删"的既有做法）

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| 均匀分布的练习日与真实作息不符 | 用户看不到"自己的周几" | 提供"改投入"与练习日偏好开关；顺延不丢项 |
| 一次排完骨架后进度落后 | 计划表与实际脱节 | 待补区 + 重排入口（保留历史，不覆盖记录） |
| 复习项挤占新学 | 新内容推进变慢 | 复习占当日上限 1/2 且 ≤2 条；超出顺延 |
| 多训练同时排在同一天 | 单日负荷叠加超预算 | 第一版只展示合计并提示，不做自动再平衡（明确列为非目标） |
| 状态枚举新增值触发迁移 | 数据库迁移是最高风险动作 | 复用已演练过的迁移三件套 + 迁移后 `foreign_key_check` 自检 |

## 待决问题（Open Questions）

1. **第 1 次练习是否固定为"创建日次日"（不管频率高低）**？当前规则是"次日一定练一次，之后按 `7 / 频次` 递推"。如果频率很低（如每周 1 次），是否也应该次日先练一次，而不是等第 8 天？
2. 每日条数上限默认 6 是否合适？（`daily_budget_minutes / 平均单项时长` 也能算出上限，二者取小更稳）
3. 复习次数上限 5 次之后是否需要一个"维护复习"（更长间隔，如 60/120 天）？ADR-0018 提到"已掌握只保留低频维护复习"，本 change 未实现该低频档
4. 首页"今日训练"与现有首页指标区的布局顺序（建议：今日训练在最上，指标在下）
5. 跨训练合计超出单日可承受量时，是否需要一个"今天只做这些"的裁剪动作？（当前列为非目标）
