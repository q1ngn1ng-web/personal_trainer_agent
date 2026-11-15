# grading-rubric-hardening · 任务清单（backlog，未排期）

- [x] 0.1 设计决策：证据归一化口径（去空白/标点子串匹配；微改写容错）；核验失败只标记（确认不降级）——已定稿于 design.md D1
- [x] 1.1 quiz_grade prompt 升 v1.4.0（v1.3.0 已被记忆块迭代占用，故顺延）+ schema 加 evidence 字段
- [x] 1.2 grading_service 新增证据核验纯函数（归一化子串 → evidence_ok）
- [x] 1.3 answer_service：透传 evidence、核验标记、point_results.detail 快照 point_text+evidence
- [x] 1.4 PATCH /api/plan-items/{id}/points（增删改 weight/is_required；存在 graded attempt → 409）
- [x] 1.5 TaskCard 要点编辑（简版列表 + 权重/必答开关）
- [ ] 1.6 深度解析高亮证据位置（可选，依赖 1.3 的快照）
- [x] 1.7 测试：schema 证据必附、核验失败标记不改判、得分与证据无关、锁定 409、历史快照自包含

> 实施注记（2026-11-16）：0.1-1.5、1.7 已完成并全量回归 343 passed；1.6（深度解析高亮证据位置）为可选项未做；
> 测验链路 evidence 落点维持非目标（测验 attempt 本不带 point_results，属既有口径，见 record 遗留）。
> 顺带修复：日常判分 point_results 此前被改成 list 格式导致错因不落库的断链（本次统一为 dict + 快照格式）。
