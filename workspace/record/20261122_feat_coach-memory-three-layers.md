# 2026-11-22 · 教练记忆三层（coach-memory-three-layers）

> 类型：feat ｜ 对应 change：`coach-memory-three-layers`（任务全部勾选）｜ 按 tasks 顺序实施

## 变更摘要

系统此前只会**记**学习信号（practice_attempts 全量留档），不会**读**给用户与教练看。
本次按 change 补上三个消费视图，全部零新表：

- **A 会话小结**（当次会话记忆）：`session_summary.summarize_day(training_id, date)`
  读时聚合当天判分作答——题数 / 通过率 / 错要点频次 / 最弱知识点 / 各题连败状态 +
  规则模板叙述；LLM 叙述为开关预留（`session_llm_narrative`，默认关，只读不实现）；
- **B 连败反馈**（跨次记忆反馈）：`submit_answer` 响应附加 `failure_streak` +
  `coach_hint`（streak≥3 且开关开时给模板文案，含历次分数与深度解析引导）；
  纯规则零 LLM，只加键不改键；
- **C 用户偏好**：app_settings 三键（coach_hint_enabled 默认开 / daily_minutes_target
  默认 30 / question_type_preference 默认 any）+ GET/PUT `/api/preferences`
  （键白名单 + 值校验，非法整批拒绝）。**边界硬约束**：偏好只影响呈现与节奏，
  不碰内容与判分（合意困难）。

## 口径决策（一处与 design D2 的偏差，已申报）

D2 字面写 `source IN ('llm','quiz')`——其注释给出动机是"practice-only 无客观信号，
不计"。但 practice-only 本就不落 attempts；而客观题（choice/fill）判分走 ADR-0015 的
**rule 通道**（确定性、有客观信号）。若按 D2 字面，最常见的客观题连败将永远数不出来，
直接违反 spec 正文"连续判分失败计入"的 MUST。故 streak/小结统一取
`('llm','quiz','rule')`（只排除自评 self），已同步进 tasks 备注与测试。

## 冲突避让执行情况（design D5）

- 开工前 git status + 全量基线 **363 passed**（≥351 ✓）；收尾全量 **375 passed**；
- 只做附加字段与新增端点：submit_answer 既有 8 键原样不动（测试断言键集合）；
  三个新 GET/PUT 路由注册在 app.py 文件尾 SPA 通配路由**之前**（含 `/api/preferences`）；
- 未触碰判分公式 / verdict 语义 / learner_knowledge 结构 / tables.sql；
  streak 数据只产出不消费（回炉/排期属 adaptive-practice-composition 与
  performance-driven-scheduling）；
- 提交与并行会话分开（本提交不含 docs/architecture.md 与 web/index.html——并行改动不收）。

## 验证

- `tests/test_coach_memory.py` 12 用例：来源过滤与 pass 清零、阈值与开关、
  附加字段键集合、小结聚合与空日、越权 403、偏好读写与非法键/值 400；
- 全量 **375 passed + 30 subtests**（基线 363）；`npm run build` 通过；
- 服务重启（8501）后线上冒烟：偏好默认值/写入/非法键 400、小结空日叙述、
  q3ng 越权 403——全部符合预期。
