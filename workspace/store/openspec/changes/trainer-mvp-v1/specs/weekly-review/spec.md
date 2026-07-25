# Spec: weekly-review

## ADDED Requirements

### Requirement: 系统每周日自动触发周复盘
系统 SHALL 在每周日首次进入训练主页时检测是否需要周复盘（距离上次复盘 ≥ 7 天）。

#### Scenario: 触发周复盘
- **WHEN** 当前日期为周日 且 `trainings.last_review_at` 距今 ≥ 7 天
- **THEN** 系统显示「本周训练简报」页（含本周数据汇总 + LLM 校准建议）

#### Scenario: 跳过非周日
- **WHEN** 当前日期非周日
- **THEN** 不主动触发复盘，但允许用户手动点击「立即复盘」按钮

### Requirement: 系统机械计算本周指标
系统 SHALL 从 `daily_logs` 汇总本周（最近 7 天）数据，输出结构化指标 dict。

#### Scenario: 指标计算正确性
- **WHEN** 本周 7 天 daily_logs 完整
- **THEN** 系统计算并展示：
  - `avg_completion`: 本周平均任务完成率（0-1）
  - `avg_recall_success`: 本周平均回忆题正确率
  - `three_reflection_coverage`: 三省提交次数 / 7（0-1）
  - `consecutive_days`: 连续打卡天数
  - `weakest_topic`: 回忆成功率最低的单元
  - `strongest_topic`: 回忆成功率最高的单元
  - `missed_tasks`: 本周未完成任务清单

### Requirement: LLM 裁决校准建议
系统 SHALL 把机械指标 + 当前基线评分 + 用户的目标 一起送入 LLM，要求返回校准建议（JSON Schema 强约束）。

#### Scenario: LLM 输出 schema 约束
- **WHEN** 调用 LLM 校准裁决
- **THEN** 输出 MUST 符合 schema：
  - `baseline_score_delta`（number，-1.0 ~ +1.0）
  - `schedule_adjustment`（dict，键为主题单元，值为「降低密度 / 升级 / 维持」）
  - `material_recommendations`（array of {action: add/remove, ref: string, reason: string}）
  - `reward_refresh`（string，本周奖励调整建议）
  - `next_week_focus`（string，下周重点内容维度）

#### Scenario: LLM 调用失败兜底
- **WHEN** LLM 返回无法解析
- **THEN** 系统重试最多 3 次；3 次仍失败则降级为「保持本周计划，仅更新基线（按 avg_recall_success 简单线性映射）」

### Requirement: 用户确认后自动更新训练文件与数据库
系统 SHALL 在用户点击「确认校准」后，把 LLM 校准建议落地到训练文件与数据库。

#### Scenario: 确认校准触发更新
- **WHEN** 用户在简报页点击「确认校准」
- **THEN** 系统：
  - 在 `baseline_history` 新增一条（baseline_score 旧值+delta, recorded_at=now）
  - 把 `trainings.schedule` 与 `trainings.materials` JSON 字段按 material_recommendations 更新
  - 把校准建议渲染为新一周的 `04_复习日历.md` 内容追加
  - 把 `trainings.last_review_at` 更新为 now

#### Scenario: 用户跳过校准
- **WHEN** 用户点击「跳过」
- **THEN** 不更新任何数据，但记录 `review_archives` 一条 `skipped=true`

### Requirement: 周复盘快照归档
系统 SHALL 在每次复盘完成后（不论用户确认还是跳过）写入一行 `review_archives`，用于后续 harness 化分析。

#### Scenario: 复盘快照入库
- **WHEN** 复盘完成（确认或跳过）
- **THEN** 在 `review_archives` 表写入一行：training_id、week_start、metrics JSON、llm_suggestions JSON、user_action（confirmed/skipped）、created_at
- **THEN** 该表数据用于后续 harness 化分析（用户行为趋势、prompt 调优证据）

#### Scenario: harness 查询接口可用
- **WHEN** 外部脚本调用 `get_reviews_by_training(training_id)`
- **THEN** 返回该训练的所有复盘快照，按 `week_start` 倒序