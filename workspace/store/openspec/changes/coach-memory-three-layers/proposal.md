# coach-memory-three-layers · 教练记忆三层视图（提案，待实施）

> 状态：**仅提案，未实施**。本文件为**自包含交接文档**——实施会话只读本 change
> （proposal / design / tasks / specs）即可动手，不需要创建者的对话上下文。
> 来源：2026-11-19 用户提出的三层记忆功能设计（当次会话记忆 / 跨次记忆反馈 / 用户偏好）。

## Why

系统已能完整**记录**学习信号（practice_attempts 全量留档 + learner_knowledge 学习者模型），
但三个**消费者**缺失——记忆写得很全，用户与教练行为都读不到它：

1. **当次会话没有小结**：张三今天练完 4 题，系统知道他哪题错、错因是什么，但没有任何视图告诉他
   "这次练得怎么样、薄弱在哪"；
2. **连败没有反馈**：同一道题连续 3-4 次 verdict=fail（score<0.8），系统全知道，却一声不吭——
   用户第 4 次答错时，正是最需要被提醒"这不是手生，是理解有偏差"的时刻；
3. **偏好无处安放**：提示开关、每日时长、题型倾向——基础设施在（app_settings 键值表已有
   mistake_analysis_enabled / memory_context_enabled 两个先例），偏好项没定义。

## What Changes

**A. 会话小结（当次会话记忆）**：按 `(training_id, 当地日期)` 聚合当天判分作答——
题数/通过率/错的要点聚合/最弱知识点/各题连败状态；纯规则生成结构化小结 + 一段模板化叙述
（可选 LLM 叙述走 app_settings 开关，默认关）。零新表（读时聚合）。

**B. 连败提示（跨次记忆反馈）**：`submit_answer` 响应增加两个**附加字段**
`failure_streak`（连续 fail 次数）与 `coach_hint`（≥3 次时的人话提示，含历次分数）。
纯规则：按 item_key 取最近判分作答数前导 fail；pass 即清零；practice-only 不计数。
同时把 streak 写入响应供深度解析与调度 backlog 消费。

**C. 用户偏好**：app_settings 三个键（见 tasks 0.1）+ `GET/PUT /api/preferences` 读写端点。
**边界硬约束：偏好只影响呈现与节奏，绝不影响学习内容与判分**（合意困难原则——
教练推"需要"，不推"喜欢"）。

### 关键取舍

| 选择 | 备选 | 放弃理由 |
| --- | --- | --- |
| 小结读时聚合 | 会话小结表 | 事实源唯一原则；聚合成本本量级可忽略；无一致性窗口 |
| 连败=纯规则计数 | LLM 判断"该不该提醒" | 确定性可测零幻觉；提示文案可模板化，LLM 叙述留给小结的可选开关 |
| streak 只数 graded attempt | 把 practice-only 也算 | practice-only 无客观信号，计入会污染"连续答错"的语义 |
| 偏好三键起步 | 大而全的偏好体系 | 先立骨架与边界约束，键随功能长 |
| 响应附加字段 | 改响应结构 | 现有前端零破坏；旧字段一个不动 |

## 非目标（Non-goals）

- 不改判分公式、verdict 语义、达标判定（graded attempt 结构零变化）
- 不改排期/回炉逻辑（连败数据是 `adaptive-practice-composition` 与
  `performance-driven-scheduling` 的**输入**，不是本 change 的输出行为）
- 不做会话级 LLM 叙述的默认开启（开关预留，默认纯规则文案）
- 不做偏好对内容选择的个性化（合意困难边界）
- 不做跨训练用户画像聚合（learner_knowledge 已有，属后续视图）

## Capabilities

### New Capabilities

- `coach-memory`：教练记忆的三层消费视图——会话小结（日聚合）、连败反馈（题级规则）、偏好（呈现层）

## Impact

- **代码（实施时）**：`src/services/answer_service.py`（submit_answer 响应附加字段 + streak 纯函数，
  建议落 `src/core/` 或独立小模块便于测试）；`src/services/session_summary.py`（新，读时聚合）；
  `src/api/app.py`（GET 会话小结 + GET/PUT preferences 三个新端点，均走 `_load_training_for`/
  `require_viewer`）；`web/src`（TaskCard 显示 coach_hint、训练详情/Me 页小结卡、偏好设置项）
- **数据**：零新表（聚合读时算；偏好复用 app_settings）
- **测试**：streak 计数规则（含 practice-only 不计数、pass 清零）、小结聚合、端点契约、偏好读写与默认值
- **风险**：低——全部附加字段与新端点；唯一热区是 `answer_service.submit_answer` 返回 dict
  （加键不改键），实施前跑全量回归确认
