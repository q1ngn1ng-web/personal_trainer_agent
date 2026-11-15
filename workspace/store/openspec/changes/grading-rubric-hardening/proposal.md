# grading-rubric-hardening · 判分细则加固：证据引用判分 + 要点可编辑（backlog，面试后实施）

> 状态：**仅提案，未实施**（用户决策 2026-11-16：先登记，面试前不动主链）。
> 来源：2026-11-16 判分原理讨论。rubric（要点判分）的两个结构性弱点被确认：
> ①**要点质量是单点故障**——模型出的要点平庸/重叠/漏关键时，判分"精确地错"，且无人工兜底入口；
> ②**单条判定无证据可审计**——模型说某条 hit，无法核对它依据作答的哪句话，幻觉 hit 不可见。
> 两个修复都便宜、不动算分公式，与 `learner-memory-and-grading` 的判分一致性标注（8.1/8.2）互补：
> 标注回答"模型判定与人工的一致率"，本 change 回答"每条判定凭什么"。

## Why

当前判分链路（quiz_grade v1.2.0）：模型对每条要点输出四态判定（hit/partial/wrong/missing），
规则层按系数算分（覆盖率×正确性、必答否决、阈值 0.8）。判定本身**没有依据**：

1. **幻觉 hit 不可见**：模型可能把没说到的判成 hit（尤其 partial/hit 边界），规则层与用户都无从核对；
2. **深度解析缺定位**：解析知道"你缺 p1"，但不能在用户作答里高亮"哪句话对应哪条、缺在哪"；
3. **要点一次生成终身使用**：`plan_items.points` 出题时固化，用户发现要点出得差（太琐碎/重叠/漏关键）
   只能整题重练，没有"把 rubric 修对"的入口——单点故障无人兜底；
4. **历史判定会失义**：`point_results.detail` 只存 point_id，若未来允许编辑要点，历史 attempt 的判定
   记录将指向被改过的文本。

## What Changes

**A. 证据引用判分（audit-only，不参与算分）**

- `quiz_grade` prompt 升 **v1.3.0**：hit/partial/wrong 的每条 `point_verdicts` MUST 附 `evidence`——
  **引用用户作答原文的连续片段**（missing 无证据，天然为空）；
- schema 同步：point_verdicts 条目增加 `evidence` 字段；
- 规则层核验：对 evidence 做**归一化子串匹配**（去空白/标点后，evidence 应出现在作答原文中），
  结果记 `evidence_ok`（bool）；**核验失败默认只标记、不自动改判**——降级策略需先积累
  evidence_ok 数据再定（保守起步）；
- `practice_attempts.point_results.detail` 每条同时快照 `point_text` 与 `evidence`——
  历史判定记录自此彻底自包含，不随要点编辑失义；
- 明确边界：**证据 MUST NOT 参与得分计算**（算分仍是四态系数公式），它是审计层与产品层
  （深度解析高亮）的原料。

**B. 要点可编辑（human-in-the-loop 兜底单点故障）**

- 新端点 `PATCH /api/plan-items/{id}/points`：增/删/改要点文本、`weight`、`is_required`；
- **锁定规则**：该计划项首次判分（存在 graded attempt）后编辑接口返回 409——
  rubric 在第一份客观记录产生前可修，之后不可（保证判分标准对同一作答历史稳定）；
- 前端 TaskCard 展开后提供简版要点编辑（列表 + 权重/必答开关）；
- 编辑只影响后续判分；历史 attempt 的 point_results 因 A 的快照设计不受影响。

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
| --- | --- | --- |
| 证据核验失败只标记 | 核验失败自动降级为 missing | 模型引用常微改写，自动降级会制造新的误伤；先用 evidence_ok 积累误报率数据，再定降级策略 |
| 证据不参与算分 | 把 evidence_ok 纳入得分 | 算分公式的确定性是本项目判分的立身之本；审计与算分分层 |
| 首次判分即锁定 rubric | 永久可编辑 | 判分标准必须对作答历史稳定，否则连续 2 次通过的达标语义被破坏 |
| point_text 随判定快照 | 只存 point_id 引用 | 解耦历史记录与当前 rubric，深度解析回看旧作答不失义 |

## 非目标（Non-goals）

- 不做证据不匹配的自动降级（数据不足，见取舍表）
- 不做出题重掷/重新生成整套要点（另一个话题）
- 不改算分公式、系数与 0.8 阈值（校准走判分一致性标注那条线）
- 测验链路（question_points/assessment_items）的 evidence 落点实施时核对，本提案不预设

## Capabilities

### New Capabilities

- `grading-rubric`：判分细则的可审计与可维护——逐条判定附证据、要点在首判前可编辑、历史判定自包含

## Impact

- **代码（实施时）**：`src/llm/prompts.py` + `src/llm/schema.py`（quiz_grade v1.3.0）；
  `src/services/answer_service.py`（透传 evidence + 核验 + 快照）；`src/services/grading_service.py`
  （核验函数，纯函数）；`src/api/app.py`（PATCH 端点 + 锁定规则）；`web/src`（TaskCard 要点编辑）
- **数据**：无新表新列（point_results 是 JSON 字段，结构内扩展）
- **测试**：证据必附（schema）、核验标记不降级、得分与证据无关、编辑锁定 409、历史快照自包含
- **面试口径**：登记后可讲「我知道 rubric 的两个结构性弱点，修复方案在 openspec 里，排面试后实施」
