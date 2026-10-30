# 2026-10-31 · 题目级作答历史注入深度解析（item-history-deep-explanation）

> 类型：feat ｜ 对应 change：`item-history-deep-explanation` ｜ 关联审计：记忆层未接线（P1）

## 变更摘要

让「深度解析」基于题目级作答历史工作——第一次答错、第二次又答错，第三次点解析时
模型能看到前两次怎么错的并给出针对性改进：

1. **`practice_attempts.answer_text` 新列**（tables.sql + migrate 老库补列）：
   作答原文尝试级留档——此前原文只存 `plan_items.answer_text`，会被下一次作答覆盖，历史留不住；
2. **错因自动落库**：`record_attempt` 按 `point_results` 调 `derive_mistake_reasons`
   （纯规则四态映射）写 `mistake_reasons`，日常判分与测验回写全调用方零改动接入；
3. **`attempt_service.item_history`**：时间正序返回最近 N 次作答（原文/结果/分数/错因/来源）；
4. **`explanation` prompt v1.0.0 → v1.1.0**：新增 `attempt_history` 变量；
   有历史时逐次对比、指出重复错误与共性错因、给可执行改进动作；旧 `generate_explanation` 同步注入；
5. **`generate_item_explanation(training_id, plan_id)`**：以计划项为锚，
   切片优先回指 `training_items.source_chunk_ids`（退回 question_bank），
   `explanations` 落库取真实 prompt 版本/模型；
6. **端点 `POST /api/plan-items/{plan_id}/explanation`**（403/404 守卫）；
7. **前端**：`api.explanation()` + TaskCard「🔍 深度解析（对比我的历史作答）」按钮与结果面板；
8. **顺手修复两个存量前端缺陷**：App.vue 导航文案 `replace` 误用 RegExp 字面量、
   WizardView 从错误模块导入 `SourceSummary`——vue-tsc 错误 4 → 0。

## 影响范围

- 数据：生产库经 migrate 自动补列（幂等）；此后每次系统判分作答留原文
- 审计：解析链路经统一客户端自动落 `llm_calls`（purpose=explanation，见同日 llm-audit-unified-client）

## 验证

- `uv run pytest tests/test_explanation_item_history.py -q` → 5 passed
  （错因推导：必答缺失→key_omission / wrong→concept_confusion；历史注入含两次原文与中文错因标签；
   explanations 落库 prompt_version=v1.1.0；无题目报错；端点 200/404 契约）
- `npx vue-tsc --noEmit` → 0 errors；`npm run build` 成功
- 全量回归 `uv run pytest tests/ -q` → **280 passed, 1 skipped, 30 subtests**

## 遗留

- 训练级记忆注入（render_context → 出题/路径）另行 change；
- 解析缓存与 `explanations` 历史回看 UI 另行安排。
