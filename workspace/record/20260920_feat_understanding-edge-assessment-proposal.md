# 20260920 · feat · 理解边缘定位 proposal（未写代码）

## 变更摘要

把 ADR-0018 落成规格。本次只产出 proposal / design / specs / tasks，**未改动任何业务代码**。

这一环是个人版五个 change 中的最后一块拼图，位置在"选好资料来源"与"生成训练路径"之间。

## 产出

| 文件 | 内容 |
|---|---|
| `.../changes/understanding-edge-assessment/proposal.md` | Why / What Changes / 六条关键取舍 / 非目标 / Capabilities / Impact |
| `.../design.md` | 知识点清单、分层自适应探测、三态判定、前置铺垫、跳过与兜底、重测、结果如何被路径消费、风险表 |
| `.../specs/baseline-diagnosis/spec.md` | 4 条 Requirement 改写（分层探测 / 三态判定 / 前置铺垫 / 可重测），1 条 REMOVED |
| `.../tasks.md` | 8 组任务，每项写明验收方式 |

### 核心设计决定

1. **探测从"水平档位"改为"逐知识点三态"**：已掌握（跳过）/ 边缘（教学重点）/ 未达（先铺垫）
2. **分层自适应**：从难度 2 起，答对升档、答错降档，单知识点最多 3 题
3. **三态由规则层计算**，LLM 只出题与评分；判定依据（哪档通过、哪档失败）必须留痕
4. **未达知识点必须先铺垫**，且铺垫要回指来源切片
5. **允许跳过**：跳过后所有知识点按难度 2 起步，训练中用经验难度校准快速修正
6. **可重测**：阶段切换或用户主动请求，重测题目与首次不同，历史记录保留以便回看边缘移动
7. **移除"写入训练文件"**：md 已是导出物（ADR-0017），结果只写结构化数据

### 与关键词白名单解耦

探测的知识点清单可从来源切片与验收标准推导，**不依赖关键词白名单**，因此白名单的去留不影响本设计（按用户要求暂缓决策）。

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：修改 `baseline-diagnosis`；能力 id 保留以延续历史，但内容已升级为理解边缘定位
- **验证**：`openspec status` 显示 4/4 artifacts complete；`openspec validate --all` 12 passed, 0 failed
- **个人版 change 集合由此凑齐**：`goal-clarification-confirm`、`training-source-selection`、`understanding-edge-assessment`、`training-path-generation`、`training-execution-feedback`

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/understanding-edge-assessment/` | 新增（proposal / design / specs / tasks） |

## 关联 OpenSpec change id

`understanding-edge-assessment`（状态：进行中，尚未 archive）
