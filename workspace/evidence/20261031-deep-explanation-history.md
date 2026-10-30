# 2026-10-31 · 深度解析历史注入验证（item-history-deep-explanation）

> 对应 change：`item-history-deep-explanation` ｜ 复现：`uv run pytest tests/test_explanation_item_history.py -q`

## 一、端到端场景验证（用户诉求的直接复现）

种子：一道题两次作答——第一次答「RDB 是日志」（缺必答要点 p1）、
第二次答「RDB 是一种日志，每次写入都记录」（p2 wrong）。

```
record_attempt × 2 → practice_attempts 两行，各自保留当次原文（answer_text 列）
                   → mistake_reasons：{p1: key_omission, p2: concept_confusion}
generate_item_explanation → 注入的 attempt_history 含：
  第1次（…，第 1 轮）：未通过；错因：关键遗漏。作答：RDB 是日志
  第2次（…，第 1 轮）：未通过；错因：概念混淆。作答：RDB 是一种日志，每次写入都记录
→ explanations 落库 prompt_version=v1.1.0，attempts_used=2
```

## 二、测试结果

```
uv run pytest tests/test_explanation_item_history.py -q
5 passed
```

覆盖：错因推导（必答缺失/概念混淆）、无要点不伪造错因、历史注入（两次原文+中文标签）、
无题目时明确报错、端点 200/404 契约（TRAINER_AUTH=0 个人版形态）。

## 三、前端

```
npx vue-tsc --noEmit   → 0 errors（存量 4 个错误一并清零）
npm run build          → ✓ built in 2.66s
```

## 四、全量回归

```
uv run pytest tests/ -q
280 passed, 1 skipped, 30 subtests passed in 213.29s
```
