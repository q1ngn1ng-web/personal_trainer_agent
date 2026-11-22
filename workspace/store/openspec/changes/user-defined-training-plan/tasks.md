# user-defined-training-plan · 任务清单（待实施会话执行）

## 0. 待用户确认的设计决策（实施前必须逐条拍板）

- [ ] 0.1 每项最少接触次数：默认 2（学习+复习）？「能讲清」等级是否强制 3？
- [ ] 0.2 次数×容量不足时的行为：仅警告，还是禁止确认（强制加次数/时长）？
- [ ] 0.3 终测不过 →「重新来」的语义：同 horizon 重排（推荐）/ 顺延 horizon / 二选一让用户选？
- [ ] 0.4 14 天周期小测是否保留（推荐：horizon>4 周时保留为中期检查，否则只留终测）？
- [ ] 0.5 会话日期：均匀摊开（推荐默认）还是允许用户自选具体日期？

## 1. 数据与澄清层

- [ ] 1.1 goal schema 增 horizon_days(1-56)/session_count(2-6)，快照落 goal_json（field_sources=user_input）；
      校验进 core/goal.py（is_complete/missing_fields 纳管）
- [ ] 1.2 澄清提示词第 6/7 条修订：禁的是 LLM 追问，参数由界面控件收集；口径 8 加字段间自洽检查
- [ ] 1.3 _clarify_payload 带节奏字段 + 推荐值计算（知识点数×等级→建议次数与警告）
- [ ] 1.4 WizardView 澄清步节奏卡片（总时长/次数控件 + 推荐与警告 + 可编辑）——与 draft 字段编辑器同批

## 2. 排期与覆盖分配

- [ ] 2.1 分配纯函数：N 会话 × 训练项 → 每会话清单（新知按阶段序靠前、每项≥2 次接触、
      单次容量≤daily_minutes_target、顺延进位）——独立模块可单测
- [ ] 2.2 plan_service.generate_plan v2：session_index 替代 round_index；预生成+UNIQUE 幂等保留
- [ ] 2.3 quiz_service：trigger='final' 终测（覆盖全部必修项）；完成门=终测通过→completed；
      不过→按剩余 horizon 重排（0.3 决策），达标项记录保留
- [ ] 2.4存量训练 schedule_mode='legacy_v21' 隔离，不迁移

## 3. 前端与收尾

- [ ] 3.1 训练详情页展示会话制计划（第几次/覆盖哪些/顺延标记）
- [ ] 3.2 新 ADR（取代 0021）+ 0021 标注被取代；specs/training-plan 对应 Requirement 修订
- [ ] 3.3 测试：分配纯函数全路径、终测门、重新来、参数校验、存量隔离；全量回归
- [ ] 3.4 record/evidence + 归档
