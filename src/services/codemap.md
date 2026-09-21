# src/services/

`src/services/` 是个人训练师 Agent 的"业务编排 + LLM 适配"中间层，位于 UI（`src/ui/`）与底层（`src/core/`、SQLite、LLM client）之间。它把零散的低层原语组合成可被 UI 直接调用的业务流程。

## Responsibility

- **业务流程编排**：把多个原语组装成端到端的工作流（新建训练、周复盘、每日卡片、首页面板）。
- **LLM 适配封装**：把 `src/llm/client.complete` 的多步骤调用（带重试、校验、回退、审计、归一化）封成业务级函数。
- **纯计算**：所有不涉及 LLM 的统计、排序、解析、文件写入与模板渲染均在这里实现。
- **数据形状契约**：通过 `@dataclass` 暴露稳定的输入/输出数据结构给 UI 与上层调用者。
- **审计持久化**：几乎所有 LLM 调用都通过 `record_llm_call` 写入 SQLite 供后续分析。

## Design

- **分层清晰**：
  - 编排层：`trainer_service`（新建）、`review_service`（周复盘）。
  - 子服务（按功能）：`keyword_service` / `baseline_service` / `scoring_service` / `calibration_service`（LLM）；`topic_validation`（LLM）；`plan_service` / `attempt_service` / `quiz_service` / `mastery_service` / `schedule_service` / `recall_service` / `daily_log_service` / `progress_service`（数据视图）；`metrics_calculator`（聚合）；`renderer` / `file_writer`（产物落盘）。
  - 共享基础：每个 LLM 子服务都遵循同一套 `complete → 解析 output_json → record_llm_call` 三段式套路，便于排查。
- **鲁棒性策略统一**：
  - **失败兜底**：LLM 服务一旦调用失败/回退，会写一条 `validation_result="fail"`、`fallback_used=1` 的审计记录，然后回退到 `fallback_for(...)` 或启发式算法。
  - **失败开放（fail-open）**：仅 `topic_validation` 对 LLM 失败采用 fail-open，避免阻塞用户流程；其他服务宁可降级也不走穿。
  - **重试 + 覆盖校验**：`baseline_service` 实现了最多 3 次重试 + `keyword_coverage_check` 校验，不通过即重发。
  - **归一化与钳位**：`calibration_service` 用 `_clamp_delta` 把 `baseline_score_delta` 限定在 ±0.5；`scoring_service` 用白名单过滤非常规标签。
- **数据契约**：所有业务结果都用 dataclass 暴露（`TrainingProgress`、`WeeklyMetrics`、`BaselineQuestions`、`ScoringResult`、`CalibrationSuggestion`、`RecallQuestion`、`TodayTasks`、`TopicValidationResult`、`KeywordResult`、`ReviewOutcome`、`TaskCheckResult`、`ReflectionResult`、`DailyProgress`）。
- **可测性**：纯计算逻辑（`metrics_calculator`、`progress_service`、`schedule_service`、`recall_service`、`renderer`、`file_writer`）不依赖 LLM；其他带 LLM 的服务也允许注入 `today`、`week_start` 等参数便于回放。

## Flow

### 1. 新建训练的总数据流（`create_training`）

`src/ui/` → `trainer_service.create_training(topic, baseline_answers, ...)`

1. `validate_topic` 用 LLM 判断主题是否足够具体（失败开放）。
2. `generate_keywords` 用 LLM 生成关键词白名单、覆盖数、禁忌词。
3. `generate_baseline_questions` 用 LLM 生成 3 道基线诊断题，最多重试 3 次并做关键词覆盖校验；用尽则回退到 `fallback_for("baseline_q")`。
4. **（可选）**`score_baseline` 用 LLM 评分；若 LLM 不可用，用 `_heuristic_score` 做关键词重叠度比较降级。
5. `_build_render_context` 把上述结果 + `daily_minutes`、`total_weeks` 装配成渲染上下文。
6. `render_training_files` 用 Jinja2（`src/templates/*.md.j2`）生成 10 个 Markdown。
7. `sanitize_dir_name` → `check_writable` → `write_training_directory`（原子写入 `training_<slug>/`）。
8. `create_training`（`src.db.queries`）插入 `trainings` 行，状态为 `active`（有基线答案时）或 `created`。
9. `add_baseline_history` 把基线评分折线写入 `baseline_history`。
10. 若 `overall_level=="low"`，再用 `pretrain_checklist` LLM 生成预习清单并 `update_training`。
11. 最后把 ORM 行包成 `domain.core.Training` 返回 UI。
12. 失败时 `_cleanup_dir` 移除已写入的目录，再抛 `TrainerCreationError`。

### 2. 周复盘的总数据流（`review_service`）

`src/ui/` → `review_service.prepare_weekly_review(training_id)` / `apply_weekly_review(...)` / `skip_weekly_review(...)`

1. `prepare_weekly_review`：取 `Training` → `compute_weekly_metrics`（最近 7 天聚合） → `generate_calibration`（LLM weekly_calibration，失败回退到启发式）→ 返回 `ReviewOutcome(applied=False)`。
2. `apply_weekly_review`：先 prepare，然后：
   - `_apply_state_changes` 计算新 baseline_score（钳位到 [0,5]）、新 `baseline_level`、合并 schedule、按 `material_recommendations` 增删 references、调 `current_week += 1`，写回 training；
   - `add_baseline_history` 记录新分数；
   - `create_review_archive` 写入 `review_archives`（status="confirmed"）。
3. `skip_weekly_review`：prepare + `create_review_archive(status="skipped")`，不写状态。

### 3. 每日卡片的数据流（`schedule_service` + `recall_service` + `daily_log_service`）

UI 在"今日训练"页面按以下顺序读取：

- `schedule_service.extract_today_tasks`：读取 `training.schedule.units`，按 `review_count` 与 `learned_date` + `STANDARD_INTERVALS=[1,3,7,15,30]` 判断到期复习；未学过的归为"新内容"（每日上限 `_MAX_NEW_ITEMS_PER_DAY=3`）；无 unit 时返回占位 `TaskItem("N1", ...)`。
- `recall_service.get_today_recall_questions`：从 `materials.recall_units` 取单元，逐个判断 `_unit_due`（同样用 `interval_for_index`），按 `ContentDimension`（概念 / 原则 / 应用 / 反思）以 `DEFAULT_DAILY_RATIO` 做轮询分配，上限 `max_questions=5`。
- UI 把 R/N 任务的勾选 + 三省文本 + 回忆题对错发回：
  - `daily_log_service.check_task` → upsert `daily_log_tasks`、汇总 `completed_count/total_tasks` → `update_daily_log_progress`、并 `update_training(last_active_at=...)`。
  - `daily_log_service.submit_reflections` → `submit_three_reflections` 写三段反思并 bump `last_active_at`。
  - `daily_log_service.record_recall_results` → 在 `daily_logs.recall_questions_total/correct` 上做累加（注意是"叠加"，不是覆盖）。
  - `daily_log_service.get_today_progress` → 喂给 UI 显示。

### 4. 首页 / P1 数据流（`progress_service`）

- `compute_home_dashboard`：遍历 `list_trainings()` → 每个 `compute_training_progress`（抓今天的 daily_log、计算连续天数 ≤ 30 天窗口、days_since_creation 等）→ 返回 `HomeDashboard`（含 active 平均 baseline_score）。
- `get_p1_summary`：训练运行 < `_P1_MIN_DAYS=14` 天 → 返回 `has_enough_data=False` 占位；否则读取 `baseline_history`（baseline_score 折线）+ 近 7 天 daily_logs 的 `recall_success_rate`。

### 5. 周度指标聚合（`metrics_calculator`）

`compute_weekly_metrics` 是 P0/P1 的纯 SQL 聚合：
- 用 `get_daily_logs_in_range` 拿 7 天日志 → 计算 `avg_completion`、`avg_recall_success`、`three_reflection_coverage`、`consecutive_days`、`missed_tasks`。
- 优先从 `trainings.materials` 取单元 recall_rate 决定 `weakest_topic` / `strongest_topic`；若缺则从 `daily_log_tasks.task_ref` 的完成率推断。
- 完全不调 LLM，可独立单测。

## Integration

| 来源 | 内容 | 依赖的服务 |
|---|---|---|
| `src/core/baseline.py` | `compute_level(score)` 把 0–5 折算成 `BaselineLevel` | `progress_service`、`review_service` |
| `src/core/element.py` | `BaselineLevel`、`TrainingStatus` 枚举 | `progress_service`、`trainer_service` |
| `src/core/training.py` | `Training`（领域对象） | `trainer_service`（返回它） |
| `src/core/content_dim.py` | `ContentDimension`、`DEFAULT_DAILY_RATIO`、`distribute_by_ratio` | `recall_service` |
| `src/db/sqlite.py` | `get_connection` | `daily_log_service`、`metrics_calculator`、`progress_service` |
| `src/db/queries.py` | `get_or_create_daily_log`、`update_daily_log_progress`、`update_training`、`get_training`、`get_daily_logs_in_range`、`list_trainings`、`create_training`、`add_baseline_history`、`create_review_archive`、`submit_three_reflections`、`record_llm_call` | 所有服务 |
| `src/db/models.py` | `Training`（行模型） | `calibration_service`、`review_service` |
| `src/llm/client.py` | `complete(prompt_name, variables)`、`LLMError` | 所有 LLM 子服务 + `trainer_service.pretrain_checklist` |
| `src/llm/prompts.py` | `PROMPT_REGISTRY`、`WEEKLY_CALIBRATION_PROMPT_VERSION` | 所有 LLM 子服务 |
| `src/llm/schema.py` | `SCHEMA_REGISTRY`（每个 prompt 对应一份 JSON Schema） | 所有 LLM 子服务 |
| `src/llm/validators.py` | `keyword_coverage_check` | `baseline_service` |
| `src/llm/fallback.py` | `fallback_for(prompt_name)` | `baseline_service` |
| `src/templates/*.md.j2` | 10 个 Jinja2 模板 | `renderer`（通过 `FileSystemLoader`） |
| `jinja2` | `Environment`、`FileSystemLoader`、`ChainableUndefined` | `renderer` |

外部产物：
- `training_<slug>/00_对象档案.md … 09_边界与止.md`（由 `trainer_service` 落盘到 `training_root`）。
- `data/trainer.db` 中：`trainings`、`baseline_history`、`daily_logs`、`daily_log_tasks`、`review_archives`、`llm_calls`。

## 各服务一览

### 1. `trainer_service.py` — 新建训练编排器

**职责**：端到端执行"主题具体化 → 关键词 → 基线题 → 评分 → 渲染 → 落盘 → 入库 → 历史与预习清单"。
**入口**：`create_training(topic, *, training_root, baseline_answers, daily_minutes, total_weeks) -> DomainTraining`。
**调用关系**：
- 调 `topic_validation.validate_topic`、`keyword_service.generate_keywords`、`baseline_service.generate_baseline_questions`、`scoring_service.score_baseline`、`renderer.render_training_files`、`file_writer.{sanitize_dir_name, check_writable, write_training_directory}`，以及内嵌的 `_generate_pretrain_checklist`（直接走 `complete`）。
- 持久化：经 `src.db.queries` 调 `create_training`、`update_training`、`add_baseline_history`、`record_llm_call`。
**失败处理**：每一步包在 `try/except` 里统一抛 `TrainerCreationError(step, original)`；最终失败时 `_cleanup_dir` 删目录，避免污染文件系统。

### 2. `review_service.py` — 周复盘编排器

**职责**：把"周指标 + LLM 校准"落成新训练状态（`apply` 或 `skip`），并归档。
**入口**：
- `prepare_weekly_review(training_id)`：只算指标 + 提议，不入库。
- `apply_weekly_review(training_id, suggestion)`：写新 baseline/level/schedule/materials、加 history、`current_week += 1`、写 `review_archives(status="confirmed")`。
- `skip_weekly_review(training_id)`：只写 `review_archives(status="skipped")`。
**调用关系**：内部串联 `metrics_calculator.compute_weekly_metrics` 与 `calibration_service.generate_calibration`；持久化走 `src.db.queries.{update_training, add_baseline_history, create_review_archive}`。
**数据流**：`Training` → `WeeklyMetrics` → `CalibrationSuggestion` → 字段合并到 `training.{baseline_score, baseline_level, schedule, materials, current_week, last_review_at, last_active_at}` → `review_archives`。

### 3. `metrics_calculator.py` — 周指标聚合（纯 SQL）

**职责**：基于 `daily_logs` + `daily_log_tasks` 计算 7 天汇总指标。
**入口**：`compute_weekly_metrics(training_id, *, today, week_start) -> WeeklyMetrics`。
**字段**：`training_id`、`week_start/end`、`avg_completion`、`avg_recall_success`、`three_reflection_coverage`、`consecutive_days`、`weakest_topic`、`strongest_topic`、`missed_tasks`、`days_logged`。
**依赖**：只用 `src.db.queries.get_daily_logs_in_range` 与 `src.db.sqlite.get_connection`。**不调 LLM**，便于单测。
**关键算法**：
- 连续天数 = 当前日往前找，直到遇到第一条间隔（`_consecutive_completed`）。
- 弱/强主题：优先 `trainings.materials.units[*].recall_rate`；否则从 `daily_log_tasks.task_ref` 完成率聚合（`_unit_completion_from_daily_tasks` + `_min_max_topics`）。

### 4. `progress_service.py` — 实时面板只读

**职责**：为首页与训练详情页提供"实时 P0"与"两周后的 P1 摘要"，**全部只读**。
**入口**：
- `compute_training_progress(training_id) -> TrainingProgress`
- `compute_home_dashboard() -> HomeDashboard`
- `get_p1_summary(training_id) -> P1Summary`
**依赖**：`src.core.baseline.compute_level`、`src.core.element.{BaselineLevel, TrainingStatus}`、`src.db.queries.{get_daily_logs_in_range, get_training, list_trainings}`、`src.db.sqlite.get_connection`。
**注意**：`_consecutive_days` 与 `metrics_calculator._consecutive_completed` 实现相似但窗口不同（30 天 vs 全部），是两套并存实现。

### 5. `schedule_service.py` — 间隔复习任务抽取

### 4.5 `attempt_service.py` — 作答记录与达标判定（2026-09-21 新增）

`practice_attempts` 是**客观表现的唯一数据源**，也是审计报告 M1（四失无闭环）的修复前提：
没有逐次作答，`signal_service` 的客观一侧永远只能返回"数据不足"。

| 函数 | 作用 |
|---|---|
| `record_attempt(...)` | 写一次作答（`pass` / `fail`），校验题目键与结果枚举 |
| `recent_results(...)` / `recent_training_results(...)` | 取最近 N 次结果（时间正序） |
| `item_mastery(...)` / `training_accuracy(...)` | 单题 / 训练级客观摘要 |
| `objective_for_item(...)` / `objective_for_training(...)` | 供 `signal_service` 的客观通道（<3 次 → `unknown`） |
| `mark_mastered_if_ready(...)` | **唯一的"达标"写入点**：连续 2 次通过 → `training_items.status='passed'` + `mastered_at` |
| `record_and_evaluate(...)` | 记录作答并顺带判定达标，返回是否刚刚达标 |

### 4.6 `quiz_service.py` — 测验取题、判分与回退重练（2026-09-21 新增）

对应 `periodic-assessment` 能力与 ADR-0016。

| 函数 | 作用 |
|---|---|
| `question_pool(...)` | 可抽题池：只取 `question_bank.cooldown_until <= 今天` 的题（冷却期内的近期原题不得进池） |
| `pick_blueprints(pool, size)` | 先保证**知识点覆盖**（每知识点最多一题），再按练过次数补足 |
| `build_questions(blueprints)` | 优先 LLM 生成**变式题**（`quiz_variant`）；不可用时退回冷却期外的原题并标记 `is_variant=0` |
| `start_assessment(...)` | 建测验批次 + 落题（`assessments` / `assessment_items`） |
| `save_answers(...)` / `save_manual_verdicts(...)` | 存作答 / 自评兜底（LLM 判分不可用时，标注来源为自评） |
| `grade_with_llm(...)` | LLM 判分（`quiz_grade`，只出 pass / fail） |
| `finish_assessment(...)` | 结算成绩（通过线 80%）、把测验结果写进 `practice_attempts`、未通过的题**追加补练轮次**（`reason='quiz_failed'`） |
| `pending_quiz_plan(...)` / `latest_assessment(...)` | 今日到期测验 / 最近一次测验（页面用） |

### 4.7 `mastery_service.py` — 阶段达标与任务达标（2026-09-21 新增）

把"练到什么程度算完成"变成确定状态（ADR-0011 + change `training-execution-feedback` 的 5.2 / 5.3）。

| 函数 | 作用 |
|---|---|
| `stage_statuses(...)` | 逐阶段算达标（覆盖模式看必修全 `passed`；达成模式看验收判据，判不了退回覆盖口径） |
| `sync_stages(...)` | **写回** `path_stages.status`：全部达标 → `completed`，第一个未达标 → `active`，其余 `locked`（修掉"阶段永远 locked"的老问题） |
| `training_progress(...)` | 任务达标报告：必修覆盖比例 + 最近一次测验是否通过 |
| `sync_training_status(...)` | 任务达标 → `trainings.status='completed'`（终态） |
| `evaluate(...)` | 一站式：同步阶段状态 → 同步任务状态 → 返回报告（页面进入时调用） |

> ⚠️ 2026-09-20 起，新链路（已有训练路径的训练）由 `plan_service` 接手；
> `schedule_service` 的 `trainings.schedule.units` 分支只服务老训练，属 legacy。

**职责**：把 `training.schedule.units` 解析成"今日复习项 + 新内容项"。
**入口**：`extract_today_tasks(training_id, today) -> TodayTasks`、`interval_for_index(idx)`、`next_review_date(last_reviewed, idx)`。
**关键常量**：`STANDARD_INTERVALS = [1, 3, 7, 15, 30]`、`_MAX_NEW_ITEMS_PER_DAY = 3`、`_DAY_BUCKETS = {"first_review":1,...}`（后者为兼容用的字典）。
**降级**：找不到 unit 时返回 1 个 `TaskItem(task_id="N1", topic="今日训练 (待初始化)")` 占位。
**对外被调**：`recall_service` 调用 `interval_for_index` 做 due 判断。

### 6. `recall_service.py` — 主动回忆题抽取

**职责**：从 `training.materials.recall_units` 按 due date 筛选 + 按 `ContentDimension` 比例轮询出今日回忆题（默认最多 5 道）。
**入口**：`get_today_recall_questions(training_id, today, *, max_questions=5) -> list[RecallQuestion]`。
**依赖**：`src.core.content_dim.{ContentDimension, DEFAULT_DAILY_RATIO, distribute_by_ratio}`、`src.db.queries.get_training`、`schedule_service.interval_for_index`。
**降级**：缺 unit 或缺队列时返回 `[]`，由 UI 兜底。

### 7. `daily_log_service.py` — 日卡写操作

**职责**：勾选任务、提交三省、累计回忆题结果、回读今日进度。
**入口**：
- `check_task(training_id, task_id, completed, *, today) -> TaskCheckResult`
- `submit_reflections(training_id, loyal_to_goal, method_effective, applied_to_practice, *, today) -> ReflectionResult`
- `record_recall_results(training_id, results, *, today)`
- `get_today_progress(training_id, today) -> DailyProgress`
**依赖**：`src.db.queries.{get_or_create_daily_log, update_daily_log_progress, update_training, submit_three_reflections}`、`src.db.sqlite.get_connection`。
**数据流**：UI 勾选 → upsert daily_log_tasks → 重算 completed_count/total_tasks → update_daily_log_progress → bump `trainings.last_active_at`。
**约定**：`task_id` 首字母 `R` 为复习、`N` 为新（其他默认 `new`），用于 daily_log_tasks.task_type 列。

### 8. `file_writer.py` — 文件系统写入器

**职责**：训练目录安全命名 + 原子写入。
**入口**：
- `sanitize_dir_name(topic) -> str`（输出 `training_<slug>/`）
- `write_training_directory(base_dir, dir_name, files) -> Path`
- `check_writable(path) -> bool`
**实现要点**：
- 目录权限 0o755，文件 0o644；先写到 `*.tmp`，再 `os.replace` 原子替换。
- 失败时清理遗留 `.tmp`，再抛原异常。
- slug 规则：替换 `\/:*?"<>|\s` → `_`；合并相邻 `_`；去首尾 `_`；截 60 字符；前缀 `training_`。

### 9. `renderer.py` — 10 份 Markdown 渲染

**职责**：用 Jinja2 把"渲染上下文字典"渲染成 10 份 Markdown。
**入口**：`render_training_files(context: Mapping) -> dict[str, str]`。
**常量**：`00_对象档案`、`01_基线诊断`、`02_训练目标`、`03_资料库`、`04_复习日历`、`05_主动回忆题`、`06_环境配置`、`07_奖励机制`、`08_每日反省`、`09_边界与止`。
**环境**：Jinja2 `ChainableUndefined` + `autoescape=False` + `keep_trailing_newline=True`，模板目录 `src/templates/`（与本目录同级的父目录 `src/templates/`）。
**完全无副作用**：纯渲染，零 IO，被 `trainer_service` 调用后再交给 `file_writer` 写盘。

### 10. `calibration_service.py` — 周度校准（LLM + 启发式回退）

**职责**：周复盘的"调整方案"生成器。
**入口**：`generate_calibration(training, metrics) -> CalibrationSuggestion`。
**字段**：`baseline_score_delta`（±0.5 钳位）、`schedule_adjustment`（dict）、`material_recommendations`（list of dict）、`reward_refresh`、`next_week_focus`、`raw`、`fallback_used`。
**回退**：LLM 抛错或输出不可解析时，调 `_heuristic_suggestion`：基于 `avg_recall_success < 0.7` 决定"降低密度"/"维持"，写 `raw.source = "heuristic_fallback"`。
**审计**：成功 / 失败都会写 `llm_calls`（`call_purpose="weekly_calibration"`）。

### 11. `baseline_service.py` — 基线诊断题生成（LLM + 关键词覆盖校验）

**职责**：根据关键词白名单生成 3 道基线诊断题。
**入口**：`generate_baseline_questions(topic, keywords, must_cover_count, forbidden) -> BaselineQuestions`。
**算法**：最多 `_MAX_ATTEMPTS=3` 次调 `complete("baseline_q")` → 每轮做 `keyword_coverage_check` → 不通过则重发；用尽取 `fallback_for("baseline_q")` 并设 `fallback_used=True`。
**审计**：每轮调用都写 `llm_calls`（`call_purpose="baseline_q"`）。

### 12. `scoring_service.py` — 基线答案评分（LLM + 启发式回退）

**职责**：对用户的 3 道基线答案打标（`mastered`/`partial`/`missing`）+ 汇总 `overall_level`（`high`/`mid`/`low`）。
**入口**：`score_baseline(topic, questions, user_answers) -> ScoringResult`。
**回退**：LLM 失败时走 `_heuristic_score`：用问题题干里的关键 token（>2 字符）做轻量重叠匹配判定是否"实质回答"；再按实质回答条数算 overall。
**审计**：成功写一条 `llm_calls`（`call_purpose="baseline_scoring"`）；失败写一条 `validation_result="fail"` + `failure_reason`。

### 13. `keyword_service.py` — 关键词白名单生成（LLM）

**职责**：根据主题生成 `keywords`、`must_cover_count`、`forbidden`。
**入口**：`generate_keywords(topic, *, training_root=".") -> KeywordResult`。
**回退**：LLM 不可用 → 兜底用 `topic.split()[0]` 当唯一种子，关键词长度为 1。
**审计**：成功与失败都写 `llm_calls`（`call_purpose="keyword_generation"`）。

### 14. `topic_validation.py` — 主题具体性判定（LLM，fail-open）

**职责**：判断 `topic` 是否足够具体可训练。
**入口**：`validate_topic(topic) -> TopicValidationResult`。
**特殊策略**：LLM 不可用时 **fail-open** —— 返回 `is_valid=True` + `reason="LLM unavailable, skipping validation"`，**不**阻塞用户。
**审计**：成功与失败都写 `llm_calls`（`call_purpose="topic_validation"`）；是所有 LLM 子服务里唯一对失败采用 fail-open 的。

## 调用关系总图

```
src/ui/
  ├─ 新建训练 ─────────► trainer_service.create_training
  │                        ├─► topic_validation.validate_topic
  │                        ├─► keyword_service.generate_keywords
  │                        ├─► baseline_service.generate_baseline_questions ── (fallback_for)
  │                        ├─► scoring_service.score_baseline
  │                        ├─► renderer.render_training_files  ◄── src/templates/*.md.j2
  │                        ├─► file_writer.{sanitize_dir_name, check_writable, write_training_directory}
  │                        └─► db.queries.{create_training, update_training, add_baseline_history, record_llm_call}
  │
  ├─ 周复盘 ───────────► review_service
  │                        ├─► metrics_calculator.compute_weekly_metrics
  │                        ├─► calibration_service.generate_calibration
  │                        └─► db.queries.{update_training, add_baseline_history, create_review_archive}
  │
  ├─ 每日卡片（读）─────► schedule_service.extract_today_tasks
  │                        └─► recall_service.get_today_recall_questions
  │                            └─► schedule_service.interval_for_index
  ├─ 每日卡片（写）─────► daily_log_service
  │                        └─► db.queries.{get_or_create_daily_log, update_daily_log_progress,
  │                                        update_training, submit_three_reflections}
  │
  └─ 面板 ─────────────► progress_service.{compute_training_progress, compute_home_dashboard,
  │                                   get_p1_summary}
  │                        └─► core.{compute_level, BaselineLevel, TrainingStatus}

LLM 子服务统一模式（keyword/baseline_scoring/baseline_q/topic_validation/weekly_calibration/pretrain_checklist）：
    complete(prompt_name, variables)
        ├─ 解析 output_json
        ├─ 归一化 / 回退
        └─ record_llm_call(...)
```

## 数据契约（核心 dataclass）

| 服务 | 输出 dataclass | 关键字段 |
|---|---|---|
| keyword_service | `KeywordResult` | `keywords`、`must_cover_count`、`forbidden`、`raw` |
| baseline_service | `BaselineQuestions` | `questions: list[BaselineQuestion]`、`fallback_used` |
| baseline_service | `BaselineQuestion` | `dimension`、`difficulty`、`question`、`reference_answer` |
| scoring_service | `ScoringResult` | `scores[QuestionScore]`、`overall_level`、`partial_topics` |
| calibration_service | `CalibrationSuggestion` | `baseline_score_delta`、`schedule_adjustment`、`material_recommendations`、`reward_refresh`、`next_week_focus`、`fallback_used` |
| topic_validation | `TopicValidationResult` | `is_valid`、`suggestions`、`reason` |
| metrics_calculator | `WeeklyMetrics` | 7 天聚合 + `weakest_topic`、`strongest_topic`、`missed_tasks` |
| progress_service | `TrainingProgress` | `topic`、`baseline_score/level`、`consecutive_days`、`today_completion`、`current_week` |
| progress_service | `HomeDashboard` | `trainings`、`total_active`、`total_all`、`avg_baseline` |
| progress_service | `P1Summary` | `has_enough_data`、`baseline_history_points`、`recall_rates` |
| schedule_service | `TodayTasks` | `today`、`review_items`、`new_items` |
| schedule_service | `TaskItem` | `task_id`、`topic`、`dimension`、`source`、`is_required` |
| recall_service | `RecallQuestion` | `qid`、`unit`、`dimension`、`question`、`reference` |
| daily_log_service | `TaskCheckResult` | `task_id`、`completed`、`completed_at` |
| daily_log_service | `ReflectionResult` | `submitted_at`、`reflections` |
| daily_log_service | `DailyProgress` | `log_id`、`total_tasks`、`completed_count`、`recall_*`、`reflection_submitted_at` |
| review_service | `ReviewOutcome` | `metrics`、`suggestion`、`applied` |

## 风险与注意

- `daily_log_service.record_recall_results` 是**累加**而非覆盖：多次调用会持续累加 `recall_questions_total/correct`，UI 调用需谨慎。
- `metrics_calculator._consecutive_completed` 与 `progress_service._consecutive_days` 是**两套**独立实现（窗口/算法细节略有差异）；修改一处记得同步另一处。
- `trainer_service.create_training` 失败会 `_cleanup_dir` 删除目录；但已写入 `trainings` 行后失败时不会回滚 DB（属于已知权衡）。
- LLM 子服务中只有 `topic_validation` 在 LLM 不可用时**保持流程通过**；其他都会进入回退或兜底路径。
- `renderer` 完全无副作用，是纯函数；任何渲染相关 bug 应优先在这里复现与修复。
