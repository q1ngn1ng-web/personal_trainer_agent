# 20260725 · feat · trainer-mvp-v1

> 训练教练 MVP 首次落地（trainer-mvp-v1）

---

## 变更摘要

完成了训练教练 MVP 的首次完整落地（OpenSpec change `trainer-mvp-v1`）。基于「训练之道·十要素完整闭环 v3」理论，构建了 Streamlit 本地网页应用，跑通"新建训练 → 基线诊断 → 10 文件生成 → 今日任务卡 → 周复盘校准 → 进度仪表盘"完整闭环。同步落地 LLM 调用可观测层（JSON Schema 强约束 + prompt 版本化 + 调用入库可追溯），为后续 harness 化预留基建。

为什么做：把现有训练理论从文档落到可执行的工程产品，先自用验证闭环，再面向 GitHub 开源积累 star 与面试素材。

---

## 影响范围

- `src/llm/` — LLM 客户端、prompt 模板、JSON Schema、关键词覆盖率校验、重试降级
- `src/db/` — SQLite 连接、queries、Pydantic 模型
- `src/core/` — 间隔算法（1-3-7-15-30）、档位规则、业务常量
- `src/services/` — trainer / baseline / schedule / recall / daily_log / metrics / calibration / review / progress 九大业务模块
- `src/ui/` — Streamlit 多 Page（home / new_training / daily / review / training）
- `src/templates/` — Jinja2 渲染 10 份 md 模板
- `src/main.py` — Streamlit 多 Page 路由入口
- `src/cli/` — `init-db` 等命令
- `README.md` — 项目说明 + Quick Start + Roadmap
- `docs/architecture.md` — 新增架构文档（系统图、模块边界、LLM 契约、DB schema、设计决策、演进方向）
- `.env.example` — 增加 LOG_LEVEL 配置项
- `data/trainer.db` — 首次初始化（不入 git）
- `training_<主题>/` — 每主题一个目录，落盘 10 份 md（不入 git）

---

## 相关文件路径

关键新增/修改：

- `src/main.py`、`src/config.py`、`src/logger.py`
- `src/cli/`（init-db 命令）
- `src/core/`（间隔算法、档位规则）
- `src/services/`（trainer / baseline / schedule / recall / daily_log / metrics / calibration / review / progress）
- `src/llm/`（client / prompts / schema / validators / retry / fallback）
- `src/db/`（sqlite / queries / models）
- `src/ui/`（page_home / page_new_training / page_daily / page_review / page_training）
- `src/templates/`（10 份 md Jinja2 模板）
- `data/trainer.db`（运行时生成）
- `training_<主题>/*.md`（运行时生成）
- `README.md`（项目说明）
- `docs/architecture.md`（架构文档，本变更新增）
- `.env.example`（增加 LOG_LEVEL）
- `requirements.txt`（追加依赖：streamlit、tenacity、jinja2、pydantic 等）
- `workspace/store/openspec/changes/trainer-mvp-v1/`（OpenSpec 提案与设计文档）

---

## 关联的 OpenSpec change id

**`trainer-mvp-v1`** — 自用训练教练 MVP（先自用、后续拓展）

详见：
- `workspace/store/openspec/changes/trainer-mvp-v1/proposal.md`
- `workspace/store/openspec/changes/trainer-mvp-v1/design.md`

---

## 关键能力（spec 摘要）

| Capability | 说明 |
|---|---|
| `trainer-generation` | 新建训练：主题具体性校验 → 关键词白名单 → 3 道基线诊断题 → 评分档位 → 产出 10 份 md |
| `baseline-diagnosis` | 基线诊断：LLM 受关键词约束生成诊断题，评分后输出档位（高/中/低）与模糊点清单 |
| `daily-execution` | 日常执行：复习日历抽取今日任务、主动回忆题呈现、三省打卡输入、任务完成勾选 |
| `weekly-review` | 周复盘与自动校准：机械计算指标 + LLM 裁决（基线调整 / 下周重点 / 资料更新 / 奖励刷新） |
| `progress-dashboard` | 进度仪表盘：分层 P0/P1/P2 展示（基线评分、已坚持天数、今日完成度、回忆正确率、阶段目标进度） |
| `llm-observability` | LLM 调用可观测：统一客户端、JSON Schema 强约束、关键词覆盖率校验、重试降级、调用入库可追溯 |

---

## 已知局限 / 后续工作

- **Phase 2 通用化**：当前仅自用单用户，需扩展多用户、权限系统、对象分支（人/LLM/动物）
- **Phase 3 Harness 化**：基于 `llm_calls` 表构建 A/B 实验框架、回归测试套件、prompt 版本管理 UI
- **LLM 校准 prompt 调优**：周复盘裁决的 JSON Schema 字段需要根据实际使用数据迭代
- **间隔算法动态化**：当前固定 1-3-7-15-30，后续基于回忆成功率动态调整
- **数据库迁移**：SQLite 单点写并发问题在 Phase 2 评估切换 PostgreSQL
- **关键词白名单质量**：依赖 LLM 自生成 + 覆盖率校验，需要持续调优 prompt 并积累主题级 fallback 词典