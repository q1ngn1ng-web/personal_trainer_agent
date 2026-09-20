# 20260920 · feat · 组织、角色与培训任务 proposal（未写代码）

## 变更摘要

为「企业化」建立规格与选型依据。本次只产出 proposal / design / specs / tasks 与一条 ADR，**未改动任何业务代码**。

要解决的具体问题：此前所有设计都是单人视角，资料、路径、训练记录都属于同一个人；而产品定位面向企业，管理层要"发下去并知道谁达标了"，员工要"知道练什么、练到哪了"。没有组织与角色，就没有企业公共区这种分发关系，**培训周期与达标率也无从量化**。

## 产出

| 文件 | 内容 |
|---|---|
| `workspace/store/openspec/changes/org-and-roles/proposal.md` | Why / What Changes / 五条关键取舍 / 非目标 / 三条待决问题 / Capabilities / Impact |
| `.../design.md` | 数据模型、认证方案、权限校验点、资料可见范围、培训任务、内容层与进度层落地、三个指标口径、员工端界面收敛、风险表 |
| `.../specs/org-and-roles/spec.md` | 新增能力：5 条 Requirement |
| `.../specs/training-assignment/spec.md` | 新增能力：5 条 Requirement |
| `.../tasks.md` | 8 组任务，每项写明验收方式 |
| `workspace/decisions/ADR-0014-认证复用成熟组件第一版只做两种角色.md` | 认证与权限粒度选型 |

### 核心设计决定

1. **两种角色**（admin / employee），第一版不做细粒度权限——没有真实需求支撑的权限模型是过度设计
2. **权限校验统一在服务层**，UI 隐藏按钮不算权限控制
3. **培训任务四要素**（资料范围 / 验收标准 / 目标人群 / 截止日期）缺一不可——没有它们就算不出达标率与周期
4. **内容层按组织一份、进度层按人一份**（落地 ADR-0013），经验难度按标签聚合且样本量低于 5 人时回退结构难度
5. **三个企业价值指标口径写死**：首次达标周期（接收到达标的自然天数中位数）、必修覆盖率、首次通过率
6. **刻意不做**员工互看与排行榜——训练数据属于个人，用排名激励会诱导刷量而不是掌握

### 显式记录的三条待决问题

1. 澄清流程需要扩展"任务派发"入口（现有 `goal-clarification` 假定用户从零描述目标），本 change 不动其规格以避免冲突
2. 指标按岗位统计需要岗位字段，第一版用标签分组
3. 十要素模板生成的 10 份 md 留废问题仍未决

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `org-and-roles` 与 `training-assignment` 两个 capability；四个进行中的 change 互不冲突
- **依赖**：后续实现需引入认证组件（ADR-0014）
- **验证**：`openspec status` 显示 4/4 artifacts complete；`openspec validate --all` 10 passed, 0 failed
- **决策记录累计**：15 条（含模板）

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/org-and-roles/` | 新增（proposal / design / specs / tasks） |
| `workspace/decisions/ADR-0014-认证复用成熟组件第一版只做两种角色.md` | 新增 |
| `workspace/decisions/README.md` | 索引新增一行 |

## 关联 OpenSpec change id

`org-and-roles`（状态：进行中，尚未 archive）
