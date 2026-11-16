# layered-learner-memory · 分层学习者记忆（当日提案→当日实施）

> 状态：**实施中**（用户决策 2026-11-16：登记并直接写代码，面试前可做）。
> 来源：2026-11-16 记忆架构讨论。现有系统是「DB 即记忆」——情景记忆（practice_attempts）
> 与程序记忆（PROMPT_REGISTRY）已做对；缺**语义记忆**（用户的知识模型，只有统计快照）
> 与记忆的**查询式消费**（只能注入 prompt）。本 change 补这两块，纯增量、不动现有消费方。

## Why

1. **语义记忆缺失**：`knowledge_profile` 只能说"准确率 0.55"，回答不了"用户对 RDB 的心智模型
   是什么"。判分/深度解析/调度需要的是提炼过的掌握度与活跃误解，不是原始统计。
2. **无时间衰减**：`AVG(score)` 里三个月前的 fail 与昨天的 fail 同权重；掌握度应随时间向
   "遗忘"漂移，复习信号由"快忘"触发（与 performance-driven-scheduling 同一枚硬币）。
3. **记忆消费只有 prompt 注入一条路**：记忆应可查询（未来的对话 agent 拿它当只读工具），
   而不是硬编码在哪条链就只有哪条链用得上。

## What Changes

**A. 学习者模型实体化（新表 `learner_knowledge`）**

- per `(training_id, item_key)` 一行：`mastery`（掌握度估计 0-1）、`misconceptions`
  （活跃误解 JSON 清单：point_id/text/reason，从最近一次判分 detail 提炼——wrong→概念混淆、
  必答 missing→关键遗漏）、attempts/passes 计数、last_seen_at；
- **更新规则（纯规则，零 LLM）**：Elo 式 `mastery += K×(outcome−mastery)`，K=0.35，
  outcome=score（无分数则 pass=1/fail=0），起点 0.5；
- **触发点**：`record_attempt`——全部作答（日常判分 + 测验回写）的唯一入口，随作答事务增量更新；
  派生层失败只告警不阻塞事实记录；
- **时间衰减（读时计算，不落盘不跑批）**：`decayed = mastery × 0.5^(距 last_seen 天数/30)`——
  30 天半衰期，与五轮排期最长间隔呼应；查询时返回 mastery 与 decayed_mastery 及 weak 标记
  （decayed < 0.8，沿用 WEAK_SCORE_THRESHOLD）；
- **rebuild 可重放**：learner 模型从 practice_attempts 重放必与增量更新收敛（单一事实源），
  提供重建端点做存量回填。

**B. 只读记忆 API（未来对话 agent 的工具面）**

- `GET /api/trainings/{id}/learner-model`：按 decayed 升序返回全量知识点画像
  （mastery/decayed/weak/misconceptions（含中文标签）/last_seen/次数）；
- `POST /api/trainings/{id}/learner-model/rebuild`：从 attempts 重放重建（部署后回填存量）。
- 纯增量：**不改动** grade_memory_block / render_context / 深度解析任何现有消费链。

### 关键取舍

| 选择 | 备选 | 放弃理由 |
| --- | --- | --- |
| 读时算衰减 | 定时任务落盘 decayed | 零调度进程、零一致性窗口；本量级查询成本可忽略 |
| (training_id, item_key) 粒度 | user 级跨训练画像 | 个人版训练即归属；跨训练画像是后续项（见非目标） |
| 从最近一次判分 detail 整体替换误解清单 | 逐条增删状态机 | "活跃误解"语义=最近一次的表现，可重放、无状态漂移 |
| 增量 + rebuild 双轨 | 只读时聚合 | 消费方（未来 agent 工具）需要 O(1) 读取与可分页，且 mastery 递推式非简单聚合 |
| 误解只存规则码 | LLM 提炼自然语言 | 先规则可测零幻觉；LLM 提炼属后续增强 |

## 非目标（Non-goals）

- 不改现有消费链（grade_memory_block/render_context/深度解析的接入属后续 change）
- 不做 user 级跨训练画像、对话工作记忆（session/message）、embedding 语义检索
- 不做 L1 对话 agent 本体；本 change 只交付其记忆工具面
- 不动 performance-driven-scheduling（它消费 decayed 是实施该 change 时的接线项）

## Capabilities

### New Capabilities

- `learner-memory`：结构化学习者模型——掌握度递推 + 时间衰减 + 活跃误解 + 可重放 + 只读查询 API

## Impact

- **代码**：`src/db/tables.sql`（新表，init_db 的 IF NOT EXISTS 自动覆盖存量库）；`src/core/learner.py`
  （纯函数：mastery 递推/衰减/误解提炼）；`src/services/learner_service.py`（apply_attempt/get/rebuild）；
  `src/services/attempt_service.py`（record_attempt 挂钩）；`src/api/app.py`（两个端点）
- **测试**：纯函数数学、增量=重放收敛守卫、record_attempt 集成、衰减与 weak、端点契约与可见性
- **证据**：测试输出 + rebuild 收敛证明
