# grading-rubric-hardening · 设计

## D1 为什么证据核验失败不自动降级

模型引用作答时常微改写（去语气词、补标点），严格匹配的自动降级会把大量正确判定误伤成 missing。
先只记 evidence_ok，跑一段时间统计「核验失败且人工复核确属幻觉」的占比，有数字再定降级策略——
与判分阈值校准同一思路：标定优于拍脑袋。

## D2 锁定时机 = 首次 graded attempt

判分标准必须对作答历史稳定：连续 2 次通过才达标，若中途改 rubric，等于换考卷凑成绩。
锁定点是「第一份客观记录产生」——此前随便修，此后不可。409 语义清晰。

## D3 point_text 快照让历史自包含

point_results.detail 原来只存 point_id/verdict；加 point_text+evidence 后，
每条历史判定独立可读（深度解析回看三个月前的作答也不失义），要点编辑自此无历史包袱。
JSON 字段内结构扩展，零迁移成本。

## D4 与既有工作的关系

- `learner-memory-and-grading` 8.1/8.2（判分一致性/重复稳定性标注）：标注回答「判定准不准」，
  本 change 回答「判定凭什么」——两者合起来才是完整的判分可信度叙事；
- `adaptive-practice-composition`（回炉题复用存量题）：要点可编辑后，回炉题的 rubric 同样可先修再练。
