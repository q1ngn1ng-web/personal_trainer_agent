# weekly-review Specification

## MODIFIED Requirements

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
  - `signal_counts`: 本周四类信号（`too_easy` / `too_hard` / `too_much` / `too_narrow`）各自的次数
  - `assessment_pass_rate`: 本周测验通过项数 / 测验总项数（本周无测验时为 null）
  - `adjustment_count`: 本周实际执行的结构性调整次数
