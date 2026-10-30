# item-history-deep-explanation · 题目级作答历史注入深度解析

## Why

用户的核心诉求：**同一道题第一次答错、第二次又答错，第三次点「深度解析」时，
系统要能看到前两次分别怎么错的，并给出针对性的改进**。

当前实现离这个目标差四根线：

1. **作答原文留不住**：`practice_attempts` 没有 `answer_text` 列，作答原文只存在
   `plan_items.answer_text`，**会被下一次作答覆盖**——"第一次怎么错的原文"在库里根本不存在；
2. **错因没落库**：`memory_service.derive_mistake_reasons`（纯规则，判分四态 → 关键遗漏/记忆缺失/概念混淆/表达不完整）
   在生产链路零调用点，错因只活在测试里；
3. **解析没有消费历史**：`explanation_service` 只讲知识点，不知道用户错过几次、错在哪；
4. **没有入口**：深度解析没有 API 端点、没有前端按钮，用户点不到。

这四根线接上后，「学习者记忆」从一句口号变成可演示的能力：
每道题记住每次怎么错的，深度解析基于这份历史做针对性纠正。

## What Changes

- **`practice_attempts` 增加 `answer_text` 列**（tables.sql + migrate 老库补列）；
  `record_attempt` 新增同名参数，日常判分与测验回写两个调用点传入作答原文——**尝试级留档**
- **错因随作答自动落库**：`record_attempt` 内部按 `point_results` 调
  `derive_mistake_reasons` 推导并写入 `mistake_reasons`（纯规则，零 LLM 成本），所有调用方零改动
- **`explanation` prompt 升 v1.1.0**：新增 `attempt_history` 变量；
  有历史时要求逐次对比、指出重复错误与共性错因、给出可执行的改进动作；无历史时保持原三段结构
- **`explanation_service` 新增 `generate_item_explanation(training_id, plan_id)`**：
  以计划项为锚（题目/要点/参考答案），取该题最近 5 次作答历史（原文+结果+分数+中文错因标签），
  切片优先回指 `training_items.source_chunk_ids`（测验链路退回 question_bank），
  落库 `explanations`（prompt 字段取真实观测值）
- **新端点 `POST /api/plan-items/{plan_id}/explanation`**：可见性校验（403/404）→ 服务调用 →
  失败映射 400/502
- **前端**：`api.ts` 新增 `explanation(planId)`；`TaskCard` 增加「🔍 深度解析（对比我的历史作答）」按钮
  与结果面板（标注"基于最近 N 次作答"与资料依据）
- 顺手修复两个存量前端缺陷（`App.vue` 导航文案替换误用 RegExp 字面量、`WizardView` 从错误模块导入
  `SourceSummary`）——`vue-tsc` 由 4 错误清零

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| `practice_attempts` 加 `answer_text`（尝试级留档） | 只用 `plan_items.answer_text` | 会被下一次作答覆盖，历史原文永久丢失——这是本 change 要解决的第一根线 |
| 错因推导挂在 `record_attempt` 内 | 挂在判分 service 调用方 | 所有调用方（日常/测验/自评）零改动自动获得；漏记类别在结构上消失 |
| 错因纯规则（四态映射） | 用 LLM 分析错因 | 零成本零幻觉可测试；LLM 深度分析保持既有开关预留（默认关） |
| 解析以 plan_items 为锚（新函数） | 改造旧 `generate_explanation`（question_bank 锚） | 日常训练的题在 plan_items 上；旧路径保留兼容并同样注入历史 |

## 非目标（Non-goals）

- 不做解析结果缓存复用（每次点击重新生成，`explanations` 表保留全部历史可回看）
- 不把 `render_context` / `knowledge_profile` 接入出题与路径（训练级记忆注入另行 change）
- 不开 `mistake_analysis` LLM 深度错因开关（保持预留）

## Capabilities

### New Capabilities

- `deep-explanation`：题目级深度解析——尝试级作答留档、规则错因落库、历史对比注入、按需生成与溯源

## Impact

- **代码**：`src/db/tables.sql` + `src/db/migrate.py`（1 列）；`src/services/attempt_service.py`（错因 + item_history + answer_text）；`src/llm/prompts.py`（explanation v1.1.0）；`src/services/explanation_service.py`（新函数 + 历史渲染 + 切片回指）；`src/api/app.py`（新端点）；`web/src/api.ts` + `web/src/components/TaskCard.vue`（前端入口）；`web/src/App.vue` + `web/src/views/WizardView.vue`（存量小修）
- **数据**：生产库经 migrate 自动补 `practice_attempts.answer_text`；此后每次作答留原文
- **风险**：低——新增列可空、新增函数独立、旧解析路径同步注入历史（默认占位）；全量回归验证
- **测试**：新增 `tests/test_explanation_item_history.py`（5 用例：错因推导/空要点/历史注入/无题目/端点契约）
- **证据**：测试输出；解析链路审计行由 #3 的覆盖冒烟覆盖（explanation purpose）
