# 20260921 · feat · 作答记录 + 达标判定 + 四失客观通道接通

## 变更摘要

补上审计报告里 **M1（四失反馈没有闭环）** 的数据前提与执行点：

1. **逐次作答记录**（`practice_attempts`）：每次"答对 / 答错"落一条，成为**客观表现的唯一数据源**；
2. **达标判定**（`attempt_service.mark_mastered_if_ready`）：连续 2 次通过 → `training_items.status='passed'` +
   `mastered_at`，这是**唯一**写"达标"的地方（勾选只写 `practiced`）；
3. **客观通道接通**：四失反馈不再恒为"数据不足"——`objective_for_training()` 按最近 5 次作答算准确率，
   按 ADR-0015 的阈值给出 `low / mid / high / unknown`，并传给 `signal_service.process_signal(objective=...)`；
4. **结构性动作的执行点**（`signal_service.apply_decision`）：`raise_difficulty` / `lower_difficulty` 真的调整
   `training_items.difficulty_tier`（1..4），前后取值写进 `adjustment_log.detail`；`reduce_load` / `expand_scope`
   按 ADR-0021 只留痕不假装调整（题量不裁剪、补资料属人工动作）。

## 产出

| 文件 | 内容 |
|---|---|
| `src/core/mastery.py`（新增） | 纯函数：`consecutive_passes`、`accuracy`、`evaluate`、`objective_state`、`difficulty_delta`；常量 `MASTERY_STREAK=2`、`MIN_ATTEMPTS_FOR_OBJECTIVE=3`、`ACCURACY_LOW/HIGH=0.6/0.9` |
| `src/services/attempt_service.py`（新增） | `record_attempt` / `recent_results` / `item_mastery` / `training_accuracy` / `objective_for_item` / `objective_for_training` / `mark_mastered_if_ready` / `record_and_evaluate` |
| `src/db/tables.sql` | 新增 `practice_attempts` 表；`training_items` 增 `mastered_at` 列 |
| `src/db/migrate.py` | 训练项重建时补 `mastered_at`（老库缺列也能迁，列缺失用 `NULL` 兜住） |
| `src/db/models.py` | 新增 `PracticeAttempt` 模型；`TrainingItem` 增 `mastered_at` |
| `src/db/queries.py` | 级联删除补 `practice_attempts` |
| `src/services/path_service.py` | 新增 `adjust_difficulty`（按稳定题目键调难度档位，返回 before/after） |
| `src/services/plan_service.py` | 新增 `item_id_for`（信号归因用） |
| `src/services/signal_service.py` | `process_signal` 支持 `objective` / `item_key` 入参；新增 `apply_decision`（动作执行点） |
| `src/ui/page_daily.py` | 每个训练项加「✓ 答对 / ✗ 答错」按钮与"近 N 次准确率 · 连续通过"摘要；四失区显示客观口径，并把反馈关联到当前训练项 |
| `tests/test_attempt_service.py`（新增） | 11 个用例：连续通过/准确率/客观档位/难度增量的纯函数、作答校验、连续 2 次达标写 `passed`+`mastered_at`、客观通道随作答变化、`too_easy`+低准确率被拦截、难度执行点只改难度不改排期 |

## 关键实现细节

1. **"没有数据"不能冒充"表现差"**：`accuracy([])` 返回 `None`，`objective_state` 在作答 < 3 次时返回 `unknown`
   ——这正是修复前系统的病根：因为永远没有作答数据，客观通道永远是"数据不足"，任何反馈都只能降级成轻微提示。
2. **达标只有一个写入点**：`mark_mastered_if_ready`（依据 `practice_attempts` 的最近两次都是 `pass`）。
   勾选/答题按钮都只写 `practiced`，避免出现第二个"达标"来源。
3. **执行点诚实**：难度动作真实改库并记 before/after；`reduce_load`（题量）按 ADR-0021 **不裁剪**，
   `expand_scope`（范围）需要补资料/重生成路径，二者都只留痕并写清原因——不制造"已调整"的假象。
4. **排期与难度解耦**：难度调整不动 `plan_items.due_date`（单测断言 5 个轮次日期不变）。

## 验证

| 项 | 结果 |
|---|---|
| 全量单测 | **188 passed, 1 skipped, 30 subtests**（新增 11 个用例；改动前 177） |
| 真实库迁移 | 备份 `/tmp/trainer_before_attempts.db` → `init-db` → `PRAGMA foreign_key_check` = 0、`quick_check` = ok；`training_items.mastered_at` 与 `practice_attempts` 已就位 |
| 迁移未丢数据 | 迁移前后逐表对比一致（`trainings` 4、`training_paths` 1、`training_items` 19、`plan_items` 97） |
| 线上数据 | 训练 #50（Redis 八股，19 题）：今天 9/21 第 1 轮 **19 项 / 约 300 分钟**，下一次到期 9/23，进度 0/95 次 |
| 服务 | 已用新代码重启并验证 `/_stcore/health` = 200 |

## 影响范围

- **数据**：新增 `practice_attempts` 表与 `training_items.mastered_at`；迁移走已演练的三件套
- **行为**：任务卡新增答对/答错按钮；四失反馈现在带真实客观口径，冲突时按 ADR-0015 拦截；达标首次成为可达状态
- **规格**：`training-plan-and-daily-view` 任务 1.5 完成；`training-execution-feedback` 的"日常作答记录"与
  "连续 2 次达标"两半已完成（已在该 change 的 tasks.md 里加注，测验批次表与"判据满足"仍待做）
- **未做（下一批）**：测验批次的取题与判分（`assessments` / `assessment_items`）、达标判定里的"判据满足"
  （与 `acceptance` 口径比对）、`expand_scope` 的自动化、任务卡"全部 / 仅某训练"范围切换、`check_budget` 口径重写

## 相关文件路径

- 代码：见上表
- 规格：`workspace/store/openspec/changes/training-plan-and-daily-view/tasks.md`（1.5 勾选完成）、
  `workspace/store/openspec/changes/training-execution-feedback/tasks.md`（1.3 / 5.1 加注进度）
- 决策：`workspace/decisions/ADR-0015-主观信号与客观表现双通道冲突时以客观为主.md`、`ADR-0010`、`ADR-0021`
- 审计关联：`workspace/evidence/20260920-服务层代码审计.md` 的 **M1**（本条即其修复）与 **M2**（勾选语义）

## 关联 OpenSpec change id

`training-execution-feedback`（13/33 → 已完成日常作答与连续达标部分）＋ `training-plan-and-daily-view`（1.5 完成）
