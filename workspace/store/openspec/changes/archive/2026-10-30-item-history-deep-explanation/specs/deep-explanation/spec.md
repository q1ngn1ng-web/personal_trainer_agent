# deep-explanation Specification

## ADDED Requirements

### Requirement: 每次作答在尝试级留档原文与规则错因

系统 SHALL 在 `practice_attempts` 中为每次系统判分的作答保存**当次作答原文**（`answer_text`）
与**规则推导错因**（`mistake_reasons`，由要点四态判定映射为
关键遗漏/记忆缺失/概念混淆/表达不完整，纯规则、不调用模型）。
作答原文 MUST NOT 只存于会被下一次作答覆盖的位置。

#### Scenario: 同一道题两次答错

- **WHEN** 用户对同一道题第一次答「RDB 是日志」（缺必答要点）、第二次答「RDB 是一种日志，每次写入都记录」（概念混淆）
- **THEN** `practice_attempts` 存在两行，各自保留当次原文
- **THEN** 两行的 `mistake_reasons` 分别含 `key_omission`（必答缺失）与 `concept_confusion`

#### Scenario: 无要点判分的作答

- **WHEN** 作答走二元判定（无 `point_results`）
- **THEN** 该尝试的 `mistake_reasons` 为空，不伪造错因

### Requirement: 深度解析基于题目历史作答生成并留痕

用户对某道题请求深度解析时，系统 SHALL 把该题的历史作答（原文、结果、得分、中文错因标签、时间正序）
注入解析上下文；解析 MUST 依据题目关联的资料片段（可溯源），
有历史时 MUST 指出重复出现的错误并给出可执行的改进动作，无历史时按「正确答案 / 本次问题 / 记忆提示」三段输出。
解析文本与来源引用 SHALL 落库 `explanations`（含 prompt 版本与模型），按需生成、不预生成。

#### Scenario: 第三次点深度解析

- **WHEN** 用户对已答错两次的题点击「深度解析」
- **THEN** 解析上下文包含前两次的作答原文与错因标签（关键遗漏/概念混淆）
- **THEN** 返回的解析指出重复错误（把 RDB 说成日志）并给出针对性改进动作
- **THEN** `explanations` 落一行，标注基于的作答次数与 prompt 版本

#### Scenario: 第一次作答就请求解析

- **WHEN** 该题还没有任何判分作答记录
- **THEN** 解析按无历史三段结构输出，不编造历史

#### Scenario: 访问控制

- **WHEN** 用户请求不属于其可见范围的计划项的解析
- **THEN** 返回 403；计划项不存在返回 404
