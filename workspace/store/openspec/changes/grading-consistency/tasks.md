# grading-consistency · 任务清单

## 1. 温度确定化

- [x] 1.1 `client.PURPOSE_TEMPERATURES` + `temperature_for()`，`quiz_grade` → 0.0；`_call_api` 支持 temperature 覆盖
  - 验收：单测断言 `temperature_for("quiz_grade") == 0.0`、其余用途保持默认

## 2. 幂等缓存

- [x] 2.1 `grading_cache` 表：tables.sql DDL + `migrate._ensure_grading_cache_table` + schema 守卫 34 表
  - 验收：全新库 `init_db` 含该表；既有库迁移产出 `grading_cache:new_table`
- [x] 2.2 `src/services/grading_cache.py`：`cache_key`（任一语义输入变化换键）/ `lookup`（坏数据当未命中）/ `store`（首写为准）
  - 验收：`tests/test_grading_cache.py` 六个单测
- [x] 2.3 `answer_service._grade_answer` 与 `quiz_service.grade_with_llm` 接入缓存
  - 验收：集成测试——同卷同答第二次判分零模型调用且结果逐字一致；改答穿透缓存

## 3. 证据

- [x] 3.1 自一致性实验 `scripts/eval_grading_consistency.py`：温度 0.2 vs 0.0 各重判 5 次，记录判定组合数、得分范围、pass/fail 翻转
  - 验收：`workspace/evidence/20261029-时间成本基准.md` 追加节含数字
- [ ] 3.2 人工一致率标注（模型判分 vs 人工判定）
  - 验收：使用 `workspace/evidence/判分一致性标注-工作表.csv` 完成一批真实作答标注，逐条要点一致率入 evidence
  - 注：工具与模板已备（20260920 审计批），待对真实作答执行；自一致性数字不替代人工一致率
  - 进展（2026-11-02）：真实数据工作表已预填——`判分一致性标注-工作表-真实数据.csv`
    （库里全部可标注题：2 题 / 6 条要点判定；human/system 列留空待盲标）。
    样本缺口如实记录：距模板要求的 20-30 题尚远，需随真实使用积累作答后扩表。
  - 进展（2026-11-10）：新增 markdown 填写版 `判分一致性标注-人工填写.md`
    （同 2 题 6 条排成表格，用户直接填【你的判定】列；含复标表与样本量声明）——
    等待用户填写完成后跑系统判分并计算一致率。
