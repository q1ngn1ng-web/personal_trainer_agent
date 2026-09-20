# 20260920 · feat · 训练执行与反馈 proposal（未写代码）

## 变更摘要

补上整条链路的最后一段：训练进行中的反馈与检验。本次只产出 proposal / design / specs / tasks 与两条 ADR，**未改动任何业务代码**。

要解决的两个缺口：

1. **反馈是单向的**：用户只能勾选完成、自评对错、写三省，系统看不懂"太简单了""太宽泛了"这类感受，无法据此调整难度与题量
2. **没有不依赖自评的检验**：学习中最常见的失败是误以为自己懂了，尤其在用 AI 学习时

## 产出

| 文件 | 内容 |
|---|---|
| `.../changes/training-execution-feedback/proposal.md` | Why / What Changes / 七条关键取舍 / 非目标 / Capabilities / Impact |
| `.../design.md` | 四失映射、采集方式、冲突裁决、防抖动、测验三个理由对应三条设计、测验与日常训练对照、触发条件、回退机制、三级达标判据、风险表 |
| `.../specs/learning-signal/spec.md` | 新增能力：5 条 Requirement |
| `.../specs/periodic-assessment/spec.md` | 新增能力：5 条 Requirement |
| `.../specs/daily-execution/spec.md` | **修改**两条 Requirement（任务卡加信号采集、微调改双通道 + 三省变可选） |
| `.../specs/weekly-review/spec.md` | **修改**一条 Requirement（指标加信号分布、测验通过率、调整次数） |
| `.../tasks.md` | 7 组任务，每项写明验收方式 |
| `workspace/decisions/ADR-0015-主观信号与客观表现双通道冲突时以客观为主.md` | 冲突裁决与防抖动 |
| `workspace/decisions/ADR-0016-测验题不得取自刚练过的原题.md` | 测验独立性 |

### 核心设计决定

1. **四失落成四类信号与四类动作**：多→收敛、寡→拓展、易→深挖、止→鼓励
2. **一键标签，不填表**：训练中要求填评分表会直接杀死使用意愿
3. **冲突时以客观为主并显式提示**：自评"太简单"但正确率低于 60% 时不升难度，而是把差异告诉用户
4. **结构性调整限频留痕**：同类信号当日累计 2 次才触发，每日最多 1 次，全部写入调整日志（含被拦截的情形）
5. **测验三个理由对应三条设计**：防自我催眠→换成变式或新题；保持校准→结果写入经验难度；应用巩固→测验本身进入排期
6. **测验题不得取自刚练过的原题**，触发时机可由用户决定但内容不可挑选
7. **未通过回退重练而非补考**，重考必须换新题
8. **三级达标判据**：训练项需连续 2 次达标；阶段达标分两种模式；任务达标需覆盖 100% 且最终测验通过

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增两个 capability，修改 `daily-execution` 与 `weekly-review`；这两个 spec 此前未被其他进行中的 change 触碰，无冲突
- **决策记录累计**：17 条（含模板）
- **验证**：`openspec status` 显示 4/4 artifacts complete；`openspec validate --all` 11 passed, 0 failed

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/training-execution-feedback/` | 新增（proposal / design / specs / tasks） |
| `workspace/decisions/ADR-0015-主观信号与客观表现双通道冲突时以客观为主.md` | 新增 |
| `workspace/decisions/ADR-0016-测验题不得取自刚练过的原题.md` | 新增 |
| `workspace/decisions/README.md` | 索引新增两行 |

## 关联 OpenSpec change id

`training-execution-feedback`（状态：进行中，尚未 archive）
