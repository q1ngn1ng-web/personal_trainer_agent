# grading-rubric Specification

## ADDED Requirements

### Requirement: 逐条判定附带可审计证据

`quiz_grade` 判分时，`hit` / `partial` / `wrong` 的每条要点判定 MUST 附带 `evidence`——
引用用户作答原文的连续片段；`missing` 无证据。规则层 SHALL 对 evidence 做归一化子串核验
并在 `practice_attempts.point_results` 记录 `evidence_ok`；核验失败默认仅标记，MUST NOT 自动改判。
证据 MUST NOT 参与得分计算——算分仍由四态系数公式（覆盖率×正确性、必答否决、阈值）决定。
`point_results.detail` 每条 SHALL 快照 `point_text` 与 `evidence`，使历史判定记录自包含。

#### Scenario: 证据可核验

- **WHEN** 模型对要点 p1 判 hit，evidence 为作答原文片段「一条条执行命令」
- **THEN** 归一化核验通过，point_results 中 p1 记 evidence 与 evidence_ok=true
- **THEN** 该条得分系数仍由 verdict 决定，与 evidence 无关

#### Scenario: 证据对不上只标记

- **WHEN** 模型判 partial 但 evidence 在作答原文中找不到（归一化后仍不匹配）
- **THEN** 记 evidence_ok=false，verdict 与得分不变
- **THEN** evidence_ok=false 的占比可统计，作为后续降级策略的依据

#### Scenario: 历史判定自包含

- **WHEN** 用户在另一次作答后回看三个月前的 attempt
- **THEN** 该 attempt 的 point_results.detail 自带当时的要点文本与证据，不因后续要点编辑失义

### Requirement: 要点清单在首次判分前可编辑

用户 MAY 在计划项**首次判分前**编辑要点（增/删/改文本、weight、is_required）；
该计划项已存在 graded attempt 后，编辑接口 MUST 拒绝（409）。
编辑只影响后续判分，MUST NOT 改写任何历史 attempt 的判定记录；
必答缺失的否决口径以判分当时生效的要点清单为准。

#### Scenario: 作答前修正 rubric

- **WHEN** 出题后、作答前，用户删除一条琐碎要点并新增一条关键要点（设为必答）
- **THEN** 判分按新清单执行；新必答缺失则一票否决

#### Scenario: 判分后锁定

- **WHEN** 该计划项已有 graded attempt，用户请求编辑要点
- **THEN** 接口返回 409，历史判定记录不受影响
