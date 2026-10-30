# item-history-deep-explanation · 设计

## D1 尝试级留档为什么必须加列

作答原文此前只有 `plan_items.answer_text` 一份，语义是"该计划项的当前作答"。
历史对比需要"每次作答各自的原文"，只有尝试级存储能承载。
列可空（自评/纯勾选路径没有原文），migrate 走既有 `_GRADING_COLUMNS` 机制，老库自动补列。

## D2 错因挂 record_attempt 而不是判分调用方

`record_attempt` 是全部作答的唯一入口（日常 `source='llm'`、测验 `source='quiz'`、自评 `source='self'`）。
挂在这里：三个调用方零改动；带 `point_results` 的尝试自动获得错因，
不带（二元判定）保持 NULL——「错因只来自要点判定」的语义不破坏。

## D3 历史渲染的口径

最近 5 次、时间正序；每行：第 N 次（时间截断到分钟，第几轮）：通过/未通过（+得分）；
错因：中文标签（`MISTAKE_REASON_LABELS` 映射，模型不接触内部枚举码）；作答原文截 200 字。
无历史时传占位文本「（无历史作答）」，prompt 按无历史分支走原三段结构。

## D4 解析锚点：plan_items 而不是 question_bank

日常训练的题目/要点/参考答案在 `plan_items` 上（要点判分接线后 `plan_items.points` 是判分锚点）；
question_bank 只在勾选完成后才有题。以 plan_id 为锚对"今天没练完的题"也能解析；
切片回指优先 `training_items.source_chunk_ids`（出题依据），退回 question_bank（测验链路）。

## D5 与 #3 审计的关系

新解析链路经统一客户端 `complete()`，成功/失败自动落 `llm_calls`（purpose=explanation）——
#2 审计下沉让本 change 的可观测性零成本就位。

## D6 回滚

revert 提交即可；`answer_text` 列留在库里无害（可空），migrate 幂等。
