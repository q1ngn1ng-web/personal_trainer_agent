# performance-driven-scheduling · 设计

## D1 为什么选离散阶梯而不是 SM-2 连续参数

连续 ease factor 需要数据标定，N=1 用户标不出来；离散 5 档每一步用户可预期
（"答对→下次隔更久，答错→明天重来"），纯函数可精确断言。待多用户数据积累，
阶梯可平滑升级为连续参数——模型换心脏不必一次到位。

## D2 为什么预生成行 + 重写日期，而不是增量生成

增量生成让"今日该练什么"从纯查询变成"查询+可能触发生成"，幂等与并发语义全要重设计。
预生成保留 UNIQUE(training_id,item_key,round_index) 与现有查询零改动；
完成事件只 UPDATE 后续行的 due_date，original_date 天然记录生成时口径，轨迹可审计。

## D3 step 推导 vs 存储

attempts 是唯一客观事实源；step 存列就要处理"列与历史不一致"的同步问题。
从 practice_attempts 推导（按 item_key 时间正序回放：pass 前进、fail 归零），
推导函数与 1.1 一起单测。本量级（每题 ≤ 十余次作答）性能无虞。

## D4 与 adaptive-practice-composition 的收编关系

fail→次日重练已覆盖"错题回炉"的主要诉求（近端重练）。
该 backlog 剩余价值：跨知识点巩固混排（好题回炉）与提前练。
实施顺序：先本 change（调度换心脏），再评估收编——避免两个 backlog 各自实现一套"重练"语义。

## D6 演进路径：从离散阶梯到 FSRS

本 change 的五档阶梯是 **FSRS（Free Spaced Repetition Scheduler，Anki 内置）的离散近似**：
阶梯档位即离散化的 Stability S，0.8 通过阈值即目标保持率 desired retention。
三分量映射：R（可提取性）↔ learner_knowledge 的读时衰减 decayed_mastery；
S（稳定度=保持到 90% 的天数）↔ 阶梯间隔；D（难度）↔ difficulty_tier + 答错计数。

演进三步（每步只换"下次何时复习"一个函数，mastery 递推/判分/达标全不动）：

1. **现在**：`core/plan` 的阶梯纯函数（固定档位）——FSRS 的固定参数退化版；
2. **实施本 change**：阶梯随 pass/fail 移动 = 离散 FSRS；`next_due` 保持纯函数接口，
   曲线可插拔；
3. **远期**：practice_attempts 复习历史攒够（数百次）→ 用开源 FSRS 优化器
   （py-fsrs / fsrs-rs）拟合每用户参数 → 真 FSRS 输出 due_date。
   注意概念分工：FSRS 管"还记得吗"（记忆保持），mastery 递推管"学会了没"（能力估计），
   两者互补不替代——难学的点通常也忘得快（D 小 → S 涨得慢），由 D 联通。

**不引入 FSRS 的理由记录**：参数拟合需要数据量，N=1 阶段拟合不出个性化参数；
固定参数的 FSRS 相比离散阶梯只多复杂度不多收益——阶梯够了，接口留好缝。

## D5 回滚

训练级 schedule_mode 隔离新旧口径；回滚=新训练回到旧模型，存量从未迁移，零风险。
