# 2026-11-16 · 判分细则加固验证（grading-rubric-hardening）

> 对应 change：`grading-rubric-hardening`（本次已实施并归档）｜ 复现命令见各节

## 一、守卫测试

```
uv run pytest tests/test_grading_rubric.py -q   → 11 passed
```

覆盖：归一化核验（中文标点/大小写/空白；编造引用→False；空→False）；
point_results 快照（point_text/evidence/evidence_ok；missing→None）；**证据不改变得分**
（判定与 coverage 均不因核验失败变化）；schema 拒绝无 evidence 的判定；
日常判分端到端（真实摘录→ok=True、编造引用→ok=False、**错因随作答落库**——断链修复的回归证明）；
要点编辑服务（重编号/校验/判分后锁定）；PATCH 契约（200/400/404/409）。

## 二、schema 契约

quiz_grade v1.4.0：point_verdicts 条目 required=[point_id, verdict, evidence]
（jsonschema 拒绝缺 evidence 的载荷——测试钉死）；版本钉 `tests/test_prompt_schema_contract.py` 同步 v1.4.0。

## 三、顺带修复（发现于实施过程）

日常判分 point_results 此前为 **list 格式**（判分缓存重构引入），而
`derive_mistake_reasons` 只认 dict → 日常作答错因从未落库。
本次统一为 dict + point_text/evidence/evidence_ok 快照，错因链恢复（端到端测试断言 mistake_reasons 非空）。

## 四、全量回归

```
uv run pytest tests/ -q   → 343 passed, 1 skipped, 30 subtests
前端：npx vue-tsc --noEmit（本变更文件零错误；存量 1 错属并行会话 TrainingDetailView）
     npm run build → ✓ built
```
