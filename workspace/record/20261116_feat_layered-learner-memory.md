# 2026-11-16 · 分层学习者记忆实施（layered-learner-memory）

> 类型：feat ｜ 对应 change：`layered-learner-memory`（当日提案→当日实施归档）

## 变更摘要

记忆架构讨论（同日）确认：情景记忆与程序记忆已做对，缺**语义记忆**（学习者知识模型）与
**查询式消费**。本 change 纯增量补齐，不动任何现有消费链（grade_memory_block/解析/调度）：

1. **学习者模型实体化**：新表 `learner_knowledge`（UNIQUE(training_id,item_key)）——
   mastery（Elo 式递推 K=0.35 起点 0.5）、活跃误解 JSON（最近一次判分 detail 整体替换：
   wrong→concept_confusion、必答 missing→key_omission，带要点文本）、attempts/passes、last_seen；
2. **更新挂 record_attempt**（全部作答唯一入口，随作答事务；派生层失败只告警不阻塞事实）；
3. **读时衰减**：`decayed = mastery × 0.5^(days/30)`（30 天半衰期，与五轮最长间隔呼应），
   不落盘无定时任务；查询按 decayed 升序 + weak 标记（<0.8）+ 误解中文标签；
4. **只读记忆 API**：GET /api/trainings/{id}/learner-model（未来对话 agent 的记忆工具面）+
   POST .../rebuild（全量重放回填，幂等，有收敛守卫测试）；
5. 纯函数落 `src/core/learner.py`（零 LLM 零 I/O），服务层 `learner_service.py`。

## 影响范围

- `src/db/tables.sql`（新表；init_db 的 IF NOT EXISTS 对存量库自动生效）
- `src/core/learner.py`（新）、`src/services/learner_service.py`（新）
- `src/services/attempt_service.py`（record_attempt 挂钩）、`src/api/app.py`（两端点）
- 测试：`tests/test_learner_model.py`（8 用例）

## 验证

- 新用例 8 passed（含增量==重放收敛守卫）；全量 **351 passed, 1 skipped, 30 subtests**
- 证据：`workspace/evidence/20261116-layered-learner-memory.md`

## 遗留（后续 change）

- 消费方接线：grade_memory_block / 深度解析 / performance-driven-scheduling 消费 decayed mastery
- user 级跨训练画像、对话工作记忆（session/message）、embedding 语义检索、L1 只读对话 agent
