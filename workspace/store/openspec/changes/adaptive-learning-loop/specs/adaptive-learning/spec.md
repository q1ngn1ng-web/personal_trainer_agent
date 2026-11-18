# adaptive-learning Specification

## ADDED Requirements

### Requirement: 缺口触发定向补材且补充资料可溯源

系统 SHALL 仅在明确缺口信号（探测未达、同一知识点错因聚集 ≥2 次、资料覆盖空洞）上生成
**定向补充资料**，作为一等来源落库（`type='ai_generated'`）并照常切片检索。
补充资料生成 MUST 锚定相邻已验证切片，MUST 显式标注「AI 补充」且用户可关闭；
基于补充资料出的题 MUST 回指其切片并保持与原始资料知识点的关联（效度锚定红线）。
系统 MUST NOT 在导入时全量补全资料。

#### Scenario: 错因聚集触发补材

- **WHEN** 某知识点连续 2 次判分为 fail 且原始资料切片不足以覆盖该点
- **THEN** 系统生成一段锚定相邻切片的补充资料，落库为 ai_generated 来源并标注
- **THEN** 基于该补充出的题可回指其切片，并关联原始资料的知识点

#### Scenario: 用户关闭补材

- **WHEN** 用户在设置中关闭「AI 补充资料」
- **THEN** 不再生成新补充；已生成的补充来源保留但不再出新题

### Requirement: 日常训练支持错题回炉与同题巩固

当日训练清单 MAY 在主轮次之外附加**近期错题回炉**（带上限）与**冷却期外的原题巩固**
（低概率），作为附加行呈现（`reason='review_recall'`），MUST NOT 改变主轮次行的排期与
「每题最早未完成一轮」的取数语义。回炉题 MUST 复用 `question_bank` 存量题目。

#### Scenario: 连续答错的知识点出现在次日清单

- **WHEN** 某知识点连续 2 次判分为 fail
- **THEN** 次日清单附加 1 道该知识点的回炉题（上限内），标识与原因可见
- **THEN** 主轮次行的 due_date、round_index 与达标口径不变

### Requirement: 支持显式提前训练

用户 MAY 对未到期轮次发起「提前练」：系统 SHALL 提前提供作答机会并照常判分落库，
MUST NOT 修改 due_date、anchor_date 或累计顺延语义；提前完成的轮次在到期日
MUST NOT 再次出现；提前练作答 MUST NOT 被排除在达标判定之外。

#### Scenario: 提前练第 2 轮

- **WHEN** 第 1 轮已通过、第 2 轮 due_date 在 3 天后，用户点击「提前练」
- **THEN** 第 2 轮题目立即可答并正常落 practice_attempts；due_date 保持原值
- **THEN** 到期日当天该轮不再出现在清单中
