# item-history-deep-explanation · 任务清单

- [x] 1.1 `practice_attempts` 增加 `answer_text`（tables.sql + migrate 补列）；`record_attempt` 新增参数并写入；日常判分与测验回写两个调用点传入原文
  - 验收：测试中两次作答的历史分别读到各自原文；老库 migrate 后列存在
- [x] 1.2 `record_attempt` 内按 `point_results` 推导错因并落 `mistake_reasons`
  - 验收：必答缺失→key_omission、wrong→concept_confusion（测试断言）
- [x] 1.3 `attempt_service.item_history`：时间正序返回最近 N 次作答（原文/结果/分数/错因/来源）
- [x] 1.4 `explanation` prompt 升 v1.1.0（新增 `attempt_history` 变量与对比要求）；旧 `generate_explanation` 同步注入（无历史时占位）
  - 验收：explanations 落库 prompt_version=v1.1.0
- [x] 1.5 `explanation_service.generate_item_explanation`：plan_items 锚 + 历史渲染（中文错因标签）+ training_items 切片回指
  - 验收：注入的历史文本包含两次作答原文与「关键遗漏/概念混淆」标签
- [x] 1.6 端点 `POST /api/plan-items/{plan_id}/explanation`（403/404 守卫、失败映射 400/502）
- [x] 1.7 前端：`api.explanation()` + TaskCard「深度解析」按钮与结果面板；顺手修复 App.vue 正则与 WizardView 类型导入（vue-tsc 0 错误）
- [x] 1.8 测试 `tests/test_explanation_item_history.py` 5 用例 + 全量回归 + 收尾（record/evidence/archive）
