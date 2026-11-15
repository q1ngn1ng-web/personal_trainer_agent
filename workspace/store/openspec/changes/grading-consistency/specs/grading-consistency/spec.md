# grading-consistency Specification

## ADDED Requirements

### Requirement: 同输入判分结果恒定

系统 SHALL 对同一（模型, prompt 版本, 题目, 参考答案, 要点清单, 作答）的判分
返回**逐字一致**的结果：首次判分结果幂等缓存，重复判分 MUST 命中缓存且
MUST NOT 产生新的模型调用。缓存 MUST NOT 存储最终分数（分数由规则层实时计算），
且缓存键 MUST 包含模型与 prompt 版本（任一变化即失效）。

#### Scenario: 同卷同答重复提交

- **WHEN** 同一作答对同一计划项再次提交判分
- **THEN** 命中 grading_cache，本次判分零模型调用
- **THEN** 返回结果与首次逐字一致

#### Scenario: prompt 升级后重新判分

- **WHEN** quiz_grade prompt 版本升级
- **THEN** 旧缓存键失效，下一次判分重新调用模型并写入新缓存

### Requirement: 判分用途温度确定化

quiz_grade 用途的模型调用 SHALL 使用 temperature 0（消除客户端采样噪声）；
其余用途保持默认温度。客观题（choice/fill）MUST NOT 经过任何模型调用。

#### Scenario: 判分请求采样参数

- **WHEN** 发起 quiz_grade 判分调用
- **THEN** 请求体 temperature 为 0

#### Scenario: 客观题不经模型

- **WHEN** 用户提交选择题或填空题
- **THEN** 判分由规则层确定性完成，全程零模型调用
