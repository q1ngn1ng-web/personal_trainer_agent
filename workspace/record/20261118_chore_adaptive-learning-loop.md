# 2026-11-18 · 合并 backlog 为「自适应学习闭环」（adaptive-learning-loop）

> 类型：chore ｜ 对应 change：`adaptive-learning-loop`（仅提案，未实施；**取代并合并** `adaptive-practice-composition`）

## 变更摘要

将两条 backlog（错题回炉/提前练 + 定向补材构想）合并为一个完整的 assessment-driven 闭环设计：

- 测量侧（已上线）：系统判分 + 规则错因全量落库；
- 本 change 补后半环：缺口触发总线（probe unreached / 错因聚集≥2 / 覆盖空洞）
  → 定向补材（ai_generated 一等来源，锚定相邻切片，标注可关闭）
  → 错题回炉附加行 + 同题巩固 + 提前训练；
- 沉淀两条红线：**效度锚定**（补充服务于原始资料的掌握，禁止全面重写知识域）、
  **质量门槛**（生成锚定已验证切片、显式标注、用户可审阅可关闭）；
- 灵感来源（仅记录）：对标 [amosblomqvist/learnharness](https://github.com/amosblomqvist/learnharness)
  的 think-out-loud 字段、predict-before-explain、BYOK/记录可检查姿态；
- 删除 `adaptive-practice-composition`（内容全部纳入本 change，git 历史留档）。

## 验证

- `openspec validate adaptive-learning-loop --store store` 通过；零代码改动
