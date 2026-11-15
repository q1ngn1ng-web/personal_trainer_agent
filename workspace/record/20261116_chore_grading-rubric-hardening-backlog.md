# 2026-11-16 · 登记判分细则加固 backlog（grading-rubric-hardening）

> 类型：chore ｜ 对应 change：`grading-rubric-hardening`（仅提案，未实施）

## 变更摘要

判分原理讨论（同日，for-work 导学带教）确认 rubric 判分的两个结构性弱点并登记修复方案：

1. **证据引用判分**：quiz_grade 将升 v1.3.0——hit/partial/wrong 每条判定必须引用作答原文片段；
   规则层归一化核验记 evidence_ok（失败只标记不降级）；point_results.detail 快照 point_text+evidence，
   历史判定自包含；证据不参与算分（审计层与算分层分离）。
2. **要点可编辑**：新端点 PATCH /api/plan-items/{id}/points，首次判分前可修 rubric（human-in-the-loop
   兜底要点质量单点故障），判分后 409 锁定（保证达标语义对作答历史稳定）。

与 `learner-memory-and-grading` 8.1/8.2 判分一致性标注互补：标注回答"判定准不准"，
本 change 回答"判定凭什么"。用户决策（2026-11-16）：**面试前不实施**。

## 验证

- `openspec validate grading-rubric-hardening --store store` 通过
- 零代码改动，无需测试
