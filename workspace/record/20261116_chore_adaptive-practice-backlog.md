# 2026-11-16 · 登记自适应练习编排 backlog（adaptive-practice-composition）

> 类型：chore ｜ 对应 change：`adaptive-practice-composition`（仅提案，未实施）

## 变更摘要

用户在第 1 课复述中描述了期望的练习编排形态（错题回炉、同题巩固、提前训练、渐进式覆盖）。
审计判定这些能力当前不存在，与其在面试中误讲，不如登记为真实 backlog：

- 建 openspec change `adaptive-practice-composition`（proposal + tasks，未归档未实施）；
- proposal 中记录了与 ADR-0021（固定五轮每轮全覆盖）的设计张力与处置建议
  （渐进式覆盖默认不做；错题回炉走附加行不动主轮次；提前练不改 due_date）；
- 用户决策（2026-11-16）：**面试前不实施**，不影响主链与判分达标规则。

## 验证

- `openspec validate adaptive-practice-composition --store store` 通过
- 零代码改动，无需测试
