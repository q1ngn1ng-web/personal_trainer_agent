# adaptive-practice Specification

## ADDED Requirements

### Requirement: 日常训练支持错题回炉与同题巩固

当用户进入当日训练时，系统 MAY 在新题之外附加**近期错题回炉**（同一知识点或同题，带上限）
与**冷却期外的原题巩固**（低概率），作为附加行呈现（`reason='review_recall'`），
MUST NOT 因此改变主轮次行的排期与「每题最早未完成一轮」的取数语义。
回炉题 MUST 复用 `question_bank` 存量题目，MUST NOT 重新生成。

#### Scenario: 连续答错的知识点出现在次日清单

- **WHEN** 某知识点连续 2 次判分为 fail（错因已随作答落库）
- **THEN** 次日训练清单在主轮次之外附加 1 道该知识点的回炉题（上限内），标识与原因可见
- **THEN** 主轮次行的 due_date、round_index 与达标口径不变

#### Scenario: 回炉题复用存量题目

- **WHEN** 回炉题被点开
- **THEN** 直接返回 question_bank 登记的存量题目，不调用模型重新出题

### Requirement: 支持显式提前训练

用户 MAY 对未到期轮次发起「提前练」：系统 SHALL 提前提供该轮的作答机会并照常判分落库，
MUST NOT 修改该轮的原定 due_date、anchor_date 或累计顺延语义；
提前完成的轮次在到期日 MUST NOT 再次出现。提前练的作答 MUST NOT 被排除在达标判定之外。

#### Scenario: 提前练第 2 轮

- **WHEN** 第 1 轮已通过、第 2 轮 due_date 在 3 天后，用户点击「提前练」
- **THEN** 第 2 轮题目立即可答，作答正常写 practice_attempts
- **THEN** 该轮 due_date 保持原值不变；到期日当天该轮不再出现在清单中
