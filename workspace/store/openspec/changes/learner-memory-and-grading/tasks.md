# learner-memory-and-grading · 任务清单

> 按依赖顺序编号，每个任务写明验收方式。设计见 design.md。

## 1. 数据层

- [x] 1.1 `question_bank` 新增 `question_type`（choice / fill / qa）与 `options` 字段
  - 验收：`init-db` 后可查看；旧数据 `question_type` 默认 `qa`，不丢数据
- [x] 1.2 新增 `question_points` 表（题目要点清单：要点文本 / 权重 / 是否必答）
  - 验收：一道题能查到其全部要点及权重，必答项可标记
- [x] 1.3 `practice_attempts` 新增 `score`（0—1）与 `point_results`（要点级明细）
  - 验收：一次作答能查到分数与每条要点的判定结果
- [x] 1.4 `assessment_items` 新增 `question_type`（判分分流依据）
  - 验收：迁移可重复执行，老数据默认为 `qa`

## 2. 判分

- [x] 2.1 新增 `src/services/grading_service.py`：统一判分入口，按 `question_type` 分流
  - 验收：choice / fill 不产生任何 LLM 调用（可用 `llm_calls` 表断言）
- [x] 2.2 实现客观题判分：choice 比对正确项；fill 归一化后精确比对
  - 验收：同义但不同写法的填空判为不通过（本期明确不处理同义答案）
- [x] 2.3 实现要点评分：覆盖率 × 正确性，必答项缺失一票否决
  - 验收：三个要点答两个得 2/3；答满但说反一条低于答两个
- [x] 2.4 判分结果落库：分数 + 缺失要点 + 错误要点
  - 验收：判分后能直接读到"缺哪条、错哪条"
  - 注（2026-10-15）：`record_attempt_score` 已把分数与要点级明细写回 `practice_attempts`；
    **测验链路（quiz_service）尚未接线**，留在 2.5 之后一并处理
- [x] 2.5 达标判定改造：必答项全中 + 总分 ≥ 阈值，且保留"连续 2 次"
  - 验收：阈值可配置；未达阈值不写入 passed
  - 完成（2026-10-15）：`QUIZ_GRADE_PROMPT` 升级为 v1.1.0、`QUIZ_GRADE_SCHEMA` 改为逐条要点四态判定；
    `quiz_service.grade_with_llm` 现在只把模型的逐条语义判定交给 `grading_service`
    算分与达标（阈值 0.8 + 必答否决），写入的 verdict 即新口径。
    "连续 2 次"沿用既有 `mastery.evaluate` 管线，未改动。
    历史题（无要点清单）自动退回旧的二元口径，不伪造分数。
  - 注（2026-10-15）：判定规则已在 `grade_question` 内实现（`passed = 无必答缺失 and score ≥ 阈值`），
    但**尚未接入** `core/mastery.evaluate` 与 `attempt_service` 的通过/连续管线。
  - 依赖发现（2026-10-15）：接线**依赖阶段 3**——`quiz_service` 现在拿的是 LLM 直接给的 pass/fail，
    要用要点评分必须先让题目带要点清单、并让判分 prompt 产出逐条判定。**2.5 应在 3.1/3.3 之后收口。**
  - 已定参数：达标阈值 `0.8`；整场评分权重 客观题 `0.4` / 主观题 `0.6`；必答点 LLM 建议 + 人工改。

## 3. 出题

- [x] 3.1 出题 prompt 支持按题型出题，并同时产出结构化要点清单
  - 验收：三类题型都能生成，要点清单带权重与必答标记
  - 注（2026-10-15）：**必答标记由 LLM 建议、用户可改**（用户决策）。
  - 注（2026-10-15）：已改 `TRAIN_QUESTION_PROMPT` 与 `TRAIN_QUESTION_SCHEMA`（新增 `question_type` / `options` / `points`）。
- [x] 3.2 选择题干扰项必须取自同一资料片段
  - 验收：抽样检查，干扰项均能在来源切片中找到依据
  - 注（2026-10-15）：prompt 已约束，且在 `validate_generated_question` 里做成**可断言的校验**——
    传入资料原文时，选项文本若在原文中找不到依据即判为"疑似编造"并拒绝落库。
- [x] 3.3 题目落库时写入 `source_chunk_ids` 与 `question_type`
  - 验收：每道题都能回指资料来源
  - 注（2026-10-15）：`source_chunk_ids` 原本就由 `plan_service.register_in_question_bank` 写入；
    `question_type` / `options` / 要点清单由 `question_service.save_generated_question` 落库。

## 4. 记忆

- [ ] 4.1 新增 `src/services/memory_service.py`：把事实与统计渲染为紧凑上下文
  - 验收：一次渲染包含画像 / 题型分布 / 本场进度 / 当前题背景四段
- [ ] 4.2 实现薄弱点画像（纯 SQL）：知识点掌握度、稳定通过率、高频错误类型、题型失误分布
  - 验收：不产生 LLM 调用；给定训练计划能查出各知识点状态
- [ ] 4.3 整场评分与解析改用 memory_service 组装上下文
  - 验收：不再把原始作答全集塞进 prompt
- [ ] 4.4 记录并验证上下文规模
  - 验收：产出"渲染后 token vs 原始作答 token"的对比数据

- [ ] 4.5 错因推导（纯函数）：由要点判定推导错因枚举，写入 `practice_attempts.mistake_reasons`
  - 验收：missing → 记忆缺失、wrong → 概念混淆、partial → 表达不完整；该过程不产生 LLM 调用
- [ ] 4.6 新增 `mistake_analysis` 表与"是否开启错题分析"开关
  - 验收：开关关闭时零调用；开启时分析文本单独入库，不覆盖规则错因
- [ ] 4.7 历史错因注入：`memory_service` 渲染"该知识点近 N 次错因"摘要
  - 验收：构造同一错因出现 3 次的场景，评价里能说出次数
- [ ] 4.8 错因聚合查询：按知识点统计高频错因
  - 验收：能回答"这个错因出现过几次"

## 5. 整场评分

- [ ] 5.1 测验结束后聚合每题结果，写入 `assessments.score` 与 `passed`
  - 验收：一次测验能查到总分与是否通过
- [ ] 5.2 生成综合反馈：总分 + 知识点掌握 + 薄弱点 + 下一步建议
  - 验收：反馈里能指出具体薄弱知识点，而非泛泛而谈

## 6. 按需解析

- [ ] 6.1 用户请求解析时生成，且必须引用资料来源原文片段
  - 验收：解析包含可回指的来源片段
- [ ] 6.2 记录"查看解析"为学习信号
  - 验收：能按题目统计解析查看次数

## 7. 自适应出题

- [ ] 7.1 下一场测验的题型配比按上一场的题型失误分布调整
  - 验收：构造"选择题失误多"的场景，下一场选择题占比上升

## 8. 验证与收尾

- [ ] 8.1 人工标注 20—30 题，测判分一致性
  - 验收：产出系统判分与人工判分的吻合度数据
- [ ] 8.2 同一份作答重复判分的稳定性测试
  - 验收：产出分数波动范围
- [ ] 8.3 跑 `uv run pytest -q`，补对应单测
  - 验收：全绿；要点计分、分流、必答否决均有单测
- [ ] 8.4 回填证据：把指标写进 `workspace/evidence/`
  - 验收：简历里的每个数字都能指到证据文件
- [ ] 8.5 写 `workspace/record/` 变更记录并 git 提交
