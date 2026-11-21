# 2026-11-22 · 记录 FSRS 演进路径（performance-driven-scheduling/design D6）

> 类型：chore ｜ 无代码改动

## 变更摘要

用户讨论中提出用 FSRS 公式做记忆遗忘/调度。确认 FSRS（Anki 内置的 DSR 三分量模型）
与本系统架构的精确映射（R↔decayed_mastery、S↔阶梯间隔、D↔difficulty_tier），
并将三步演进路径写入 performance-driven-scheduling/design.md D6：
阶梯（固定参数退化版）→ 随本 change 实施成为离散 FSRS → 数据攒够后开源优化器拟合每用户参数。
概念分工记录：FSRS 管记忆保持（R），mastery 递推管能力估计，互补不替代。

## 验证

- `openspec validate performance-driven-scheduling --store store` 通过
- 零代码改动
