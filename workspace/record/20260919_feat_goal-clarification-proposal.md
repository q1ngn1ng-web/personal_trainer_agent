# 20260919 · feat · 目标澄清与确认 proposal（未写代码）

## 变更摘要

为「用户描述学习内容 → AI 澄清目标 → 用户确认目标」这一步建立规格与选型依据。
**本次只产出 proposal / design / specs / tasks 与一条 ADR，未改动任何业务代码。**

要解决的具体问题：

1. `src/services/topic_validation.py` 只做一次性"主题是否具体"的二值判定，**不能追问**；
2. 从输入主题到生成 10 份文件一气呵成，**没有用户确认环节**，导致后续评测无法归因到"哪个目标"；
3. 缺少结构化目标，第 5 步"生成训练路径"没有可信输入，只能退化为固定十要素模板。

### 产出

| 文件 | 内容 |
|---|---|
| `workspace/store/openspec/changes/goal-clarification-confirm/proposal.md` | Why / What Changes / 关键取舍表 / **非目标** / Capabilities / Impact |
| `.../design.md` | 目标 5 字段、状态机、LLM 输出契约、快照存储、风险表、验收方式 |
| `.../specs/goal-clarification/spec.md` | 新增能力：4 条 Requirement + 12 个 WHEN/THEN 场景 |
| `.../specs/trainer-generation/spec.md` | 修改现有能力：创建入口增加"必须先确认目标"约束 |
| `.../tasks.md` | 6 组任务（数据层 / 状态机 / LLM 用途 / 澄清服务 / UI / 收尾），每项写明验收方式 |
| `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md` | 选型依据：3 个备选方案的代价与放弃理由，含重评估触发条件 |

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `goal-clarification` capability；修改 `trainer-generation` 的一条 Requirement
- **文档**：`workspace/decisions/` 索引新增 ADR-0004
- **验证**：`openspec status --change goal-clarification-confirm --store store` 报 4/4 artifacts complete；
  `openspec validate --all --store store` 报 7 passed, 0 failed

## 待办

按 `tasks.md` 实施；实施完成后需把 `goal-clarification` spec 的 `Purpose` 从 TBD 补成一句话，
并把澄清完成率、平均追问轮次写进 `workspace/evidence/`。

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/goal-clarification-confirm/` | 新增（proposal / design / specs / tasks） |
| `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md` | 新增 |
| `workspace/decisions/README.md` | 索引新增一行 |

## 关联 OpenSpec change id

`goal-clarification-confirm`（状态：进行中，尚未 archive）
