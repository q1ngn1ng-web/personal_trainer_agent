# 2026-11-22 · 登记用户自定义训练计划提案（user-defined-training-plan）

> 类型：chore ｜ 对应 change：`user-defined-training-plan`（**仅提案，未实施**）
> 关联：实质修订 ADR-0021；收编 performance-driven-scheduling 与 adaptive-practice-composition

## 变更摘要

用户产品决策（2026-11-22）：澄清阶段就向用户展示并允许自定义**总时长 × 训练次数**
（例：两周三次），AI 协调每次训练覆盖的知识点；训练完成由**总测验**判定，不通过重新来。
登记为提案（自包含交接文档），实施前有 5 项设计决策待用户拍板（tasks 0.1-0.5：
最少接触次数、容量不足行为、重排语义、中期小测去留、会话日期策略）。

要点：
- 投入参数以 UI 控件收集（不走 LLM 对话），写入 goal 快照（user_input 来源）；
  提示词第 6/7 条修订为"禁的是 LLM 追问，不是收集"；
- 覆盖分配为纯函数（新知靠前、每项≥2 次接触、容量约束、顺延进位），LLM 只做建议；
- 终测（trigger='final'，全必修项）单独把关完成；per-item 达标 streak 保留作分配输入；
- 实施顺序：本 change 定骨架 → performance-driven-scheduling 阶梯移植为会话内自适应。

## 验证

- `openspec validate user-defined-training-plan --store store` 通过
- 零代码改动，无需测试
