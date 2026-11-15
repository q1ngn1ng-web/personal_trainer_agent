# 2026-11-16 · 登记表现驱动调度 backlog（performance-driven-scheduling）

> 类型：chore ｜ 对应 change：`performance-driven-scheduling`（仅提案，未实施）

## 变更摘要

项目薄弱环节评审（同日，for-work 导学带教）确认：调度器不消费判分/记忆产出的学习信号
（"测得准、练得笨"），且一轮=全部题造成负载尖峰。登记修复方案：

- **阶梯前进/重置模型**（SM-2 离散化）：pass→间隔扩张、fail→归零+次日重练、
  practice-only 不动；step 从 practice_attempts 推导（单一事实源）；
- plan_items 预生成不变，完成事件重算后续 due_date（original_date 保留轨迹，重算幂等）；
- 首轮到期按每日预算错峰；达标后剩余轮次转可选巩固（不再罚站）；
- 测验 14 天节奏维持日历驱动；调度全程零 LLM；
- **修订 ADR-0021**（实施时写新 ADR）；存量训练按 schedule_mode 隔离不迁移。

与既有 backlog 关系：fail→次日重练吸收 `adaptive-practice-composition` 的"错题回炉"大半，
该 backlog 收窄为"巩固混排+提前练"；与 `grading-rubric-hardening` 正交（判分可信度 vs 调度消费）。
用户决策（2026-11-16）：**面试前不实施**。

## 验证

- `openspec validate performance-driven-scheduling --store store` 通过
- 零代码改动，无需测试
