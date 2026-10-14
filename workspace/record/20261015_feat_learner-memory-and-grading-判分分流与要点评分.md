# 20261015 feat 判分按题型分流与要点评分（数据层 + 判分）

## 变更摘要

为 OpenSpec change `learner-memory-and-grading` 落地前两个阶段：

1. **数据层（tasks 1.1—1.4）**：`question_bank` 增 `question_type` / `options`；
   新增 `question_points`（题目要点清单）；`practice_attempts` 增 `score` / `point_results`；
   `assessment_items` 增 `question_type`。同步补了可重复执行的迁移。
2. **判分（tasks 2.1—2.4）**：新增 `src/services/grading_service.py`，按题型分流——
   选择题、填空题走确定性判分（不调用大模型），主观题按「覆盖率 × 正确性」给分并输出缺失/错误要点，
   必答要点缺失一票否决；判分结果可写回 `practice_attempts`。

## 影响范围

- 数据库：新增 1 张表与 6 个字段，均为向后兼容的加法变更；老库迁移后 `question_type` 默认 `qa`。
- 判分：新增独立模块，**尚未替换既有 `quiz_service` 的判分路径**，因此现有行为不变。
- 未新增任何大模型调用；客观题路径经测试证明零模型调用。

## 相关文件

- `src/db/tables.sql`（表结构）
- `src/db/migrate.py`（`_GRADING_COLUMNS` / `_ensure_question_points`）
- `src/services/grading_service.py`（新增）
- `tests/test_grading_service.py`（新增，12 条用例）
- `workspace/decisions/ADR-0022-判分按题型分流与要点评分.md`（新增）
- `workspace/evidence/20261015-判分分流与要点评分.md`（新增）

## 验证

- `uv run pytest -q` → 228 passed, 1 skipped, 30 subtests passed（基线 216 passed）
- `uv run pytest -q tests/test_grading_service.py` → 12 passed

## 关联 OpenSpec change

`learner-memory-and-grading` —— 已完成阶段 1 与阶段 2 的 2.1—2.4；2.5 与后续阶段待做。

## 补记（同日）

用户敲定三个产品参数，已落到代码与 ADR：

- 达标阈值 `DEFAULT_PASS_THRESHOLD = 0.8`；
- 整场评分权重：客观题 `0.6` / 主观题 `0.4`，新增 `type_weight()` 与 `overall_score()` 两个纯函数；
- 必答要点由 LLM 建议、人工可改（落在阶段 3 的出题链路）。

**依赖发现**：2.5 的接线无法独立完成——`quiz_service` 目前直接采信 LLM 给出的 pass/fail，
要改走要点评分必须先让题目带要点清单、并让判分 prompt 产出逐条判定。因此 2.5 应排在 3.1 / 3.3 之后，
已在 change 的 tasks.md 中注明。

验证：`uv run pytest -q tests/test_grading_service.py` → 14 passed。
