# 20261109 fix 四个新模板补 {schema} 占位——首发合规 0/6 → 6/6

> 类型：fix｜关联证据：`workspace/evidence/20261109-首发合规与schema注入.md`

## 变更摘要

train_question / quiz_grade / quiz_variant / explanation 四个新一代模板只在要求里写
"字段见 schema"，模板里没有 `{schema}` 占位符——模型从未见过输出格式定义，首发输出
全靠盲猜（实测首发合规 0/6，全靠错误反馈重试兜底，每次判分两轮往返、延迟翻倍）。

修复：四模板按老 11 个模板的同款句式补占位符，版本升至
train_question v1.1.0 / quiz_grade v1.3.0 / quiz_variant v1.1.0 / explanation v1.2.0。
实测修复后首发合规 **6/6**（+309 tokens 输入换掉一整个重试往返，净账为省）。

quiz_grade 版本升级使 `grading_cache` 旧键自动失效（键含 prompt 版本），重判一次为期望行为。

## 影响范围

- 仅四个模板文本与版本号；`client._run_once` 本就自动注入 schema 变量，代码零改动。
- 判分缓存对 quiz_grade 整体失效一次（v1.2.0 键不再命中）。

## 验证

- 新增 `tests/test_prompt_schema_contract.py`（3 条）：15/15 有 schema 的用途必须含占位符
  （防回退）；四模板版本钉死；schema 渲染后真实出现在 prompt 中。
- 全量测试 **308 passed, 1 skipped, 30 subtests**。
- 实验：`scripts/eval_schema_first_pass.py`（v1.2.0 vs v1.3.0 对照，0/6 vs 6/6）。

## 相关文件

- `src/llm/prompts.py`、`tests/test_prompt_schema_contract.py`、
  `scripts/eval_schema_first_pass.py`、`workspace/evidence/20261109-首发合规与schema注入.md`
