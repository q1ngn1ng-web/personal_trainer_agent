# 20260920 · fix · 验收判据的百分比口径

## 现象

接入真实 LLM 后，模型对「正确率 ≥ 80%」返回：

```json
{"type": "quantitative", "metric": "accuracy", "target": 80, "unit": "%"}
```

而 `validate_acceptance` 对 `accuracy` 只接受 `0 < target <= 1`，于是把这个**完全合格的判据判为不合格**，
系统会继续追问——用户明明已经给了明确标准，却被反复追问。

## 根因

校验器按"比例"设计（0.8），但模型与用户都习惯用**百分比**（80%）。
两边口径不一致，且该问题只在真实模型调用下暴露——单元测试里我一直用 0.8 写样本，所以没trigger。

## 修复

| 改动 | 内容 |
|---|---|
| `src/core/goal.py` | `_target_is_valid` 同时接受 `(0, 1]` 与 `(1, 100]`；新增 `normalize_acceptance_target`，把 `accuracy` 的百分比统一换算成比例存入 `normalized`（80 → 0.8） |
| `src/llm/prompts.py` | prompt 里明确要求 `accuracy` 的 target 用 0-1 比例（如 0.8），减少歧义 |
| `tests/test_goal_clarification.py` | 新增/调整 3 项：百分比归一化、1.5 视为 1.5%、180 仍判不合格 |

## 影响范围

- 累计测试从 93 增至 **95 passed, 1 skipped**
- 修复后同一段真实模型输出不再被判为缺失字段
- 这是"真实调用才能暴露的问题"的典型例子：**单测样本自己写，就会不自觉地只覆盖自己想到的口径**

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/core/goal.py` | 修改（口径容忍 + 归一化） |
| `src/llm/prompts.py` | 修改（prompt 明确比例口径） |
| `tests/test_goal_clarification.py` | 修改（新增 3 项断言） |

## 关联 OpenSpec change id

`goal-clarification-confirm`（已归档；本次为归档后的缺陷修复）
