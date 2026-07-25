# personal_trainer_agent/ · 仓库地图（Repository Atlas）

> 本文件是仓库的"总览图"，告诉新同学三件事：
> 1. 这个项目**做什么**（业务目标 + 闭环）；
> 2. **从哪进**（入口与起手命令）；
> 3. **代码怎么分**（目录职责 + 子地图索引 + 端到端流程）。
>
> 凡是涉及具体模块的内部细节（API、字段、算法），请直接看对应子目录的 `codemap.md`，本文件不做重复。

---

## 1. 项目定位与业务目标

**Personal Trainer Agent** 是一个自用的"训练教练"本地应用，核心理论是《训练之道·十要素完整闭环 v3》与《学习的本质》。它把训练理论落成可执行的本地网页：

- 支持"**新建训练 → 日常执行 → 周复盘校准**"完整闭环；
- 所有 LLM 调用可追溯（写入 `llm_calls` 表），所有训练文件可落盘（写到 `training_<主题>/` 目录）；
- 跑得通 ⇒ 用户能跟着练；看得见 ⇒ 用户能看见自己的轨迹。

**MVP 范围**：仅"人"为训练对象，单用户，Streamlit 单页应用。LLM 默认走 DeepSeek（也兼容 OpenAI Chat Completions 协议的其他端点）。

---

## 2. 入口与起手命令

| 入口类型 | 命令 | 用途 |
|---|---|---|
| **Web 入口** | `uv run streamlit run src/main.py` | 启动多页 Streamlit UI（按 `?page=` 路由） |
| **CLI 入口** | `uv run python -m src.cli init-db` | 初始化 SQLite 库（创建全部表） |
| **依赖安装** | `uv pip install -r requirements.txt` | 安装依赖（uv 自动管理 `.venv`） |
| **环境配置** | 复制 `.env.example` → `.env` 后填 `DEEPSEEK_API_KEY` | 注入 LLM 凭据 |

启动后浏览器打开 `http://localhost:8501`，URL 上的 `?page=` 取值决定渲染哪个页面：

| `?page=` | 渲染器 | `?training_id=` |
|---|---|---|
| `home`（默认） | `src/ui/page_home.py` | 不需要 |
| `new_training` | `src/ui/page_new_training.py` | 不需要 |
| `detail` | `src/ui/page_training.py` | 需要 |
| `daily` | `src/ui/page_daily.py` | 需要 |
| `review` | `src/ui/page_review.py` | 需要 |

---

## 3. 目录职责表

| 路径 | 职责 | 子地图 |
|---|---|---|
| `src/main.py` | Streamlit 入口；按 `?page=` 把请求分派给 5 个 `page_*` 渲染器 | [`src/codemap.md`](src/codemap.md) |
| `src/config.py` | 路径常量（`PROJECT_ROOT` / `WORKSPACE_DIR` / `DB_PATH` / `TEMPLATES_DIR`…）+ `load_system_prompt()` 热加载 | [`src/codemap.md`](src/codemap.md) |
| `src/logger.py` | 基于 Rich 的 `AgentLogger`，thought/action/observation 风格流式日志（主要被早期代码使用） | [`src/codemap.md`](src/codemap.md) |
| `src/models.py` | **Pydantic** 写的领域模型（`UserProfile` / `DiagnosisQuestion` / `BaselineResult` / `TrainingSession`）；当前主要服务层已切到 `src.core` 数据类 | [`src/codemap.md`](src/codemap.md) |
| `src/storage.py` | 早期 SQLite 持久化（`sessions` / `baselines` 两表），**已被 `src/db/` 子目录取代**——上层不应再依赖 | [`src/codemap.md`](src/codemap.md) |
| `src/diagnoser.py` | 基于关键词的诊断题 + 规则评分（v0.1 早期路径） | [`src/codemap.md`](src/codemap.md) |
| `src/generator.py` | Python f-string 拼装 5 份 Markdown（早期路径；当前生产路径走 `src/services/renderer.py` + Jinja2 模板） | [`src/codemap.md`](src/codemap.md) |
| `src/core/` | 纯领域层：十要素 / 训练状态 / 基线档位 / 内容维度 / 比例分配等**无副作用**原语 | [`src/core/codemap.md`](src/core/codemap.md) |
| `src/db/` | 持久化层：SQLite 连接 + `tables.sql` DDL + `@dataclass` 行模型 + 查询函数 | [`src/db/codemap.md`](src/db/codemap.md) |
| `src/llm/` | LLM 统一入口：`client.complete()` + prompts / schema / validators / retry / fallback | [`src/llm/codemap.md`](src/llm/codemap.md) |
| `src/services/` | 业务编排层：14 个服务把底层原语组装成端到端业务流程（新建训练、周复盘、每日任务卡、面板） | [`src/services/codemap.md`](src/services/codemap.md) |
| `src/ui/` | Streamlit 视图层：5 个 `page_*.py` 平行模块，**只渲染不直访 DB / LLM** | [`src/ui/codemap.md`](src/ui/codemap.md) |
| `src/templates/` | 10 份 Jinja2 模板（`00_对象档案.md.j2` … `09_边界与止.md.j2`），被 `renderer.py` 渲染 | （在 `src/services/codemap.md` "Integration" 章节） |
| `src/cli/` | CLI 入口：仅 `init-db` 一个子命令 | [`src/cli/codemap.md`](src/cli/codemap.md) |
| `data/trainer.db` | SQLite 库（不入 git，含 6 张表 + 4 个索引） | — |
| `prompts/system_prompt.txt` | System Prompt 落盘文件；首次启动由 `config.load_system_prompt()` 写入默认值 | — |
| `logs/agent_<session>.log` | `AgentLogger` 日志文件落点 | — |
| `workspace/training_<slug>/` | 每主题一个目录，10 份 Markdown 训练文件 | — |
| `docs/` | 理论参考 + 架构文档（`architecture.md`） | — |
| `scripts/` | 端到端 / Harness smoke / LLM logs 检查等脚本 | — |
| `tests/` | 单元测试 | — |
| `workspace/record/` | 变更日志（每次重大更新必写） | — |
| `workspace/store/` | OpenSpec store（id=`store`） | — |
| `.opencode/` | OpenCode skills/commands；**禁止移动** | — |

---

## 4. 分层架构速览

```
┌────────────────────────────────────────────────┐
│  UI 层        src/ui/        (5 个 page_*.py)   │
├────────────────────────────────────────────────┤
│  业务编排层   src/services/  (14 个 service)    │
├────────────────────────────────────────────────┤
│  领域原语层   src/core/      (4 个纯模块)       │
├────────────────────────────────────────────────┤
│  LLM 适配层   src/llm/       (单入口 + 校验)    │
│  持久化层     src/db/        (sqlite + queries) │
├────────────────────────────────────────────────┤
│  数据/产物    data/trainer.db / training_<slug>/│
└────────────────────────────────────────────────┘
```

> 关键约束：**UI 层不直接调用 LLM、也不直接连 DB**；**机械能算的指标不让 LLM 算**；**LLM 输出走 JSON Schema 强约束 + 关键词覆盖率校验**。

---

## 5. 核心端到端流程

### 流程 A：新建训练（4 步向导 → 落盘 10 份 md + 入库）

```
用户在 page_new_training 输入主题
  │
  ├─ Step 1:  topic_validation  (LLM + fail-open)
  ├─ Step 2:  keyword_service.generate_keywords  (LLM)
  ├─ Step 3:  baseline_service.generate_baseline_questions  (LLM + 关键词覆盖校验)
  ├─ Step 3:  scoring_service.score_baseline  (LLM + 启发式回退)
  └─ Step 3:  trainer_service.create_training
                 ├─ renderer.render_training_files  ← src/templates/*.md.j2
                 ├─ file_writer.write_training_directory  (原子写盘)
                 ├─ db.queries.create_training    (INSERT trainings)
                 ├─ db.queries.add_baseline_history
                 └─ 若 baseline_level == "low" → 再生成 pretrain_checklist
```

### 流程 B：每日任务卡（读 → 勾选 → 写）

```
page_daily
  ├─ schedule_service.extract_today_tasks(training_id, today)
  │     ├─ 基于 schedule.units + STANDARD_INTERVALS=[1,3,7,15,30] 判断到期
  │     └─ 新内容上限 _MAX_NEW_ITEMS_PER_DAY=3
  ├─ recall_service.get_today_recall_questions(training_id, today)
  │     └─ 按 ContentDimension + DEFAULT_DAILY_RATIO 轮询分配
  │
  ├─ 用户勾选任务 → daily_log_service.check_task  → upsert daily_log_tasks
  │                              → update_daily_log_progress
  │                              → update_training(last_active_at)
  ├─ 用户答回忆题 → daily_log_service.record_recall_results  (累加)
  └─ 用户提交三省 → daily_log_service.submit_reflections
```

### 流程 C：周复盘（机械指标 + LLM 校准 + 归档）

```
page_review 点 "开始本周复盘"
  ├─ review_service.prepare_weekly_review(id)
  │     ├─ metrics_calculator.compute_weekly_metrics  (纯 SQL 聚合)
  │     │     ├─ avg_completion / avg_recall_success / three_reflection_coverage
  │     │     ├─ consecutive_days / missed_tasks
  │     │     └─ weakest_topic / strongest_topic
  │     └─ calibration_service.generate_calibration  (LLM + 启发式回退)
  │           └─ 返回 CalibrationSuggestion(baseline_score_delta, schedule_adjustment, ...)
  ├─ 用户点"确认"
  │     └─ review_service.apply_weekly_review
  │           ├─ 钳位新 baseline_score 到 [0,5]
  │           ├─ 合并 schedule / 增删参考资料
  │           ├─ current_week += 1
  │           ├─ add_baseline_history
  │           └─ create_review_archive(status="confirmed")
  └─ 用户点"跳过"
        └─ review_service.skip_weekly_review
              └─ create_review_archive(status="skipped")
```

### 流程 D：LLM 调用（统一入口 + 重试 + 降级 + 入库）

```
任何 service 调用 src.llm.client.complete(prompt_name, variables, schema?, max_attempts=3)
  ├─ 取 PROMPT_REGISTRY[prompt_name] + SCHEMA_REGISTRY[prompt_name]
  ├─ tenacity.Retrying(wait_exponential(1,1,10), stop_after_attempt(3))
  │     └─ 每次失败把异常文本写入 variables["__feedback__"]，下次 prompt 末尾追加
  ├─ _call_api → POST {DEEPSEEK_BASE_URL}/chat/completions
  ├─ parse_and_validate  (JSON 抽取 + jsonschema Draft202012)
  ├─ _semantic_check     (仅 baseline_q：keyword_coverage_check)
  ├─ 成功 → 返回观测 dict {output_text, output_json, latency_ms, tokens_in/out, retry_count, model, prompt_name, prompt_version}
  ├─ 失败耗尽 → fallback_for(prompt_name) 返回静态降级载荷（目前仅 baseline_q 有）
  └─ 调用方 service 把这次结果 record_llm_call(...) 写入 llm_calls 表
```

---

## 6. 持久化产物清单

| 产物 | 路径 | 写入方 |
|---|---|---|
| 训练文件包 | `workspace/training_<slug>/00_对象档案.md ... 09_边界与止.md` | `trainer_service` → `renderer` + `file_writer` |
| SQLite 库 | `data/trainer.db`（6 张表） | `src/db/sqlite.init_db` + 各 `queries.*` |
| Agent 日志 | `logs/agent_<session_id>.log` | `src/logger.AgentLogger`（早期路径） |
| System Prompt | `prompts/system_prompt.txt` | `src/config.load_system_prompt`（首次写默认） |
| LLM 调用审计 | `data/trainer.db::llm_calls` | 每个 LLM 子服务在拿到响应后 `record_llm_call` |

SQLite 6 张表（DDL 在 `src/db/tables.sql`）：

| 表 | 用途 |
|---|---|
| `trainings` | 训练主题元数据 + 基线档位 + 当前周 + 关键词/禁忌词/计划/资料/复习项/预训练清单 JSON |
| `daily_logs` | 每日三省打卡 + 任务完成度 + 回忆题正确率 |
| `baseline_history` | 基线评分轨迹（升级曲线来源） |
| `llm_calls` | 每次 LLM 调用的可观测记录（prompt_version / latency / tokens / validation / fallback） |
| `review_archives` | 周复盘归档：指标快照 + LLM 校准建议原文 |
| `daily_log_tasks` | 今日任务卡的具体任务项（`review` / `new` / `recall`） |

---

## 7. 新人阅读顺序（推荐 4 步）

1. **理论**：[docs/training_ten_elements.md](docs/training_ten_elements.md) + [docs/学习的本质.md](docs/学习的本质.md) — 先理解"为什么这 10 个要素"。
2. **架构**：[docs/architecture.md](docs/architecture.md) — 看分层图、模块边界、关键设计决策。
3. **目录地图**：本文件 + 7 份子 `codemap.md`（按需精读）。
4. **走通闭环**：`uv run python scripts/e2e_full_flow.py` — 看真实数据如何在 6 张表 + 10 份 md 之间流转。

---

## 8. 子地图索引

| 子地图 | 链接 |
|---|---|
| `src/` 根目录 | [src/codemap.md](src/codemap.md) |
| `src/core/` | [src/core/codemap.md](src/core/codemap.md) |
| `src/db/` | [src/db/codemap.md](src/db/codemap.md) |
| `src/llm/` | [src/llm/codemap.md](src/llm/codemap.md) |
| `src/services/` | [src/services/codemap.md](src/services/codemap.md) |
| `src/ui/` | [src/ui/codemap.md](src/ui/codemap.md) |
| `src/cli/` | [src/cli/codemap.md](src/cli/codemap.md) |
