# trainer-mvp-v1 · 任务清单（第一周 7 天排期）

> 任务按依赖顺序编号。每项任务预估 1 个工作单元（半天 ~ 1 天）。

## 1. 项目骨架与依赖

- [x] 1.1 创建 `src/` 目录结构（ui / services / llm / db / core / templates / cli 子目录）
- [x] 1.2 在 `requirements.txt` 追加依赖：streamlit、jsonschema、tenacity、jinja2、python-dotenv、requests
- [x] 1.3 同步追加到 `.venv` 通过 `uv pip install`
- [x] 1.4 创建 `.env.example`，列出 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 三个变量
- [x] 1.5 创建 `src/main.py` 作为 Streamlit 入口（占位页「项目说明」）
- [x] 1.6 验证 `uv run streamlit run src/main.py` 能启动空白页

## 2. LLM 可观测基础层（对应 spec: llm-observability）

- [x] 2.1 实现 `src/llm/client.py` 统一 LLM 客户端：complete(prompt_name, variables, schema) 接口，含 tenacity 指数退避重试（最多 3 次）
- [x] 2.2 实现 `src/llm/schema.py` 定义每种用途的 JSON Schema（topic_validation、keyword_generation、baseline_q、baseline_scoring、weekly_calibration）
- [x] 2.3 实现 `src/llm/validators.py`：JSON 解析 + jsonschema 校验 + 关键词覆盖率校验（baseline_q 用）
- [x] 2.4 实现 `src/llm/prompts.py`：集中管理所有 prompt 模板字符串 + 版本号常量（`BASELINE_Q_PROMPT_VERSION = 'v1.0.0'` 等）
- [x] 2.5 实现 `src/llm/retry.py`：失败重试策略（指数退避 + 失败原因注入下一次 prompt）
- [x] 2.6 实现 `src/llm/fallback.py`：每种用途的降级返回（baseline_q 用预置 3 题 fallback；其他用途返回 None 并打 warn 日志）

## 3. 数据层

- [x] 3.1 设计 SQLite schema：tables.sql 含 trainings / daily_logs / baseline_history / llm_calls / review_archives
- [x] 3.2 实现 `src/db/sqlite.py`：连接管理 + 启动时执行 schema migration
- [x] 3.3 实现 `src/db/models.py`：dataclass 定义 Training / DailyLog / BaselineHistory / LLMCall / ReviewArchive / Element
- [x] 3.4 实现 `src/db/queries.py`：CRUD 函数 + harness 查询接口（`get_calls_by_purpose`、`get_success_rate_by_prompt_version`、`get_avg_latency_by_model`）
- [x] 3.5 创建 `src/cli.py` 提供 `init-db` 命令（创建空 db），README 写明启动步骤
- [x] 3.6 验证：执行 `init-db` 后 db 文件存在且表结构正确

## 4. 领域模型与十要素数据

- [x] 4.1 实现 `src/core/training.py`：Training 聚合根（含 keywords / directory / baseline_score / status / targets / review_items / pretrain_checklist 字段）
- [x] 4.2 实现 `src/core/element.py`：十要素枚举（OBJECT/BASELINE/GOAL/MATERIAL/SCHEDULE/METHOD/ENVIRONMENT/REWARD/REFLECTION/BOUNDARY）+ 每要素子项 dataclass
- [x] 4.3 实现 `src/core/content_dim.py`：ContentDimension 枚举（CONCEPT / READ / WRITE）与标签常量
- [x] 4.4 实现 `src/core/baseline.py`：BaselineScore dataclass（score, dimension_scores, partial_topics）与档位计算函数

## 5. md 模板与渲染

- [x] 5.1 创建 `src/templates/` 目录，放 10 个 Jinja2 模板 `00_对象档案.md.j2` 到 `09_边界与止.md.j2`
- [x] 5.2 模板内容严格对齐 `docs/minimax-v3-SKILL.md` 的文件模板章节
- [x] 5.3 实现 `src/services/renderer.py`：trainer context dict → 10 份 md 字符串
- [x] 5.4 实现 `src/services/file_writer.py`：清洗目录名 + 落盘 + 写权限检查 + 失败回滚

## 6. 训练生成服务（对应 spec: trainer-generation + baseline-diagnosis）

- [x] 6.1 实现 `src/services/topic_validation.py`：调用 LLM 做具体性校验，返回 `(is_valid, suggestions)` 元组
- [x] 6.2 实现 `src/services/keyword_service.py`：调用 LLM 生成关键词白名单，含 must_cover_count + forbidden
- [x] 6.3 实现 `src/services/baseline_service.py`：3 道题生成（含关键词覆盖率校验 + fallback）
- [x] 6.4 实现 `src/services/scoring_service.py`：用户作答评分 + 档位判定 + partial_topics 提取
- [x] 6.5 实现 `src/services/trainer_service.py`：编排上述流程，生成完整 Training 对象 + 落盘 10 md + 写库
- [x] 6.6 实现 `src/ui/page_new_training.py`：Streamlit 表单向导（4 步：主题输入 → 关键词确认 → 基线作答 → 完成）

## 7. 日常执行 surface（对应 spec: daily-execution）

- [x] 7.1 实现 `src/services/schedule_service.py`：固定间隔算法（1-3-7-15-30），从 training 历史提取今日复习/新学任务
- [x] 7.2 实现 `src/services/recall_service.py`：从 `05_主动回忆题.md` 抽取今日应做的题（含 content_dim 分布规则）
- [x] 7.3 实现 `src/services/daily_log_service.py`：任务勾选、三省提交、回忆题正确率记录，全部走 `daily_logs` 表
- [x] 7.4 实现 `src/ui/page_daily.py`：今日任务卡页面（复习项 + 新学项 + 回忆题 + 三省输入 + 完成度进度条 + 领取奖励引导）

## 8. 周复盘与校准（对应 spec: weekly-review）

- [x] 8.1 实现 `src/services/metrics_calculator.py`：纯 Python 机械计算本周 7 项指标（avg_completion / avg_recall_success / three_reflection_coverage / consecutive_days / weakest_topic / strongest_topic / missed_tasks）
- [x] 8.2 实现 `src/services/calibration_service.py`：调用 LLM 做校准裁决（JSON Schema 强约束 + retry + fallback）
- [x] 8.3 实现 `src/services/review_service.py`：编排复盘流程（指标计算 → LLM 校准 → 渲染简报 → 用户确认 → 更新训练文件与数据库 → 写 review_archives）
- [x] 8.4 实现 `src/ui/page_review.py`：周复盘简报页（指标展示 + LLM 校准建议 + 确认/跳过按钮）

## 9. 仪表盘（对应 spec: progress-dashboard）

- [x] 9.1 实现 `src/services/progress_service.py`：P0 指标计算（baseline_score / consecutive_days / today_completion）
- [x] 9.2 实现 `src/ui/page_home.py`：Streamlit 首页（项目说明 + 训练列表 + 新建按钮）
- [x] 9.3 实现 `src/ui/page_training.py`：训练详情页顶部 P0 指标块
- [x] 9.4 预留 P1 指标区（曲线图组件位置 + 「数据收集中」占位）
- [x] 9.5 验证：新建训练 → 看 P0 指标更新 → 打卡后看今日完成度变化

## 10. 端到端自用验证

- [x] 10.1 用 asyncio/aiohttp 真主题走完完整流程：新建 → 关键词生成 → 3 道基线题 → 评分 → 10 md 落盘
- [x] 10.2 模拟 3 天日常 surface（手动往 daily_logs 插数据），验证任务卡抽取逻辑
- [x] 10.3 触发一次周复盘，验证指标计算 + LLM 校准 + 文件更新
- [x] 10.4 检查 `llm_calls` 表数据完整（每种 call_purpose 都有记录、prompt_version 写入正确）
- [x] 10.5 修复自用过程中发现的所有 bug
- [x] 10.6 整理 README：项目说明、Quick Start、真主题 demo 截图占位

## 11. 文档与可移植性

- [x] 11.1 写 README.md：含项目定位、架构图、Quick Start（uv run 命令）、Roadmap（Phase 1/2/3/4）
- [x] 11.2 写 docs/architecture.md：从设计文档提炼架构图（Mermaid）
- [x] 11.3 写 .env.example 完整说明
- [x] 11.4 创建 `workspace/record/2026MMDD_feat_trainer-mvp-v1.md` 变更记录（按 AGENTS.md 规则）

---

## 7 天排期映射

| 天 | 主要任务 |
|---|---|
| Day 1 | 1.1~1.6, 3.1~3.3 |
| Day 2 | 2.1~2.6, 3.4~3.6 |
| Day 3 | 4.1~4.4, 5.1~5.4 |
| Day 4 | 6.1~6.6 |
| Day 5 | 7.1~7.4, 9.1~9.5 |
| Day 6 | 8.1~8.4 |
| Day 7 | 10.1~10.6, 11.1~11.4 |

## 验收标准（MVP 完成定义）

- [x] 用真主题（asyncio）走完完整流程无报错（E2E 11/11 通过）
- [x] 10 份 md 文件可见、内容对齐文档模板（E2E 验证）
- [x] 任务卡能正确抽取今日任务（E2E 验证）
- [x] 三省提交持久化（daily_log_service + E2E 验证）
- [x] 周复盘可触发、指标正确、LLM 校准可执行（E2E 验证，heuristic fallback 可用）
- [x] 首页 P0 指标实时反映数据（progress_service + page_home）
- [x] `llm_calls` 表完整、可按 prompt_version / call_purpose 查询（harness_smoke + check_llm_logs 通过）
- [x] README 可让陌生人 5 分钟内跑通项目（README.md + Quick Start 段落）