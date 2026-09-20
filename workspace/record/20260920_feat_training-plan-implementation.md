# 20260920 · feat · 训练计划表与今日视图（数据层 + 服务层 + UI 接线）

## 变更摘要

把 change `training-plan-and-daily-view` 的**第 0–5 组任务**落地：新增训练计划表与题库表、排期领域层、
计划服务，并把首页「今日训练」、今日任务卡、路径确认三处接上。勾选语义从"勾上即 `passed`（达标）"改为
**勾上即 `practiced`（练过）**，`passed` 只留给后续的达标判定。

排期口径按用户 2026-09-20 确认的模型（ADR-0021）：

> 锚点 = 训练创建日；第 1/3/7/15/30 天各过一遍全部题（共 5 轮）；练完即止；
> 未完成的项累计到次日；每 14 天一次测验，测验题从题库抽（冷却期 14 天）。

## 产出

| 文件 | 内容 |
|---|---|
| `src/core/plan.py`（新增） | 纯函数排期层：`ROUND_OFFSETS`、`round_due_dates`、`quiz_due_dates`、`cooldown_until`、`item_key_for`、`local_today`、`select_today_slots` |
| `src/services/plan_service.py`（新增） | `generate_plan` / `ensure_plan` / `today_tasks` / `today_summary` / `next_due_date` / `complete_tasks` / `skip_task` / `drawable_questions` / `plan_progress` |
| `src/db/tables.sql` | 新增 `plan_items`、`question_bank`；`training_items` 增 `item_key` 列与 `practiced` 状态 |
| `src/db/migrate.py` | 新增 `_rebuild_training_items`：老库补 `item_key`（回填稳定键）与新状态枚举 |
| `src/db/models.py` | `TrainingItem` 增 `item_key` 字段 |
| `src/db/queries.py` | 级联删除补上 `plan_items` / `question_bank` |
| `src/services/path_service.py` | 落库时写入稳定 `item_key`；`mark_item` 接受 `practiced` |
| `src/ui/page_home.py` | 首屏新增「今日训练」区块（跨训练聚合 + 休息日空态 + 进入任务卡） |
| `src/ui/page_daily.py` | 任务卡改从计划表取数：待补（累计）/ 今天到期 / 第 N 轮标记 / 超限只提示；勾选写 `practiced` |
| `src/ui/page_path.py` | 确认路径后自动生成 5 轮计划并提示轮次范围 |
| `tests/test_plan_service.py`（新增） | 19 个用例：5 轮日期、测验节奏、题目键稳定性、当日取数、累计不丢项、轮次顺序、勾选≠达标、题库冷却期、取消勾选保留历史、跳过需原因、跨训练聚合、老库迁移 |

## 关键实现细节

1. **稳定题目键**（`item_key_for`）：`sha1(training_id + 知识点 + 规范化标题)[:12]`。
   计划表与题库**一律引用 `item_key`，不引用会随路径重生成变化的 `training_items.id`**（与审计报告 M3 同类问题）。
2. **"累计到下一天"是查询语义**：`due_date <= 今天` 且未完成的项都算今天该做，`original_date` 保留首次到期日；
   不在读页面时改库。
3. **轮次顺序是硬约束**：同一题目只取**最早未完成的那一轮**，避免"跳过第 1 轮直接做第 4 轮"的假进度。
4. **勾选做三件事**：`plan_items.status='practiced'`、`training_items.status='practiced'`（不覆盖 `passed`）、
   题目登记进 `question_bank` 并把 `cooldown_until` 推到"练过日 + 14 天"（ADR-0016）。
   同时仍写 `daily_log_tasks`（`P{plan_id}`），保证完成度与奖励机制的既有逻辑可用。
5. **单日负荷只提示不裁剪**（ADR-0021 决策 4）：当日预计总时长超过 `daily_budget_minutes` 时给提示，任务条数不变。
6. **本地时区统一口径**：`local_today()` 用 `Asia/Shanghai`（可用 `TRAINER_TZ` 覆盖），供排期 / 打卡 / 后续限频共用。

## 验证

| 项 | 结果 |
|---|---|
| 全量单测 | **175 passed, 1 skipped, 30 subtests**（新增 19 个用例，无回归；改动前为 156） |
| 老库迁移（真实库副本） | 27 条 `training_items` 全部回填 `item_key`；`PRAGMA foreign_key_check` = 0；新表 `plan_items` / `question_bank` 建好 |
| 真实数据排期 | 训练 #42（Redis 八股，27 道题）→ 5 轮 × 27 = 135 条计划项 + 2 次测验；第 1 轮到期 2026-09-21、末轮 2026-10-20；当天 27 项约 435 分钟（会触发超限提示） |
| 规格校验 | `openspec validate --all --store store` = 13 passed, 0 failed |

## 影响范围

- **数据**：新增两张表；`training_items` 重建（新增列 + 状态枚举）——迁移走已演练过的三件套
  （`isolation_level=None` + `foreign_keys=OFF` + `legacy_alter_table=ON` + 显式事务），迁移后自检 `foreign_key_check`
- **行为**：勾选不再产生"达标"；今日任务卡的数据源从"当前阶段前 5 项"改为训练计划；首页新增今日训练区块
- **参数**：`weekly_frequency` / `horizon_weeks` 不再参与排期（路径页仍展示，属历史值）；`daily_budget_minutes` 降级为提示阈值（ADR-0021）
- **未做（下一批）**：测验题抽取与判分（属 `periodic-assessment`）、逐次作答记录与达标判定、`check_budget` 口径重写、
  路径页投入参数控件的下线、老 `schedule_service` 分支标注 legacy

## 相关文件路径

- 代码：见上表
- 规格：`workspace/store/openspec/changes/training-plan-and-daily-view/`（proposal / design / 4 份 specs / tasks）
- 决策：`workspace/decisions/ADR-0021-训练排期用固定5轮锚定创建日.md`（ADR-0006 的参数口径已被其取代）
- 审计关联：`workspace/evidence/20260920-服务层代码审计.md`（M1 的执行点、M2 的勾选语义由此落地）

## 关联 OpenSpec change id

`training-plan-and-daily-view`（状态：进行中，任务 0–5 组已完成，6–7 组待做）
