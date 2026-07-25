# trainer-mvp-v1 · 自用训练教练 MVP

> 副标题：自用训练教练 MVP（先自用、后续拓展）

## Why

毕业一年没有找到工作，需要一个能放到 GitHub 上面、获得 star 且足够硬核作为面试项目的作品。这套 MVP 是把现有训练理论（十要素完整闭环）落地成可执行、自用、并具备 harness 化潜力的工程产品。**第一周自用，第二周起逐步通用化**，最终目标是把它做成 LLM 工程能力的展示窗口。

## What Changes

- 新增一套基于 Streamlit 的本地网页应用，提供训练教练的核心交互 surface
- 新增训练主题创建流程：具体性校验（LLM）→ 关键词白名单生成 → 3 道基线诊断题 → 评分与档位判定
- 新增训练文件生成：按十要素模板自动产出 10 份 md，并落盘到 `training_<主题>/` 目录
- 新增日常训练 surface：今日任务卡（来自复习日历 + 主动回忆题）、三省打卡输入
- 新增周复盘与自动校准：基于本周 daily_logs 计算指标，由 LLM 裁决基线/计划/资料/奖励的调整
- 新增进度仪表盘：分层展示（基线评分、已坚持天数、今日完成度、基线升级曲线、回忆题正确率等）
- 新增 LLM 调用可观测层：所有 LLM 调用记录 prompt 版本、模型、延迟、token、输入输出、校验结果，支持后续 harness 化（A/B、回归、调优）
- 数据库使用 SQLite，存训练记录、日省日志、基线历史、LLM 调用日志
- 训练对象仅覆盖「人」；LLM 与动物训练分支在本次 MVP 范围外

## Capabilities

### New Capabilities

- `trainer-generation`: 新建训练能力——接收主题、跑通具体性校验、关键词白名单、3 道基线诊断题、评分与档位判定，并产出 10 份 md
- `baseline-diagnosis`: 基线诊断能力——LLM 受关键词约束生成前提诊断题，对用户作答做评分，输出基线档位（高/中/低）与模糊点清单
- `daily-execution`: 日常执行 surface——根据复习日历抽取今日任务，呈现主动回忆题，支持三省打卡输入与任务完成勾选
- `weekly-review`: 周复盘与自动校准——汇总本周 daily_logs，机械计算指标，由 LLM 裁决基线调整、下周重点、资料更新、奖励刷新
- `progress-dashboard`: 进度仪表盘——分层展示训练进展指标（P0：基线评分/已坚持天数/今日完成度；P1：基线升级曲线/回忆题正确率；P2：阶段目标进度/三省覆盖率）
- `llm-observability`: LLM 调用可观测层——统一的 LLM 客户端、JSON Schema 强约束、关键词覆盖率校验、失败重试与降级、所有调用入库可追溯（prompt_version、model、latency、tokens、in/out、validation_result）

### Modified Capabilities

无（首次引入，未对现有规格做修改）。

## Impact

- 新增文件目录：`src/`（主入口，按 ui/services/llm/db/core/templates 分模块）、`data/trainer.db`（SQLite）、`training_<主题>/`（每主题一个目录，落盘 10 份 md）
- 新增 Python 依赖：Streamlit、SQLite（内置）、DeepSeek 客户端、JSON Schema 校验库、tenacity（重试）、Jinja2（md 模板）
- API 变更：无（首次引入）
- 受影响模块：全部为新增模块，与现有 `src/` 旧版无依赖关系（本次从 0 开始设计）
- 数据迁移：无（首次引入）
- 测试影响：本次 MVP 不要求完整单测，但需要为 LLM 调用层和间隔算法预留测试接口（harness 化伏笔）
- 配置变更：`.env` 中需包含 `DEEPSEEK_API_KEY`；运行通过 `uv run streamlit run src/main.py`