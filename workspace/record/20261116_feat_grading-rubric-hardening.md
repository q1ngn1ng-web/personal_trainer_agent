# 2026-11-16 · 判分细则加固实施（grading-rubric-hardening）

> 类型：feat ｜ 对应 change：`grading-rubric-hardening`（当日提案→当日实施归档）

## 变更摘要

1. **证据引用判分**：`quiz_grade` 升 **v1.4.0**（v1.3.0 已被记忆块迭代占用）——
   hit/partial/wrong 每条判定必附 `evidence`（一字不改摘录作答原文；missing 填空串）；
   schema 同步 required；`grading_service.verify_evidence` 归一化子串核验（去空白/标点/大小写）
   记 `evidence_ok`，**失败只标记不降级不改分**（审计层与算分层分离）。
2. **point_results 快照自包含**：`build_point_results` 统一 dict 格式，每条 detail 快照
   point_text + evidence + evidence_ok——历史判定不因后续要点编辑失义。
3. **要点可编辑**：`update_points` 服务 + `PATCH /api/plan-items/{id}/points`；
   首次判分前可增删改（重编号 p1..pN、weight 0.5-5 校验），存在 source='llm' 判分作答即 409 锁定；
   TaskCard 增加「要点清单（判分依据，答前可修正）」编辑器；`/question` 响应补 points。
4. **顺带修复**：日常判分 point_results 曾被改为 list 格式导致
   `derive_mistake_reasons` 不认、**日常作答错因不落库**——本次统一 dict 格式修复断链（端到端测试断言）。

## 影响范围

- `src/llm/prompts.py`（quiz_grade v1.4.0 + 修掉重复编号 4）、`src/llm/schema.py`（evidence 必填）
- `src/services/grading_service.py`（normalize_for_evidence / verify_evidence / build_point_results 纯函数）
- `src/services/answer_service.py`（evidence 透传、point_results 重建、update_points、PointsLockedError）
- `src/api/app.py`（PATCH 端点 + question 响应带 points）；`web/src/api.ts` + `TaskCard.vue`（编辑器）
- 测试：新增 `tests/test_grading_rubric.py`（11 用例）；更新 4 个存量文件的 fixture/版本钉

## 验证

- `uv run pytest tests/test_grading_rubric.py -q` → 11 passed
- 全量 `343 passed, 1 skipped, 30 subtests`；前端 vue-tsc（本变更零错误）+ build 通过
- 证据：`workspace/evidence/20261116-grading-rubric-hardening.md`

## 遗留

- 深度解析高亮证据位置（可选增强，未做）
- 测验链路 evidence 落点：测验 attempt 本不带 point_results（既有口径），与判分缓存/幂等方案一起后续统一
