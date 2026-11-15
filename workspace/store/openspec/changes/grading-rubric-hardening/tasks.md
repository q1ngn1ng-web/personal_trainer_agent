# grading-rubric-hardening · 任务清单（backlog，未排期）

- [ ] 0.1 设计决策：证据归一化口径（去空白/标点子串匹配；微改写容错）；核验失败只标记（确认不降级）
- [ ] 1.1 quiz_grade prompt v1.2.0 → v1.3.0（evidence 要求与口径）+ schema 加 evidence 字段
- [ ] 1.2 grading_service 新增证据核验纯函数（归一化子串 → evidence_ok）
- [ ] 1.3 answer_service：透传 evidence、核验标记、point_results.detail 快照 point_text+evidence
- [ ] 1.4 PATCH /api/plan-items/{id}/points（增删改 weight/is_required；存在 graded attempt → 409）
- [ ] 1.5 TaskCard 要点编辑（简版列表 + 权重/必答开关）
- [ ] 1.6 深度解析高亮证据位置（可选，依赖 1.3 的快照）
- [ ] 1.7 测试：schema 证据必附、核验失败标记不改判、得分与证据无关、锁定 409、历史快照自包含
