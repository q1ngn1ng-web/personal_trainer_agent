# 20260921 · feat · 定期测验（取题 / 变式 / 判分 / 回退重练）

## 变更摘要

把 `training-execution-feedback` 的**定期测验**这一段做完：从题库取题、生成变式、整卷作答、判分、成绩与未通过回退重练。
严格按 ADR-0016 的约束实现：**排除近期原题**、**用变式题**、**无提示、完成前不给中间结果**、**未通过必须回退重练**。

上一批已排好的"每 14 天一条测验任务"（`plan_items.kind='assessment'`）现在**真的可以做了**：
点「开始测验」→ 整卷作答 → 提交 → 统一出结果。

## 产出

| 文件 | 内容 |
|---|---|
| `src/services/quiz_service.py`（新增） | `question_pool` / `pick_blueprints` / `build_questions` / `start_assessment` / `save_answers` / `grade_with_llm` / `save_manual_verdicts` / `finish_assessment` / `pending_quiz_plan` |
| `src/db/tables.sql` | 新增 `assessments`（批次：trigger / status / score / passed）与 `assessment_items`（题目 + 作答 + 判分） |
| `src/db/models.py` | 新增 `Assessment` / `AssessmentItem` 模型 |
| `src/db/queries.py` | 级联删除补上测验两张表 |
| `src/llm/prompts.py` | 新增用途 `quiz_variant`（蓝本题 → 变式题）与 `quiz_grade`（只判 pass / fail） |
| `src/llm/schema.py` | 新增 `QUIZ_VARIANT_SCHEMA` / `QUIZ_GRADE_SCHEMA` 并注册 |
| `src/ui/page_daily.py` | 新增「3. 测验」区块：开始测验 / 整卷作答 / 提交判分 / 自评兜底 / 结果与补练提示 |
| `tests/test_quiz_service.py`（新增） | 6 个用例：冷却期内外、无题可抽、LLM 不可用退回原题、LLM 可用走变式+判分、自评兜底通过、未通过回退重练并写作答记录 |
| `tests/test_plan_page.py` | 新增 1 个 UI 用例：点「开始测验」生成测验批次（LLM 不可用时也应降级成功） |

## 关键实现细节

1. **池子只放"不是近期原题"的题**：`question_pool` 复用 `plan_service.drawable_questions`，即
   `cooldown_until <= 今天`（冷却期 14 天）。这样"排除近期练过的原题"是**结构性保证**，不靠提示词。
2. **变式优先、降级不撒谎**：`build_questions` 先调 LLM 生成变式（换场景/换问法/改条件，`item_key` 保持回指）；
   LLM 不可用时退回**冷却期外的原题**并把 `is_variant=0` 落库，页面明确标注"含原题（变式生成不可用）"。
3. **判分降级也不撒谎**：LLM 判分不可用时不自作主张，改为**用户自评**，`reason` 写"自评（LLM 判分不可用）"，
   结果页显示 `判分方式：AI 判分 / 自评`。
4. **未通过 = 加练一轮**：对未通过的题目，在**第 5 轮之后**追加一轮补练（`reason='quiz_failed'`，到期日 = 次日），
   并在结果页列出未掌握的知识点。这是 ADR-0016 决策 5 的"回退重练"。
5. **测验结果也进客观通道**：结算时把每道题的判分写成 `practice_attempts(source='quiz')`，
   通过的题顺带做连续达标判定——测验不会再是"练完之后另开一套账"。
6. **答题过程中无提示**：题目只给题干，参考答案仅在结算后（自评时）出现。

## 验证

| 项 | 结果 |
|---|---|
| 全量单测 | **196 passed, 1 skipped, 30 subtests**（新增 7 个用例；改动前 189） |
| 规格校验 | `openspec validate --all --store store` = 13 passed, 0 failed |
| LLM 成功路径 | 单测注入"变式 + 判分"返回，断言 `is_variant=1`、题目文本为变式、成绩 0.5 → 不通过 → 加练 1 轮 |
| LLM 失败路径 | 单测注入必失败，断言退回原题、判分降级自评、仍能结算 |

## 影响范围

- **数据**：新增 `assessments` / `assessment_items` 两张表（`init-db` 自动创建，无需重建旧表）
- **行为**：今日任务卡多一段「测验」；到期测验可整卷作答；未通过的题次日自动加练一轮
- **规格**：`periodic-assessment` 的默认间隔改为 **14 天**（用户 2026-09-20 决策，原写 7 天）；
  `training-plan` 明确"第 5 轮之后不再排期"的**例外**是测验未通过的补练轮次
- **未做**：阶段末触发（4.1 的第三种入口）、重考换新题的显式约束（4.7）、`5.2/5.3` 的阶段/任务达标、
  覆盖模式下"每个必修知识点至少出现一次"（4.3，`mode` 目前恒为 mastery）

## 相关文件路径

- 代码：见上表
- 规格：`workspace/store/openspec/changes/training-execution-feedback/tasks.md`（1.3 / 4.2 / 4.4 / 4.5 / 4.6 / 6.3 勾选）、
  `.../specs/periodic-assessment/spec.md`（间隔改 14 天）、
  `workspace/store/openspec/changes/training-plan-and-daily-view/specs/training-plan/spec.md`（补练轮次例外）
- 决策：`workspace/decisions/ADR-0016-测验题不得取自刚练过的原题.md`
- 审计关联：`workspace/evidence/20260920-服务层代码审计.md` 的 **L2**（成功路径缺测）本条顺带补上

## 关联 OpenSpec change id

`training-execution-feedback`（13/33 → 测验段完成，剩阶段末触发、阶段/任务达标、复盘页指标）
