# progress-dashboard Specification

## Purpose
TBD - created by archiving change trainer-mvp-v1. Update Purpose after archive.
## Requirements
### Requirement: 首页展示训练列表与项目说明
系统 SHALL 在首页（Streamlit 首页）展示：
- 项目说明（产品定位 + 使用方法 + 真主题 demo 入口）
- 所有训练列表（topic、状态、当前基线、已坚持天数、最近活跃时间）
- 「新建训练」按钮

#### Scenario: 首页加载
- **WHEN** 用户打开应用根路径
- **THEN** 首页可见，按上述结构渲染
- **THEN** 训练列表按 `last_active_at` 倒序排列

### Requirement: P0 指标必展示
系统 SHALL 在每个训练详情页顶部展示：
- 当前基线评分（数字 + 进度条）
- 已坚持天数（从创建日到今天）
- 今日完成度（completed_count / total_count）

#### Scenario: P0 指标实时性
- **WHEN** 用户打开训练详情页
- **THEN** 三个 P0 指标从 SQLite 实时计算（不缓存）
- **THEN** 每次打卡三省 / 勾选任务后，回到详情页能看到指标更新

### Requirement: P1 指标在第二周后启用
系统 SHALL 在 Phase 2 启用以下指标（在 `progress-dashboard` capability 内作为 P1 子项）：
- 基线升级曲线（按周散点图，从 `baseline_history` 读取）
- 回忆题正确率（最近 7 天折线图，从 `daily_logs.recall_success_rate` 读取）

#### Scenario: P1 指标展示
- **WHEN** 训练已运行 ≥ 14 天
- **THEN** 训练详情页展示 P1 指标
- **WHEN** 训练 < 14 天
- **THEN** P1 区域显示「数据收集中，再练 X 天可见」占位

### Requirement: P2 指标远期启用
系统 SHALL 在 Phase 3 启用以下指标（本次 MVP 仅占位、不实现计算逻辑）：
- 阶段目标进度（从 `trainings.targets` 与当前基线推算）
- 三省覆盖率（`three_reflection_coverage` 趋势）

#### Scenario: P2 占位展示
- **WHEN** 用户打开训练详情页且 Phase 3 未启用
- **THEN** P2 区域显示「即将推出」占位，不计算也不展示具体数值

### Requirement: 仪表盘只读，禁止写操作
系统 SHALL 保证仪表盘区域的所有展示组件不修改训练状态数据。

#### Scenario: 仪表盘不可写
- **WHEN** 用户在仪表盘区域操作（点击、拖动、悬停）
- **THEN** 仪表盘只展示数据，不修改训练状态
- **THEN** 修改入口是任务卡 / 复盘页 / 新建向导（不在仪表盘区域）

#### Scenario: 数据来源单一
- **WHEN** 仪表盘组件需要数据
- **THEN** 全部从 `progress_service.py` 提供的只读查询接口读取
- **THEN** 不允许直接调用 `daily_logs` / `trainings` 等表的写接口

