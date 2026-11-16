# layered-learner-memory · 设计

## D1 mastery 递推为什么用 Elo 式而不是均值/BKT

均值（AVG）对早期信息过重且无次序概念（先错后对与先对后错同分）；完整 BKT 需要参数拟合。
Elo 式 `m += K(outcome-m)` 只依赖次序与最新状态：连续两次通过从 0.5 → 0.675 → 0.789（接近
0.8 达标线的直觉匹配），一次 fail 立即回落到 0.51——"最近表现主导"正是教练语义。K=0.35 可解释
（约三次一致表现收敛）、可测试、零参数拟合。

## D2 衰减读时计算

decay = mastery × 0.5^(days/30)。不落盘、无定时任务、无一致性窗口；30 天半衰期与五轮排期的
最长间隔（+30）呼应。消费方（调度/对话 agent）读到的永远是"此刻的掌握度"。

## D3 误解清单=最近一次判分的投影

"活跃误解"定义为最近一次判分中 wrong 或 必答 missing 的要点（带文本与错因码）。
整体替换而非状态机：可从 attempts 完整重放（与增量收敛，有守卫测试），无累积漂移。
detail 里已有 point_text（grading-rubric-hardening 的快照）——两个 change 天然衔接。

## D4 派生层失败不阻塞事实

record_attempt 是全部作答的唯一入口；learner 更新在其后同一事务内，但 try/except 包裹
只告警——事实记录（attempts）是单一事实源，派生层可随时 rebuild 追平。

## D5 回滚

DROP TABLE learner_knowledge + revert；无消费方依赖，零风险。
