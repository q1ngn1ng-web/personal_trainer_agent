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

## D5 回滚

训练级 schedule_mode 隔离新旧口径；回滚=新训练回到旧模型，存量从未迁移，零风险。
