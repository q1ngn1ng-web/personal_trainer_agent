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

## 修订记录

### 2026-09-19 v2：字段来源拆成两路

**触发**：用户反馈——投入参数（练多久、每周几次）应该让用户在前端直接选，而不是靠 AI 追问；
追问轮次要区分软性要求和硬性要求，不要问太多。

**改了什么**：

| 项 | v1 | v2 |
|---|---|---|
| 周期 / 每周次数 / 每次时长 | 作为必填字段，缺失则追问 | **前端结构化控件**，带默认值，可跳过；不再追问 |
| 追问范围 | 五个字段全部可能追问 | 只追问 `level` 与 `acceptance` 两个语义字段 |
| 追问上限 | 单一硬上限 5 轮 | **软限 2 轮**（给建议值 + 提示可采用）+ **硬限 3 轮**（强制收口） |
| 参数来源 | 未记录 | 新增 `field_sources`，取值 `ui_select` / `user_reply` / `default` / `inferred` |
| 优先级 | 未明确 | 明确铁律：**前端显式选择 > 追问得到 > 默认值 > AI 推断**，AI 不得覆盖用户显式值 |

**新增决策记录**：`ADR-0005-投入参数走前端选择追问只用于语义澄清.md`（修订 ADR-0004 的字段
来源分配，其"多轮追问 + 显式确认状态"的核心结论不变；ADR-0004 顶部已加修订标注）。

**同类产品参考**：ADR-0005 内附一张产品做法对比表（Duolingo / Anki / 百词斩 / 松鼠AI 等），
标注为【待验证】——要作为对外证据前需亲手试用 2-3 款并留存截图到 `workspace/evidence/`。

**当前状态**：`openspec status` 显示 4/4 artifacts complete，`openspec validate --all` 通过。

### 2026-09-19 v3：把投入参数移出澄清阶段

**触发**：用户指出——澄清阶段讨论的是**目标**，而周期 / 频次 / 每次时长属于**训练路径**；
路径阶段应该是 AI 生成一系列参数，显示在前端，由用户微调。v2 把参数控件放进澄清页，
是把"手段"混进了"目的"。

**改了什么**：

| 项 | v2 | v3 |
|---|---|---|
| 澄清阶段产出 | `content` / `level` / `acceptance` + 三个前端参数控件 | **只有** `content` / `level` / `acceptance` |
| `horizon` / `weekly_frequency` / `daily_budget` | 前端控件收集 | **移出本 change**，归入下一次 change（训练路径生成） |
| 路径参数的产生方式 | 未定义 | 明确：AI 生成草案 → 前端逐项展示 → 用户微调 → 确认后冻结 |
| 参数边界 | 未定义 | 规则层校验（单次时长上限、每周次数上限、周期与截止日期关系），非法直接拒绝 |
| 用户承诺的位置 | 澄清阶段选参数 | **确认路径方案**时产生承诺 |
| 状态机终点 | `confirmed` | `confirmed`（下一次 change 接 `path_pending_confirm → active`） |

**新增决策记录**：`ADR-0006-投入参数归路径阶段由AI生成用户微调.md`；
ADR-0005 状态改为**已被 ADR-0006 取代**（顶部标注，正文不动）。

**边界澄清**：目的是"学什么 / 到什么程度 / 怎么算学会"，手段是"多久 / 几次 / 每次多久 / 分几阶段"。
先确认目的，再让 AI 给手段草案，用户做审阅者而不是填空者。

**当前状态**：`openspec status` 显示 4/4 artifacts complete，`openspec validate --all` 通过。
