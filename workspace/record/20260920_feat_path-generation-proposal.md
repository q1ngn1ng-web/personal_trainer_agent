# 20260920 · feat · 训练路径生成 proposal（未写代码）

## 变更摘要

为「AI 生成训练路径」建立规格与选型依据。本次只产出 proposal / design / specs / tasks，**未改动任何业务代码**。

要解决的具体问题：现有实现是固定十要素模板，不论什么目标都生成同构的 10 份文件——路径不随目标变化、也不随表现变化，等于没有"路径"这个对象。

## 产出

| 文件 | 内容 |
|---|---|
| `workspace/store/openspec/changes/training-path-generation/proposal.md` | Why / What Changes / 六条关键取舍 / 非目标 / 三条**留给后续的问题** / Capabilities / Impact |
| `.../design.md` | 数据结构、两层生成策略、预算校验、题型与难度、两种模式、超时调整、渲染职责、确认与版本、来源回指、风险表 |
| `.../specs/path-generation/spec.md` | 新增能力：9 条 Requirement |
| `.../tasks.md` | 6 组任务，每项写明验收方式 |

### 核心设计决定

1. **两层生成**：骨架（阶段划分、顺序、题量与题型分布、预估时长）一次生成并由用户确认冻结；阶段内训练项在进入该阶段时按实际表现生成。
2. **预算是硬约束**：`周期 × 每周频次 × 每次时长` 换算成总分钟预算，超支路径**直接拒绝**，连续重试失败才交用户决定。
3. **难度必须附依据**：模型标档位需同时给出题型、知识点数、推理步数、是否给提示，缺依据视为不合格输出（ADR-0010）。
4. **两种模式**：覆盖模式锁定总量、不许跳过知识点；达成模式达标即结束（ADR-0011）。
5. **不让模型排日期**：路径只表达顺序与阶段，日期由调度器算（ADR-0001）。
6. **不改 `trainer-generation`**：避免与 `goal-clarification-confirm` 在同一 spec 上产生 delta 冲突。

### 显式记录的三条待决问题

1. 十要素模板生成的 10 份 md 是保留、迁移还是废弃
2. 关键词白名单在新流程中的角色
3. 基线诊断在新流程中的位置（生成路径前做，还是并入阶段 1）

这三项会影响路径生成的输入，但不阻塞本次设计，已在 proposal 中单列一节。

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `path-generation` capability；三个进行中的 change 互不冲突
- **决策**：引用 ADR-0001 / 0006 / 0009 / 0010 / 0011
- **验证**：`openspec status` 显示 4/4 artifacts complete；`openspec validate --all` 9 passed, 0 failed

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/training-path-generation/` | 新增（proposal / design / specs / tasks） |

## 关联 OpenSpec change id

`training-path-generation`（状态：进行中，尚未 archive）
