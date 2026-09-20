# 20260920 · feat · 目标澄清与确认（apply）

## 变更摘要

实现 `goal-clarification-confirm`：把「填写主题」改成「描述学习内容 → AI 追问 → 用户确认目标」。
这是个人版闭环的第一环，也是第一个真正落地的 change。

## 实现内容

| 层 | 文件 | 内容 |
|---|---|---|
| 领域 | `src/core/goal.py` | 状态机（draft → pending_confirm → confirmed → active）、字段来源、验收判据校验、合并优先级、追问双限，全部纯函数 |
| LLM | `src/llm/schema.py` / `prompts.py` / `fallback.py` | 新增 `goal_clarification` 用途：Schema、prompt（明令禁止问周期/频次/时长）、降级为表单式追问 |
| 数据 | `src/db/tables.sql` / `migrate.py` / `models.py` / `queries.py` | `trainings` 新增 `goal_json` / `goal_confirmed_at` / `clarification_rounds` 与三个新状态；`llm_calls` 新增用途；迁移可重复执行 |
| 服务 | `src/services/goal_clarification_service.py` | 开始会话 / 继续追问 / 确认目标 / 恢复会话 |
| UI | `src/ui/page_new_training.py` | 第 1 步改为「描述 → 追问 → 草案确认」，草案页标出「系统建议」，未确认不显示下一步 |
| 测试 | `tests/test_goal_clarification.py` / `tests/test_goal_flow.py` | 纯函数单测 + 服务流程测试，合计新增 33 项 |

## 关键设计落地

1. **三个字段是值不是布尔标记**：`content` / `level` / `acceptance` 存具体取值，`status` 与 `goal_confirmed_at` 才表示"已确认"
2. **验收判据必须可判定**：量化判据要 `metric` + `target`；质性判据要可观察；纯主观形容词（"比较熟练"）判为不合格
3. **追问双限**：软限 2 轮给建议值，硬限 3 轮强制收口并标 `inferred`
4. **AI 不得覆盖用户值**：`merge_goal` 的优先级写死
5. **澄清阶段不碰投入参数**：prompt 里明令禁止询问周期 / 频次 / 时长
6. **历史数据兼容**：`created` 读取时按 `draft` 处理，迁移把 `status` 的 CHECK 扩到 8 个值

## 一个必须记下的坑（迁移把生产库改坏过）

首次执行迁移时，`data/trainer.db` 被改成了半迁移状态：真实数据留在 `trainings_old`，`trainings` 变成空表，子表外键被改写成指向 `trainings_old`。

**两个根因**：

1. **Python `sqlite3` 的隐式事务**：默认 `isolation_level` 会在 DDL 前隐式提交，导致重建表中途失败时留下半成品
2. **`ALTER TABLE RENAME` 会改写其他表的外键引用**：只关 `foreign_keys` 还不够，必须同时打开 `legacy_alter_table`

**修复动作**：

1. 备份到 `/tmp/trainer.db.bak`，把 `trainings_old` 改名回 `trainings`
2. 重建 4 张子表（`daily_logs` / `baseline_history` / `llm_calls` / `review_archives`）修掉外键指向
3. 重建 `daily_log_tasks` 修掉它对 `daily_logs_old` 的引用
4. `migrate.py` 改为：`foreign_keys=OFF` + `legacy_alter_table=ON` + `isolation_level=None` + 显式 `BEGIN IMMEDIATE / COMMIT / ROLLBACK`

**结果**：修复后 `trainings` 3 条、子表行数与迁移前一致、`PRAGMA foreign_key_check` 为 0，迁移可重复执行。

## 影响范围

- 代码：6 个模块新增或修改，2 个测试文件
- 数据：`data/trainer.db` 执行过一次真实迁移（数据无丢失）
- 规格：`goal-clarification-confirm` 的 28 项任务全部完成，change 已归档
- 证据：`workspace/evidence/20260920-目标澄清与数据迁移.md`

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/core/goal.py` | 新增 |
| `src/services/goal_clarification_service.py` | 新增 |
| `src/db/migrate.py` | 新增 |
| `src/db/tables.sql`、`models.py`、`queries.py`、`sqlite.py` | 修改 |
| `src/llm/schema.py`、`prompts.py`、`fallback.py` | 修改 |
| `src/ui/page_new_training.py` | 修改 |
| `tests/test_goal_clarification.py`、`tests/test_goal_flow.py` | 新增 |
| `workspace/evidence/20260920-目标澄清与数据迁移.md` | 新增 |

## 关联 OpenSpec change id

`goal-clarification-confirm`（已 apply 并归档）
