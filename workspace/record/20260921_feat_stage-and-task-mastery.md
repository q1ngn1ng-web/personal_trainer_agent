# 20260921 · feat · 阶段达标与任务达标

## 变更摘要

把"练到什么程度算完成"落成确定状态（change `training-execution-feedback` 的任务 5.2 / 5.3，ADR-0011）：

1. **阶段达标**：覆盖模式看本阶段必修项是否**全部 `passed`**；达成模式看 `goal_json.acceptance` 的验收判据
   （accuracy / volume / streak），**判不了就退回覆盖口径**（speed、质性判据 → 不放水）。
2. **阶段状态写回**：达标/进行中/待解锁写回 `path_stages.status`——顺手修掉审计报告 **S6**
   "阶段永远 locked、路径页与任务卡自相矛盾"的老问题。
3. **任务达标**：必修覆盖 100%（全部训练项 `passed`）**且**最近一次完成的测验通过 → 训练进入
   **`completed` 终态**（`trainings.status` 新增该枚举值，重建表迁移）。

## 产出

| 文件 | 内容 |
|---|---|
| `src/core/mastery.py` | 新增纯函数：`coverage_satisfied`、`acceptance_satisfied`、`stage_mastered`、`StageVerdict`、`COVERAGE_MODE` / `MASTERY_MODE` |
| `src/services/mastery_service.py`（新增） | `stage_statuses` / `sync_stages` / `training_progress` / `sync_training_status` / `evaluate` |
| `src/core/goal.py` / `src/core/element.py` | `TrainingStatus` 新增 `COMPLETED`，状态迁移表允许 `confirmed/active/paused → completed` |
| `src/db/tables.sql` / `src/db/migrate.py` | `trainings.status` CHECK 加入 `completed`；迁移**只搬运新旧表共有的列**（老库少列不再让迁移直接失败） |
| `src/db/queries.py` | `_TRAINING_STATUSES` 加入 `completed` |
| `src/ui/page_path.py` | 新增「达标进度」区块；阶段锁定态改读 `path_stages.status`（不再永远 locked）；`completed` 训练可查看 |
| `src/ui/page_home.py` / `src/ui/page_training.py` | 状态徽标/标签补 `completed`（🎉 已达标） |
| `tests/test_mastery_service.py`（新增） | 10 个用例：覆盖/达成两种模式、判据判不了时退回覆盖、阶段状态写回、覆盖满但测验未过不达标、达标后训练置 `completed`、老库状态 CHECK 迁移与幂等 |

## 关键实现细节

1. **两种模式都按 ADR-0011 落地**：`coverage`（企业培训/考证，必须覆盖全部）与 `mastery`（自定目标，达标即止）。
   注意 `mode` 目前仍是路径默认值 `mastery` + 无 UI 选择入口（审计 S-ADR-0011），本批只把判定逻辑做实。
2. **判不了就不放水**：`acceptance_satisfied` 对 `speed`（没有耗时数据）与质性判据返回 `None`，
   阶段判定此时**退回覆盖口径**，并在页面上写明原因。
3. **任务达标是唯一终态来源**：`sync_training_status` 只在"覆盖 100% + 测验通过"时把训练置 `completed`，
   并在 `path_stages` 全部标 `completed`。
4. **迁移更稳了**：`_rebuild_trainings` 改为只搬运新旧表**共有**的列（缺列交给新表默认值），
   这是上次审计提到的"老库少列会直接让迁移失败"的修法。

## 验证

| 项 | 结果 |
|---|---|
| 全量单测 | **206 passed, 1 skipped, 30 subtests**（新增 10 个用例；改动前 196） |
| 规格校验 | `openspec validate --all --store store` = 13 passed, 0 failed |
| 关键负例 | "覆盖满但测验未过" → `mastered=False`，原因写明"还没有通过的测验"；达成模式目标设 1.0 → 单次练习不算达标 |
| 迁移 | 老库（`trainings.status` CHECK 无 `completed`）迁移后老状态保留、可写 `completed`、重复迁移返回空 |

## 影响范围

- **数据**：`trainings` 重建（CHECK 加 `completed`）——走已演练的迁移三件套；`path_stages.status` 开始被真正写入
- **行为**：路径页显示"必修覆盖 x/y + 测验状态"；阶段显示"已达标 / 进行中 / 待解锁"；任务达标后训练进 `completed`
- **未做**：覆盖模式/达成模式的**用户选择入口**（`mode` 仍取默认值）、阶段末触发测验、复盘页指标、`5.3` 的"必修/选修"区分（当前全部训练项都算必修）

## 相关文件路径

- 代码：见上表
- 规格：`workspace/store/openspec/changes/training-execution-feedback/tasks.md`（5.2 / 5.3 勾选）
- 决策：`workspace/decisions/ADR-0011-总量与单次负荷分离覆盖模式与达成模式.md`、`ADR-0010`
- 审计关联：`workspace/evidence/20260920-服务层代码审计.md` 的 **S6**（阶段锁态）与 ADR-0011 条目

## 关联 OpenSpec change id

`training-execution-feedback`（阶段/任务达标完成；仅剩阶段末触发、重考换新题、复盘页指标）
