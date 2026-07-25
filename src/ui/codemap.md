# src/ui/

> Streamlit 页面层。5 个页面模块全部对外只暴露 `render()` 入口，由 `src/main.py` 按 `?page=` 查询参数统一路由。本层只做"装载-展示-触发服务"，不直接访问数据库、不直接调用 LLM。

## 目录职责

`src/ui/` 是 Streamlit 应用的"视图层"。它的全部职责是：

1. 从 `st.query_params` 解析当前页与训练 ID。
2. 调用 `src/services/*` 内的服务聚合数据（dashboard、progress、metrics、suggestion 等）。
3. 把数据用 `st.*` 控件绘制出来，并把用户的输入/点击回写给服务层。
4. 在 `st.session_state` 中维护向导式多步状态（如新建训练的第几步）。

目录内 5 个文件互不依赖，全部为平行模块，由 `main.py` 路由；`__init__.py` 为空。

| 文件 | 渲染的页面 | `?page=` 值 | 是否需要 `?training_id=` |
|---|---|---|---|
| `page_home.py` | 首页 | `home`（默认） | 不需要 |
| `page_new_training.py` | 新建训练向导（4 步） | `new_training` | 不需要 |
| `page_training.py` | 训练详情 | `detail` | 需要 |
| `page_daily.py` | 今日任务卡 | `daily` | 需要 |
| `page_review.py` | 周复盘简报 | `review` | 需要 |

## 路由总览

```
src/main.py:main()
  ├─ _register_pages()      延迟导入 5 个 render
  ├─ read ?page=            默认 "home"
  └─ PAGES[page]()
        ├─ "home"          → page_home.render()
        ├─ "new_training"  → page_new_training.render()
        ├─ "detail"        → page_training.render()  需 ?training_id
        ├─ "daily"         → page_daily.render()     需 ?training_id
        ├─ "review"        → page_review.render()    需 ?training_id
        └─ 未知 → 弹 warning，重置为 "home"
```

所有页面跳转均通过 `st.query_params["page"] = ...` + `st.rerun()` 完成，没有用 `st.switch_page` / `st.navigation`。

---

## 1. `page_home.py` — 首页

### 职责
- 营销/导览区（hero 三栏说明「十要素闭环训练」）。
- 三个汇总指标：训练主题总数、活跃训练数、平均基线评分。
- 训练列表（DataFrame，带状态徽章、基线进度条、连续打卡、今日完成度、坚持天数、最近活跃）。
- 列表为空时显示空状态 CTA；列表非空时提供 selectbox + 「进入训练 →」按钮。
- 列表底部额外的「➕ 新建训练」按钮。

### 交互流程
```
render()
  ├─ _render_hero()             静态标题 + 三栏说明
  ├─ compute_home_dashboard()   调用服务聚合所有训练进度
  ├─ _render_metrics()          3 列 st.metric
  ├─ _render_training_list()    空？→ _render_empty_state()
  │                              否则 DataFrame + selectbox + 进入按钮
  └─ _render_new_training_cta() 列表底部的「➕ 新建训练」按钮
```

跳转行为：
- 空状态 CTA / 底部 CTA：写 `st.query_params["page"] = "new_training"`。
- 列表选中后点「进入训练 →」：写 `st.query_params["page"] = "detail"` 与 `st.query_params["training_id"] = str(id)`。

### 依赖服务
- `src.services.progress_service.compute_home_dashboard` → 返回 `HomeDashboard`，含 `total_all` / `total_active` / `avg_baseline` / `trainings: list[TrainingProgress]`。
- `src.core.element.TrainingStatus`（用于状态徽章映射）。

### Streamlit 状态
- **几乎不用** `st.session_state`（仅读取 `st.query_params`）。
- 自维护常量：`_STATUS_BADGE`（状态 → emoji 文本）、`_format_relative`（最近活跃时间相对显示）。
- 唯一可见的 selectbox 控件：`key="hm_select_training"`，但**选中值不写入 session_state**（仅用来生成按钮 click 的跳转）。

### 导航
- 出：`new_training`（CTA）、`detail`（列表进入）。

---

## 2. `page_new_training.py` — 新建训练向导（4 步）

### 职责
引导用户完成"主题 → 关键词白名单 → 基线诊断 → 完成"四步表单，全程调用 LLM 服务逐步产出可保存的训练。

### 4 步流程

| Step | `_render_*` | 输入 | 触发的服务 | 写入的 session_state |
|---|---|---|---|---|
| 1 | `_render_step1` | 训练主题文本 | `validate_topic(topic)` | `nt_topic`, `nt_validation` |
| 2 | `_render_step2` | 编辑关键词/禁止词/必覆盖数 | `generate_keywords(topic)`（首次进入自动） | `nt_keywords`, `nt_keywords_input`, `nt_forbidden_input`, `nt_must_cover_count` |
| 3 | `_render_step3` | 3 道基线题答案 | `generate_baseline_questions(...)`（首次进入自动） + `create_training(...)` | `nt_questions`, `nt_answers`, `nt_result`, `nt_training_id`, `nt_error` |
| 4 | `_render_step4` | （只读展示） | — | — |

### 交互流程
```
render()
  ├─ _maybe_redirect()          若 URL 已有 ?training_id，提示并 stop
  ├─ _init_state()              缺省注入 12 个 nt_* 键
  ├─ read nt_step (1..4)
  └─ dispatch step
        ├─ 1 → _render_step1
        ├─ 2 → _render_step2
        ├─ 3 → _render_step3
        └─ 4 → _render_step4
```

- Step 1：「✅ 校验主题」按钮 → `validate_topic()`。`is_valid` → 弹 success + 「下一步」；否则弹错误 + 建议列表。
- Step 2：首次进入时 `_render_step2` 检测 `nt_keywords is None` 自动调用 `generate_keywords()` 并 `st.rerun()`。用户可编辑关键词/禁止词/必覆盖数；「下一步」把编辑结果重新封装成 `KeywordResult` 写入。
- Step 3：`_ensure_questions()` 同样惰性生成 3 道题；用户填答案后「提交」调用 `create_training(topic, baseline_answers)`，捕 `TrainerCreationError` 区分失败阶段。
- Step 4：展示训练结果（基线档位、评分、补强项、预训练清单、目录路径、ID、状态），提供「查看训练详情 →」（直接写 `training_id` query param，由 `main.py` 路由到 `detail`）与「再创建一个训练」（`_reset_state()` 清空 12 个 `nt_*` 键）。

### 依赖服务
- `src.services.topic_validation.validate_topic`（Step 1，LLM 校验）。
- `src.services.keyword_service.generate_keywords`（Step 2，LLM 生成 keyword white-list）。
- `src.services.baseline_service.generate_baseline_questions`（Step 3，LLM 生成 3 题）。
- `src.services.trainer_service.create_training`（Step 3 提交，**编排服务**：评分基线 + 生成 10 份 md + 写库）。
- `src.services.baseline_service.BaselineQuestions`、`src.services.keyword_service.KeywordResult`（类型）。

### Streamlit 状态（专属 ns：`nt_*`）
| 键 | 类型 | 用途 |
|---|---|---|
| `nt_step` | int 1..4 | 当前步骤 |
| `nt_topic` | str | 已 strip 的主题 |
| `nt_validation` | ValidationResult \| None | Step 1 校验结果 |
| `nt_keywords` | KeywordResult \| None | Step 2 关键词 |
| `nt_keywords_input` / `nt_forbidden_input` | str | 文本编辑缓冲 |
| `nt_must_cover_count` | int | 每题覆盖词数 |
| `nt_questions` | BaselineQuestions \| None | 3 道基线题 |
| `nt_answers` | list[str] | 答案 |
| `nt_result` | Training \| None | Step 3 创建的训练对象 |
| `nt_training_id` | int \| None | 同上取 id |
| `nt_error` | Exception \| None | 最近一次失败 |

辅助函数：`_init_state`（默认注入）、`_reset_state`（清空全部）。

### 导航
- Step 4 → 详情页：写 `st.query_params["training_id"] = str(training.id)`（页码由 `main.py` 默认路由到 `detail`）。
- `_maybe_redirect`：若 URL 已带 `?training_id`，提示并提供「前往训练详情」按钮，避免用户在新 URL 打开新建训练页时混淆。
- 失败回退：Step 2/3 检测 LLM 失败时弹 `← 返回` 按钮回退到上一步。

---

## 3. `page_training.py` — 训练详情

### 职责
展示单条训练的全景视图：P0 进展指标 + 快捷入口 + P1 趋势 + 最近三省 + 历史复盘，并承担"导航中枢"角色（去往今日训练 / 周复盘）。

### 交互流程
```
render()
  ├─ _resolve_training_id()     解析 ?training_id=
  │      ├─ None → _render_no_training()（提供下拉选择或新建跳转）
  │      └─ 找到 → get_training(id)
  │              ├─ None → _render_no_training()（含报错）
  │              └─ 找到 → compute_training_progress(id)
  │                              └─ _render_training(training, progress)
                                        ├─ _render_header        标题 + 状态徽章 + 返回首页
                                        ├─ _render_p0_metrics    3+2 个 metric + 进度条
                                        ├─ _render_links         快捷入口三按钮 + 目录
                                        ├─ _render_p1_section    趋势线（>=14天才有）
                                        ├─ _render_p2_placeholder 折叠占位
                                        ├─ _render_three_reflections  近 14 天最近一次三省
                                        └─ _render_review_history     历史复盘卡片
```

### 依赖服务
- `src.db.queries.get_training` / `list_trainings` / `get_daily_logs_in_range` / `get_reviews_by_training`（DB 直读）。
- `src.services.progress_service.compute_training_progress`（P0 聚合）。
- `src.services.progress_service.get_p1_summary`（P1 趋势）。

### Streamlit 状态
- **基本不用**。只在 selectbox 控件（`_render_no_training` 中 `key="td_pick_training"`）上记录用户选择。
- 自维护常量：`_REFLECTION_TITLES` / `_REFLECTION_KEYS`（三省标题与字段映射）、`_P1_MIN_DAYS = 14`、`_RECALL_WINDOW_DAYS = 7`（虽然未直接使用但语义占位）。

### 导航
- 顶部「← 返回首页」：删除 `training_id` / `page` 写 `page=home`。
- 快捷入口「📅 今日训练」→ `page=daily`（保留 `training_id`）。
- 快捷入口「🔄 周复盘」→ `page=review`（保留 `training_id`）。
- 快捷入口「✏️ 编辑」→ `disabled=True`（P2 占位）。

### 关键计算
- P0 指标：基线评分、连续打卡、今日完成度（带 bar）、坚持天数、当前周。
- P1 指标：`<14 天` 显示"数据收集中，再练 N 天可见趋势"；`≥14 天` 渲染两条 `st.line_chart`（基线升级曲线 + 7 天回忆题正确率）。
- 历史复盘：每条 review 一个折叠 expander，JSON 字段（metrics / llm_suggestions）反序列化后用 `st.json` 展示。

---

## 4. `page_daily.py` — 今日任务卡

### 职责
用户每日打卡入口。按"训练十要素"中的 6 块布局：

1. **复习项**（review_items，可勾选完成）
2. **新学项**（new_items，可勾选完成）
3. **主动回忆题**（recall questions，答对/答错两按钮）
4. **三省**（3 段 text_area + 保存按钮）
5. **完成度**（st.progress + metric + 回忆题正确率 metric）
6. **奖励领取**（全部完成 + 三省已提交 → 🎁 按钮 + balloons）

### 交互流程
```
render()
  ├─ 解析 ?training_id=
  │      ├─ 无 → _render_no_training()（仅 active 训练下拉）
  │      └─ 有 → get_training(id)
  │              ├─ None → _render_no_training()
  │              └─ 找到 → _render_training(training)
                                    ├─ _training_header        3 列 metric
                                    ├─ get_today_progress(id)  当日完成进度
                                    ├─ extract_today_tasks(id) 复习/新学任务
                                    ├─ get_today_recall_questions(id)
                                    ├─ _render_review_section
                                    ├─ _render_new_section
                                    ├─ _render_recall_section
                                    ├─ _render_reflections_section
                                    ├─ _render_progress_section
                                    └─ _render_reward_section
```

### 关键交互
- **任务勾选**：`_render_task_checkbox` 用 `st.checkbox` 渲染；变更时调用 `check_task(training_id, task_id, new_value)` 写库，同时把结果写回 `dl_state_{training_id}_{task_id}` 并 `st.rerun()`。
- **回忆题**：每题两个按钮 ✓/✗，调用 `record_recall_results(training_id, {qid: True/False})`；结果写 `dl_recall_grade_{training_id}_{qid}`；点过之后展示参考答案折叠与成功/警告 banner。
- **三省**：3 个 `text_area` + 「保存三省」按钮 → `submit_reflections(training_id, loyal, method, applied)`。
- **奖励**：当 `completed_count == total_tasks` 且 `reflection_submitted_at` 非空时显示「🎁 领取今日奖励」按钮（仅 balloons + 文案提示，未实际写入 service）。

### 依赖服务
- `src.db.queries.get_training` / `list_trainings`（仅 status=active）。
- `src.services.daily_log_service.get_today_progress` / `check_task` / `record_recall_results` / `submit_reflections`。
- `src.services.recall_service.get_today_recall_questions`（返回 `list[RecallQuestion]`）。
- `src.services.schedule_service.extract_today_tasks`（返回 `TaskItem` 列表，区分 review_items / new_items）。
- `src.core.content_dim.ContentDimension`（用于维度 emoji 标签）。

### Streamlit 状态
本页面是 5 个页面里 **session_state 使用最重** 的：

| 键模式 | 用途 |
|---|---|
| `dl_state_{training_id}_{task_id}` | bool，任务当前完成状态（默认取持久化值） |
| `dl_chk_{training_id}_{task_id}` | checkbox 控件 key |
| `dl_recall_answer_{training_id}_{qid}` | 回忆题答题文本（暂未提交） |
| `dl_recall_grade_{training_id}_{qid}` | True / False / 缺失 |
| `dl_recall_ok_{training_id}_{qid}` / `dl_recall_no_…` | 按钮 key |
| `dl_ref_loyal_{training_id}` / `dl_ref_method_…` / `dl_ref_applied_…` | 三省文本 |
| `dl_save_ref_{training_id}` | 保存三省按钮 key |
| `dl_reward_{training_id}` | 奖励按钮 key |
| `dl_training_select` | 无训练时下拉 key |

> 所有按 `training_id` 命名的键在切换训练时**不会自动清理**——切换训练后旧键依然存在（Streamlit 行为），这意味着切换训练后旧训练的勾选状态不会泄漏给当前训练（因为 key 不一致）。

### 导航
- 无训练时：「选择训练」下拉 + 「进入训练」按钮写 `training_id` 后 reload 进入同一页。
- 其它页面跳转：仅依赖 `?page=` 由 `main.py` 切换（首页"今日训练"按钮 → `page=daily`）。

---

## 5. `page_review.py` — 周复盘简报

### 职责
把本周机械指标 + LLM 校准建议可视化，并提供「✅ 确认校准」/「⏭️ 跳过」两个动作，最终写入 `review_service` 完成闭环。

### 交互流程
```
render()
  ├─ _resolve_training_id()
  │      ├─ None → _render_no_training()
  │      └─ 有 → get_training(id)
  │              ├─ None → _render_no_training()
  │              └─ 找到 → 切换检测：
  │                         若 session_state[_TRAINING_ID_KEY] != training_id
  │                         → 清空 _OUTCOME_KEY / _PREPARED_FLAG_KEY
  │                         → 写入 _TRAINING_ID_KEY
  │              └─ _render_training(training)
                          ├─ _training_header
                          ├─ 「🔄 开始本周复盘」按钮
                          │     → 置 _PREPARED_FLAG_KEY = True
                          │     → 清 _OUTCOME_KEY
                          ├─ 若已 prepare 但没有 outcome：
                          │     with spinner: prepare_weekly_review(id)
                          │     → 写 _OUTCOME_KEY
                          ├─ 若 outcome 存在：
                          │     ├─ _render_metrics_section      7 个 metric（2 列网格）
                          │     ├─ _render_suggestion_section   delta + 计划调整表 + 资料增减表 + 奖励/下周重点
                          │     └─ _render_actions_section      确认 / 跳过
                          └─ 确认 → apply_weekly_review(id, outcome.suggestion); 写库; 清 outcome/prepared
                              跳过 → skip_weekly_review(id); 清 outcome/prepared
```

### 依赖服务
- `src.db.queries.get_training` / `list_trainings`。
- `src.services.review_service.prepare_weekly_review`（机械计算 + LLM 校准，**返回 `ReviewOutcome`**——含 `metrics: WeeklyMetrics` + `suggestion: CalibrationSuggestion`）。
- `src.services.review_service.apply_weekly_review`（确认校准写库）。
- `src.services.review_service.skip_weekly_review`（跳过写库）。
- `src.services.calibration_service.CalibrationSuggestion` / `src.services.metrics_calculator.WeeklyMetrics`（DTO）。

### Streamlit 状态
仅 3 个键：

| 键 | 用途 |
|---|---|
| `_TRAINING_ID_KEY = "rv_training_id"` | 当前 review 训练 id（用于切换训练时清缓存） |
| `_OUTCOME_KEY = "rv_outcome"` | `ReviewOutcome` 缓存，避免重复调用 LLM |
| `_PREPARED_FLAG_KEY = "rv_prepared"` | bool，用户是否点击了"开始本周复盘" |

### 导航
- 无训练时：下拉选择 + 「进入训练」按钮（与 daily/training 同模式）。
- 其它页面跳转：依赖 `main.py` 路由控制。

### 关键设计
- **outcome 缓存**：一旦 `prepare_weekly_review` 成功，结果写到 `_OUTCOME_KEY`，后续 rerun/切换都为同一训练保留，避免重复调用 LLM。
- **切换训练清理**：比较 `rv_training_id` 与当前 id，不一致就清掉 outcome 与 prepared，确保不会把 A 训练的建议误用到 B 训练。
- **失败兜底**：所有服务调用都 `try/except` + `logger.exception` + `st.error`，不向用户暴露 stack trace（除 `pragma: no cover` 注释外）。

---

## 跨页面共性

### 路由与跳转
- 全部页面跳转通过 `st.query_params["page"] = ...` + `st.rerun()`，由 `src/main.py` 统一分发。
- 没有 `st.navigation` / `st.page_link`，侧边栏也没有自定义链接。
- 任何子页面都把 `?training_id=` 当作"当前操作的训练"上下文。

### 公共反序列化
- `page_training.py` 与 `page_review.py` 都对 JSON 字符串字段（`three_reflections`、`metrics`、`llm_suggestions`）做 `json.loads` 容错，失败时回退到原文/占位。

### Streamlit 状态隔离
- `page_new_training` 用 `nt_*` 命名空间隔离向导状态。
- `page_daily` 用 `dl_*` 命名空间隔离当日交互状态（task / recall / reflection）。
- `page_review` 用 `rv_*` 命名空间隔离复盘 outcome 缓存。
- `page_home` / `page_training` 几乎不持久化状态，依赖 `?page=` + `?training_id=` 重建。

### 错误处理
- Wizard / 多步表单：`try/except` + 写 `nt_error` / `st.error` + 「返回上一步」按钮。
- 详情/复盘：服务抛错直接 `st.error` + `logger.exception`，不打断页面其它区块。

### 不直接做的事
- UI 层**不直接**调用 `src.db.sqlite` / `src.db.queries`（只有 `page_training` / `page_daily` / `page_review` 引用 `queries` 用于主键直查，集中在 `_render_no_training` / `_render_training` 入口）。
- UI 层**不直接**调用 LLM 客户端（所有 LLM 调用都在 service 内部）。
- UI 层**不写 schema**（由 `main.py` 启动时 `init_db()` 兜底）。

## 关键术语速查

| 术语 | 含义 |
|---|---|
| P0 指标 | 基线评分 / 连续打卡 / 今日完成度 / 坚持天数 / 当前周（详情页基础模块） |
| P1 指标 | 基线升级曲线 + 7 天回忆题正确率（≥14 天数据才显示） |
| P2 指标 | 阶段目标 / 三省覆盖率（当前折叠占位） |
| nt_* | page_new_training 的 session_state 命名空间 |
| dl_* | page_daily 的 session_state 命名空间 |
| rv_* | page_review 的 session_state 命名空间 |
| HomeDashboard | 首页聚合 DTO，含 `total_all` / `total_active` / `avg_baseline` / `trainings` |
| TrainingProgress | 单条训练进度 DTO |
| ReviewOutcome | 周复盘产物：`{ metrics: WeeklyMetrics, suggestion: CalibrationSuggestion }` |
| CalibrationSuggestion | LLM 校准建议：`baseline_score_delta` / `schedule_adjustment` / `material_recommendations` / `reward_refresh` / `next_week_focus` |
