# layered-learner-memory · 任务清单

- [x] 1.1 tables.sql 新增 learner_knowledge（UNIQUE(training_id,item_key)，misconceptions JSON）
- [x] 1.2 core/learner.py 纯函数：update_mastery（K=0.35，起点 0.5，clamp）、decay_mastery（30 天半衰期）、misconceptions_from_detail（wrong→concept_confusion；必答 missing→key_omission）
- [x] 1.3 learner_service：apply_attempt（随作答事务 upsert，kp 从 question_bank/training_items 解析）、get_learner_model（读时衰减 + weak）、rebuild（重放收敛）
- [x] 1.4 attempt_service.record_attempt 挂钩（派生层失败只告警不阻塞）
- [x] 1.5 端点：GET learner-model（decayed 升序 + 中文标签）+ POST rebuild；训练可见性守卫
- [x] 1.6 测试 test_learner_model.py（含 增量=重放 收敛守卫）
- [x] 1.7 全量回归 + 证据/记录 + 归档
