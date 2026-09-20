# 20260920 · feat · 训练计划表与今日视图 proposal（未写代码）

## 变更摘要

为整条链路缺失的**调度层**（"哪一天练什么"）建立规格与选型依据。本次只产出
proposal / design / specs / tasks，**未改动任何业务代码**。

要解决的具体问题：`training-path-generation` 明确把每日排期列为非目标（"属调度器"），
但**没有任何 change 拥有这个调度器**，于是新链路用"当前阶段待练项前 5 条"的**游标**顶替计划表，
导致：每天都有任务但看不出"这是第几次"、今日任务没有首页入口、
每道题固定 5 次的巩固（第 1/3/7/15/30 天）完全不存在、勾选即 `passed` 使"练过"与"达标"混为一谈。

而"按日期排的训练计划"本来就是需求：已归档的 `daily-execution` spec 写着「按当前日期从复习日历抽取」，
其载体 `04_复习日历.md` 已按 ADR-0017 降级为导出物 → 需求与载体脱节。本 change 把载体换成数据库计划表。

## 产出

| 文件 | 内容 |
|---|---|
| `.../training-plan-and-daily-view/proposal.md` | Why / What Changes / 八条关键取舍 / 非目标 / Capabilities / Impact / 与进行中 change 的协调 |
| `.../design.md` | D1 计划表 → D10 日期口径；迁移与兼容；风险表；5 条待决问题 |
| `.../specs/training-plan/spec.md` | 新增能力：6 条 Requirement（5 次阶梯 / 每日引入新题 / 到期日聚合 / 累计顺延 / 练过≠达标 / 变更留痕） |
| `.../specs/question-bank/spec.md` | 新增能力：3 条 Requirement（唯一稳定标识 / 练过入池 / 冷却期与排除原题） |
| `.../specs/daily-execution/spec.md` | 改写「系统呈现今日任务卡」（数据源改为计划表 + 双粒度视图 + 待补区） |
| `.../specs/progress-dashboard/spec.md` | 改写「首页展示训练列表与项目说明」（首屏新增「今日训练」区块） |
| `.../tasks.md` | 8 组 38 项任务，每项写明验收方式 |

### 核心设计决定

1. **每道题固定 5 次**：锚点 = 该题**被排入计划那天**，到期日 = 锚点 +1/+3/+7/+15/+30 天；**第 5 次之后不再出现**（不做维护复习）。
2. **取消"每周频次 / 休息日"**：排期不再依赖 `weekly_frequency`，每天是否练由"当天到期的阶梯"决定；`horizon_weeks` 一并废弃，`daily_budget_minutes` 保留并改义为"每天新引入题目的时长上限"。
3. **每天引入新题**：按阶段顺序与每日时长上限分批引入；单日负荷 = 到期项 + 昨日累计项 + 新题，超量时**优先保留到期与累计项**、推迟新题。
4. **未完成累计到次日**：保留 `original_date`，不删项、不裁剪、不自动掩盖；轮次顺序是硬约束。
5. **勾选 = 练过**（新增 `practiced`），`passed` 只由达标判定写（`training-execution-feedback` 5.1）。
6. **题目唯一标识必须跨重生成稳定**（新增 `item_key`）：现状 `save_skeleton` 先删后插，重生成会换 id，不修就会让"练过的 ID 入题库"指向消失的行。
7. **题库 + 每两周测验**：练过即入池，练完 5 次仍保留；抽取时 MUST 排除冷却期内的原题（ADR-0016），判分仍归 `periodic-assessment`。
8. **今日视图以跨训练聚合为主入口**（首页顶部），任务卡保留"全部 / 仅某训练"切换，空态显示"下次有任务的日期"。

### 显式记录的待决问题（5 条，见 design.md）

锚点口径（该题入计划日 vs 训练创建日）、每日时长上限的形态、冷却期取值（14 天 / 3 次）、首次测验的锚点、题目内容存文本还是存指针。

### 修正记录（用户两次更正）

1. **2026-09-20 第一次更正**：初稿写成"按自然周的星期几均匀分布（周一/周三/周五，排除周末）" → 改为以**训练创建日**为锚点的相对天数递推。
2. **2026-09-20 第二次更正（本版）**：进一步确认 **"没有每周只练几次、没有休息日；总共五次即 T1/T3/T7/T15/T30，练完不再练；有事累计到下一天；每两周一次测验，测验从题库抽题"** →
   改为**固定 5 次阶梯 + 每日引入新题 + 累计顺延 + 两周测验**，并新增 `question-bank` capability；
   参数模型变更记入任务 0.1（必须先写 ADR-0021 取代 ADR-0006 的投入参数模型）。

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `training-plan` / `question-bank` 两个 capability；修改 `daily-execution`、`progress-dashboard` 各一条 Requirement
- **决策**：引用 ADR-0001（排期由规则算）、ADR-0011（单次负荷与总量分离）、ADR-0016（排除近期原题）、ADR-0017（md 是导出物）、ADR-0009（列表式主视图）；**待写 ADR-0021**（取代 ADR-0006 参数模型）
- **数据模型影响（实现阶段）**：新增 `plan_items` / `question_bank`；`training_items` 增 `item_key` + `practiced` 状态（需重建表，按迁移三件套控制风险）
- **验证**：`openspec validate --all --store store` = **13 passed, 0 failed**；`openspec status` = 4/4 artifacts complete

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/training-plan-and-daily-view/` | 新增（proposal / design / 4 份 specs / tasks） |
| `workspace/evidence/20260920-服务层代码审计.md` | 引用（M1 / M2 / M4 与本 change 的对应关系） |
| `workspace/decisions/ADR-0016-测验题不得取自刚练过的原题.md` | 约束题库抽取（冷却期） |

## 与既有 change 的边界

- **不重叠修改**：勾选语义写进新 capability `training-plan`，避免与 `training-execution-feedback` 正在修改的
  `daily-execution`「用户能勾选完成任务并填写三省」Requirement 冲突；测验判分仍归 `periodic-assessment`。
- `training-path-generation`：本 change 只消费其 `training_items`，不改其 spec。
- `org-and-roles`（已后置）：企业版回答"谁要练"，本 change 回答"哪天练什么"。

## 关联 OpenSpec change id

`training-plan-and-daily-view`（状态：刚创建，未开始实现；尚未 apply）
