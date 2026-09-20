# 代码审计简报（给 high 档会话）

> 目的：让审计**带着具体怀疑点**进行，而不是泛泛 review。
> 生成时间：2026-09-20。项目现状见 `workspace/HANDOFF.md` 与 `workspace/SUMMARY-20260920.md`。

## 审计范围

本轮快速实现（约 10 个提交）新增的模块：

```
src/core/goal.py                    目标澄清领域逻辑
src/core/source.py                  切片与影响面
src/services/goal_clarification_service.py
src/services/source_service.py      来源登记/解析/检索/影响面
src/services/doc_parser.py          PDF/Word/Excel 解析
src/services/web_source.py          网络抓取与正文抽取
src/services/edge_service.py        理解边缘探测
src/services/path_service.py        训练路径生成
src/services/signal_service.py      四失信号与动作裁决
src/db/migrate.py                   表重建迁移
```

**不要审** `src/ui/` 的样式、不要审 `src/` 下的老 demo 代码（用户明确说不用管）。

## 我自认为的问题（按严重度排，请重点验证这些）

### 高：会影响正确性

1. **`signal_service` 的客观表现是"循环论证"**
   `objective_state()` 用 `training_items.status` 当客观表现，而 `status` 又被每日任务卡的勾选直接写成
   `passed`（`page_daily._render_task_checkbox` → `path_service.mark_item`）。
   于是"自评太简单"几乎必然命中 `objective=high` → 直接升难度。
   **请判断**：这个代理口径是否成立？在作答记录落地前应该怎么处理才算诚实？

2. **勾选 = 达标，语义混淆**
   现在勾选任务就把训练项标成 `passed`，但它既不是"练过"也不是"连续 2 次达标"（ADR-0010 要求后者）。
   连带后果：**当天把当前阶段的项全勾完，第二天 `today_tasks` 会跳到下一阶段或返回空**。
   **请判断**：在达标判定落地前，最低成本且不撒谎的做法是什么？

3. **`edge_service` 的三态判定依赖 LLM 给的难度**
   `judge_state(verdict, difficulty)` 用"难度 ≥3 且答对 = 已掌握"。难度是模型自报的，
   同一个知识点两次探测可能给不同难度 → **三态结论不稳定**，而且没有依据校验（ADR-0010 要求必须带 `basis`）。
   **请判断**：单题口径下有没有更稳的判定方式？

4. **知识点选取是"按顺序取前 8 个"**
   `build_knowledge_points(limit=8)` 取切片出现顺序的前 8 个。一份 19 个知识点的资料，
   后 11 个**永远探测不到**，且没有告知用户。

### 中：工程与一致性

5. **`tables.sql` 与 `migrate.py` 各写了一份建表 DDL**
   `migrate._TRAININGS_DDL` / `_LLM_CALLS_DDL` / `_SOURCES_DDL` 与新表结构重复。
   已经出现过"加字段要改两处"（`enabled`）。是否应该只保留一份？

6. **`llm_calls.call_purpose` 去掉了 CHECK**，好处是不用再重建表，代价是拼错用途不会报错。
   是否需要加应用层校验？

7. **`source_service` 每个函数都新开连接**（`_connect` + `close`），没有事务边界；
   批量操作（解析 19 个切片）在多次调用下会反复开关连接。

8. **私有函数跨模块导入**：`page_new_training` 直接 `from src.ui.page_sources import _render_add_forms`。
   是否该抽成共享组件模块？

9. **`path_service.generate_skeleton` 的超支重试是字符串拼接**
   把 `report.message` 拼进 `variables["goal"]`（本来是个 JSON 字符串）。能用但很脏。

10. **`page_path` 的「丢弃草案」是死按钮**：提示写着"未实现删除"。

### 低：测试与边界

11. **测试几乎只覆盖降级路径**：所有 LLM 调用都被注入成失败（这是为了快和确定），
    所以 `_skeleton_from_output` 等**成功路径的字段解析几乎没测**。

12. **`split_markdown` 的超长切分按字符硬切**，可能从句子中间切断。

13. **`doc_parser.parse_pdf` 的标题启发式**（字号 ≥ 正文 ×1.12）没有回归样本，
    换一份排版不同的 PDF 可能失效。

14. **`web_source` 的正文抽取是 stdlib 规则实现**，没有对含 `article` 嵌套的页面做验证。

15. **`goal.py` 的 `is_vague` 是关键词黑名单**（"比较熟练""差不多"…），
    覆盖不了同义表达，可能把合格判据误判为不合格。

## 输出要求（给审计方）

1. **不要直接改代码**——本轮只出审计结论
2. 每条问题给出：**现象 → 证据（文件:行）→ 影响 → 建议**，并按"必须改 / 建议改 / 可忽略"分级
3. 明确区分**「我认为是 bug」**与**「我不确定，需要问用户」**
4. 结论写进 `workspace/evidence/`（审计报告）与 `workspace/record/`（一条 docs 记录），
   不要只留在对话里
5. 若发现本轮实现与 ADR 冲突（ADR-0001/0006/0009/0010/0011/0015/0017/0018），单独列一节

## 建议的审计顺序

```
1. 先读 workspace/HANDOFF.md + SUMMARY-20260920.md（3 分钟建立全局）
2. 跑一遍 uv run pytest -q 与 openspec validate --all --store store（确认基线）
3. 按上面「高」的 4 条逐条验证（这是最可能真出问题的地方）
4. 再看「中」的工程一致性问题
5. 最后扫「低」的边界
```
