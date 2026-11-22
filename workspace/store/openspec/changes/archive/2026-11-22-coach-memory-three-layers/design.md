# coach-memory-three-layers · 设计

## D1 三层 = 同一事实库的三个投影（不新增存储）

会话小结=按 (training_id, date) 的聚合投影；连败=按 item_key 的规则投影；
偏好=app_settings 投影。事实源仍是 practice_attempts / learner_knowledge——
任何视图可重放，删视图不伤地基。

## D2 连败计数的精确定义

```
streak(item_key) = practice_attempts WHERE training_id=? AND item_key=?
                   AND source IN ('llm','quiz')          ← practice-only 无客观信号，不计
                   ORDER BY id DESC 的前导 fail 连续数     ← 首个 pass 即止
```
- 口径与判分阈值天然统一：verdict=fail ⟺ score<0.8 或必答缺失（无新标准）
- coach_hint 文案模板：连败次数 + 历次分数 + 「建议深度解析看共同错因」；
  ≥3 触发（用户原案：前三次不理想、第四次再错即提示）
- 该字段同时是 `adaptive-practice-composition`（回炉题触发）与
  `performance-driven-scheduling`（fail 重置已在阶梯模型内）的现成输入——
  本 change 只产出数据，不做回炉/改排期行为

## D3 会话小结的"会话"定义

**一次训练日** = (training_id, attempt 当地日期)。"日期"取 attempt.created_at 的本地日
（与 local_today 同口径）。不做跨训练日聚合（首页仪表盘已覆盖全局视角）。
叙述分层：结构化字段（纯规则）恒定输出；人话叙述默认模板拼接
（「今天 X 题、通过率 Y%、最弱：Z（连败 N 次）」），LLM 叙述为开关预留项（默认关）。

## D4 偏好的边界（合意困难）

偏好三键全部只影响**呈现与节奏**：提示开/关、每日时长目标（喂将来的错峰调度）、
题型倾向（出题形式）。**MUST NOT** 影响：出什么知识点、判分口径、达标条件、
间隔算法参数——内容与标准永远由学习科学侧决定，不由舒适度决定。
键命名与解析沿用 memory_service 的 app_settings 先例（snake_case、get_bool/int 模式）。

## D5 给实施会话的冲突避让清单（重要）

本 change 的实施会话（另一会话）注意：

1. **热区文件**：`answer_service.py`（submit_answer 返回 dict）与 `app.py`（端点区）——
   并行会话近期在此活跃（判分缓存、plan-sharing）。开工前 `git status` + 全量回归；
   只做**附加字段/新增端点**，不改现有键与路由；
2. **路由顺序陷阱**：新 GET 端点必须注册在 `app.py` 文件尾 SPA 通配路由**之前**
   （历史上通配路由前置吞过 `/api/org/*`，见 app.py 尾注释）；
3. **改动纪律**：每次收尾跑全量 pytest（当前基线见最新 record，≥351）→ record/evidence →
   独立 commit，与并行会话的提交分开；判分区文件若与并行会话同时脏，先协调再动
4. **不要动**：判分公式/verdict/达标、learner_knowledge 结构、现有响应的既有键、
   tables.sql 中 plan-sharing 的未提交改动
5. 与既有 backlog 的边界：本 change 产出 streak 数据与偏好键；
   回炉/排期行为属 `adaptive-practice-composition` / `performance-driven-scheduling`

## D6 回滚

纯附加字段与新增端点；revert 提交即可，无数据迁移、无 schema 变更。
