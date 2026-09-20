# training-path-generation · 设计文档

## Context

### 背景

训练路径生成是整条链路的枢纽：上游接已确认的目的与可用来源，下游接每日执行、评测与达标判定。

现有实现是固定十要素模板——不论什么目标都产出同构的 10 份文件。它能跑，但路径不随目标变化、也不随表现变化，等于没有"路径"这个对象。

### 当前状态

- 训练内容由 `src/services/trainer_service.py` 按模板生成，没有阶段与训练项的概念
- 没有难度、题型、预算这些字段
- `goal-clarification-confirm` 将提供已确认的 `goal_json`（含 `level` 与结构化 `acceptance`）
- `training-source-selection` 将提供 `sources` / `source_chunks` 与 FTS5 检索

### 约束

- 沿用 ADR-0001：LLM 只产出内容与顺序，日期与状态由规则层负责
- 沿用 ADR-0007：不引入向量检索
- 路径必须是结构化数据，能驱动评测、调度与达标判定
- 所有 Python 脚本用 uv 运行

### 利益相关方

- 用户本人（自用 + 面试演示）

## Goals / Non-Goals

**Goals:**

- 用户拿到一份**看得懂、能微调、能追溯**的路径，而不是一段生成的文本
- 长周期目标有明确承诺（骨架），近期执行能按实际表现调整（阶段细节）
- 路径总量与用户承诺的投入相匹配，不出现"根本练不完"的计划

**Non-Goals:**

- 不做每日排期（属调度器）
- 不做十要素文件的去留决策
- 不做多支线路径

## Decisions

### D1 路径的数据结构

```
training_paths
  id, training_id, version, status(draft|confirmed|superseded),
  mode(coverage|mastery),
  budget_minutes, planned_minutes,
  created_at, confirmed_at

path_stages
  id, path_id, ordinal, title, goal,
  item_count, type_distribution(memory|comprehension|practice 计数),
  estimated_minutes,
  status(locked|active|completed),
  prerequisite_stage_id     -- 线性前置，第一版只允许指向前一阶段

training_items
  id, stage_id, ordinal, title, item_type(memory|comprehension|practice),
  difficulty_tier(1-4), difficulty_basis(type, points, steps, hint),
  empirical(attempts, accuracy, avg_seconds),
  source_chunk_ids, acceptance, status(pending|in_progress|passed|failed)
```

**为什么不复用现有 10 份 md 文件作为路径**：md 无法被程序消费，无法承载状态、难度与回指。

### D2 两层生成策略（本设计的核心）

| 层 | 什么时候生成 | 内容 | 谁来定 |
|---|---|---|---|
| **骨架** | 用户确认目的并选好来源后，一次生成 | 阶段划分、顺序、每阶段目标、题量与题型分布、预估时长 | AI 生成草案 → 用户微调 → **确认后冻结** |
| **阶段细节** | 进入某阶段时 | 该阶段的具体训练项（含难度与来源回指） | AI 依阶段目标 + 前置阶段实际表现生成 |

**为什么不是一次生成全部**：长期细节必然失真——用户第 3 天暴露的薄弱点，不该等到第 30 天才响应；而且前期信息不足时生成细节等于浪费。

**为什么不是完全滚动**：用户看不到全貌就没有承诺感，也无法判断"这要练多久"。这与同类产品的观察一致：平台型产品路径硬但能看全貌，工具型产品灵活但没有状态。

### D3 预算校验：模型不能超支

预算由用户在澄清阶段确认的投入换算：

```
budget_minutes = horizon_weeks × weekly_frequency × daily_budget
```

校验规则（全部由规则层执行）：

| 情况 | 处理 |
|---|---|
| `planned_minutes ≤ budget_minutes` | 通过 |
| `planned_minutes > budget_minutes` | **拒绝该路径**，提示模型压缩并重试；连续失败则返回草案并标注超支比例，由用户决定调整投入还是接受压缩 |
| `planned_minutes < budget_minutes × 0.5` | 提示可能过松，但不阻塞 |

**覆盖模式下的额外校验**：必须覆盖来源中标记为必修的全部知识点，**允许总时长超预算时提示用户延长周期，不允许跳过知识点**。

### D4 题型与难度

题型三类，与评测能力对齐：

| 题型 | 例子 | 判分方式（由评测模块消费） |
|---|---|---|
| 记忆性 | 背规则、背例句 | strict：归一化文本 + diff + 关键句覆盖 |
| 理解性 | 辨析易混、解释原因 | fuzzy：语义相似度 + 关键句覆盖 + 必要时 LLM 判断 |
| 实践性 | 造句、改错、场景应用 | 场景题 + 样例对照（第一版人工确认） |

难度四档与依据要求见 `ADR-0010`。核心约束：**模型标档位必须同时给出依据**（题型 / 涉及知识点数 / 推理步数 / 是否给提示），缺依据视为不合格输出；运行中累计作答满 3 次后按准确率校准，原始 AI 档位保留。

### D5 两种模式

见 `ADR-0011`。设计上的落点：

- `mode=coverage`：`item_count` 由知识点覆盖决定并锁定；单次负荷可调；难度可降但不许跳过知识点
- `mode=mastery`：达标即可提前结束；总量可调

`mode` 由目的（`goal_json.content` 中是否包含"必须掌握全部内容"类表述）与用户显式选择共同决定，**由用户拍板，不由模型自动判定**。

### D6 超时与节奏调整

规则层依据数值触发，不由 LLM 判断：

```
连续 3 项实际耗时 > 预估耗时 → 下次单次题量下调（例如 -20%）
不降低标准、不减少总量
同时提示：实际节奏比预估慢约 X%，是否调整周期或投入
```

覆盖模式下时间预算的弹性由用户选择：延长截止日，或压缩后续休息日。

### D7 主视图与渲染职责

见 `ADR-0009`。职责划分写死：

| 内容 | 由谁产生 |
|---|---|
| 阶段结构、训练项清单 | 结构化数据（由 AI 生成后落库） |
| 进度、完成数、达标数 | 数据库统计 |
| 图形化（将来） | 由结构化数据渲染，**不允许模型直接输出 mermaid** |

### D8 确认与版本

- 骨架生成后状态为 `draft`，用户可任意微调
- 用户点「确认路径」→ `status=confirmed`，写入 `confirmed_at`，**这是用户的投入承诺**（对应 ADR-0006）
- 确认后若要重构骨架 → **新建版本**，旧版本 `status=superseded`，训练项记录归属版本
- 阶段细节的就地微调不算新版本

### D9 训练项必须回指来源

生成训练项时把候选切片一并传入（FTS5 检索得到），要求模型标注使用了哪些切片；
校验切片 ID 是否存在，不存在的丢弃并记日志。约束与 `training-source-selection` 一致。
**AI 生成的来源（`type=ai_generated`）训练项没有切片回指**，此时 `source_chunk_ids` 为空。

## Risks / Trade-offs

| 风险 | 影响 | 处理方式 |
|---|---|---|
| 骨架确认后用户仍频繁大改 | 破坏习惯与信任 | 骨架重构需显式确认并提示影响面；已完成项记录归属版本 |
| 预算校验过严导致反复重试 | 生成变慢、成本上升 | 设置重试上限；超限后返回草案 + 超支比例，交用户决定 |
| 难度四档粒度过粗 | 调整策略不灵敏 | 保留原始档位与 `basis`，用真实数据统计区分度；一致率 >95% 时考虑细分 |
| 阶段细节生成时上下文不足 | 题目质量下降 | 传入阶段目标 + 前置阶段表现摘要 + 相关来源切片 |
| 训练项与来源对不上 | 回指失效 | 校验切片 ID 存在性；对 `ai_generated` 来源允许空回指并显式标识 |
| 与 `goal-clarification-confirm`、`training-source-selection` 的依赖顺序 | 缺输入无法生成 | 本 change 依赖前两者先落地；规格中写明前置状态要求 |

## 关联决策记录

- `workspace/decisions/ADR-0001-llm负责语义-规则负责状态.md`
- `workspace/decisions/ADR-0006-投入参数归路径阶段由AI生成用户微调.md`（路径确认即承诺）
- `workspace/decisions/ADR-0009-路径主视图用嵌套列表不画流程图.md`
- `workspace/decisions/ADR-0010-难度由AI给初值并附依据再到数据校准.md`
- `workspace/decisions/ADR-0011-总量与单次负荷分离覆盖模式与达成模式.md`

## 验收方式

- 单测：预算换算与超支拒绝、阶段前置依赖、难度依据缺失被拒、版本比对、超时触发负荷下调
- 手动场景：确认目的 + 选好来源后生成骨架，界面能看到阶段、训练项数量、题型分布、预估时长与总预算对比
- 手动场景：把骨架的总时长改到超预算，系统应拒绝并给出提示
- 手动场景：确认路径后重构骨架，应产生新版本且旧版本可查
- 指标：路径总量与预算偏差分布、难度人工复核一致率、阶段完成比例——**待实测，当前标【待验证】**
