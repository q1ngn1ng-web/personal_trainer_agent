# 20260920 · feat · 训练计划表与今日视图 proposal（未写代码）

## 变更摘要

为整条链路缺失的**调度层**（"哪一天练什么"）建立规格与选型依据。本次只产出
proposal / design / specs / tasks，**未改动任何业务代码**。

要解决的具体问题：`training-path-generation` 明确把每日排期列为非目标（"属调度器"），
但**没有任何 change 拥有这个调度器**，于是新链路用"当前阶段待练项前 5 条"的**游标**顶替计划表，导致四件事：
每天都有任务（`weekly_frequency` 不参与排期，没有休息日）、今日任务没有首页入口、
间隔复习（1/3/7/15/30）失效、勾选即 `passed` 使"练过"与"达标"混为一谈。

而"按日期排的复习计划"本来就是需求：已归档的 `daily-execution` spec 写着「按当前日期从复习日历抽取」，
其载体 `04_复习日历.md` 已按 ADR-0017 降级为导出物 → 需求与载体脱节。本 change 把载体换成数据库计划表。

## 产出

| 文件 | 内容 |
|---|---|
| `.../training-plan-and-daily-view/proposal.md` | Why / What Changes / 七条关键取舍 / 非目标 / Capabilities / Impact / **与进行中 change 的协调** |
| `.../design.md` | D1 计划表结构 → D8 日期口径；迁移与兼容；风险表；5 条待决问题 |
| `.../specs/training-plan/spec.md` | 新增能力：6 条 Requirement |
| `.../specs/daily-execution/spec.md` | 改写「系统呈现今日任务卡」（数据源改为计划表 + 双粒度视图 + 待补区） |
| `.../specs/progress-dashboard/spec.md` | 改写「首页展示训练列表与项目说明」（首屏新增「今日训练」区块 + 休息日空态） |
| `.../tasks.md` | 7 组 33 项任务，每项写明验收方式 |

### 核心设计决定

1. **计划表是日期的唯一载体**（`plan_items`：日期 × 训练 × 训练项 × 类型 × 状态），`daily_logs` 只是打卡记录。
2. **排期锚定训练创建日**：第 1 次练习在创建日次日，之后按 `7 / weekly_frequency` 天递推（< 7 次必有休息日；不按自然周几、不特殊处理周末）；每日容量由 `daily_budget_minutes` 与题型默认时长决定，阶段顺序是硬约束。
3. **间隔复习以"练过当天"为起点**：复习日 = 练过日 + 1/3/7/15/30 天；复习日到点直接落位（不因落在休息日而挪动），与新学撞车时顺延新学项；复习占当日上限 1/2 且 ≤ 2 条。
4. **勾选 = 练过**（新增 `practiced` 状态），`passed` 只由达标判定写（`training-execution-feedback` 5.1）。
5. **未完成项显式顺延**，顺延 / 保持 / 跳过由用户选，系统不擅自改总量、不自动延长周期（ADR-0011 决策 4）。
6. **今日视图以跨训练聚合为主入口**（首页顶部），今日任务卡保留"全部 / 仅某训练"切换；空态显示休息日与下次练习日。
7. **取消老 spec 的「概念/读/写 3:4:3 硬比例」**：新链路题型来自路径生成，硬比例与"覆盖模式必须覆盖全部必修知识点"冲突，题型分布降为展示维度。
8. **与 `learning-signal` 的分工**：动作规则仍属该 capability，本 change 提供执行点（`reduce_load` → 次日条数、难度动作 → `difficulty_tier`、`expand_scope` → 插入相邻知识点）。

### 显式记录的待决问题（5 条，见 design.md）

第 1 次练习是否固定为创建日次日（频率低时是否也如此）、每日条数上限、5 次复习后的"维护复习"档、首页布局顺序、跨训练合计超量是否要裁剪。

### 2026-09-20 修正（用户更正）

初稿把练习日写成"按自然周的星期几均匀分布（周一/周三/周五，排除周末）"，**与实际设计不符**。
正确口径：练习日锚定**训练创建日期**（"第二天会训练一次"，之后按 `7 / 频次` 递推）；复习间隔以**练过的那一天**为起点（+1、+3、+7、+15、+30）。
proposal / design（D2、D3）/ tasks（2.1、3.2）/ `training-plan` spec 已按此更正。

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `training-plan` capability；修改 `daily-execution`、`progress-dashboard` 各一条 Requirement
- **决策**：引用 ADR-0001（排期由规则算）、ADR-0011（总量与单次负荷分离 + 顺延由用户定）、ADR-0017（md 是导出物）、ADR-0009（列表式主视图）
- **数据模型影响（实现阶段）**：新增 `plan_items`；`training_items.status` 新增 `practiced`（需重建表，风险按迁移三件套控制）
- **验证**：`openspec validate --all --store store` = **13 passed, 0 failed**；`openspec status` = 4/4 artifacts complete

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/training-plan-and-daily-view/` | 新增（proposal / design / specs / tasks） |
| `workspace/evidence/20260920-服务层代码审计.md` | 引用（M1 / M2 / M4 与本 change 的对应关系） |

## 与既有 change 的边界

- **不重叠修改**：勾选语义写进新 capability `training-plan`，避免与 `training-execution-feedback` 正在修改的
  `daily-execution`「用户能勾选完成任务并填写三省」Requirement 冲突。
- `training-path-generation`：本 change 只消费其 `training_items`，不改其 spec。
- `org-and-roles`（已后置）：企业版回答"谁要练"，本 change 回答"哪天练什么"。

## 关联 OpenSpec change id

`training-plan-and-daily-view`（状态：刚创建，未开始实现；尚未 apply）
