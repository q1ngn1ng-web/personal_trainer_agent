# 2026-11-22 · 登记教练记忆三层提案（coach-memory-three-layers）

> 类型：chore ｜ 对应 change：`coach-memory-three-layers`（**仅提案，未实施**）

## 变更摘要

用户提出教练记忆的三层功能设计并要求登记为提案，交由另一会话实施（避开并行冲突）：

1. **会话小结**：按 (training_id, 训练日) 读时聚合当天判分作答——题数/通过率/错要点频次/
   最弱知识点/各题连败；规则模板叙述，LLM 叙述开关预留（默认关）；零新表；
2. **连败反馈**：submit_answer 响应附加 failure_streak 与 coach_hint（≥3 次触发，
   含历次分数与深度解析引导）；纯规则；数据可供回炉/调度 backlog 消费；
3. **偏好**：app_settings 三键（提示开关/每日时长/题型倾向）+ 读写端点；
   边界硬约束——偏好只影响呈现与节奏，MUST NOT 影响内容与标准（合意困难）。

提案为**自包含交接文档**：design.md D5 给出实施会话的冲突避让清单
（热区文件、路由顺序陷阱、改动纪律、禁止触碰项、与既有 backlog 边界）。

## 验证

- `openspec validate coach-memory-three-layers --store store` 通过
- 零代码改动，无需测试
