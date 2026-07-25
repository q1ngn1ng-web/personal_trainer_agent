# 🎯 训练教练 MVP

> 自用训练教练 MVP（先自用、后续拓展）

**项目定位**：基于「训练之道·十要素完整闭环 v3」的自用训练教练应用。把训练理论（十要素、学习的本质）落地成可执行的本地网页应用，支持"新建训练 → 日常执行 → 周复盘校准"完整闭环。所有 LLM 调用可追溯、所有训练文件可落盘，让用户既能跑得通，也看得见自己的进展。

---

## ✨ 核心功能

- 🆕 **新建训练**：主题具体性校验 + 关键词白名单生成 + 3 道基线诊断题 + 评分档位判定
- 🔍 **基线诊断**：LLM 受关键词约束生成诊断题，对作答做评分，输出基线档位（高/中/低）与模糊点清单
- 📝 **10 文件生成**：按十要素模板自动产出 10 份 md，落盘到 `training_<主题>/` 目录
- ✅ **今日任务卡**：根据复习日历抽取今日任务，呈现主动回忆题，支持三省打卡与任务完成勾选
- 🔁 **周复盘校准**：基于本周 daily_logs 计算指标，由 LLM 裁决基线/计划/资料/奖励的调整
- 📊 **进度仪表盘**：分层展示（基线评分、已坚持天数、今日完成度、回忆题正确率、阶段目标进度等）
- 🔬 **LLM 调用可观测**：统一客户端 + JSON Schema 强约束 + 关键词覆盖率校验 + 失败重试降级 + 调用入库可追溯

---

## 🚀 Quick Start

```bash
# 1. 克隆项目
git clone <repo-url> && cd personal_trainer_agent

# 2. 配置环境变量（填入你的 DEEPSEEK_API_KEY）
cp .env.example .env
# 编辑 .env，至少设置 DEEPSEEK_API_KEY

# 3. 安装依赖（uv 会自动管理 .venv）
uv pip install -r requirements.txt

# 4. 初始化数据库
uv run python -m src.cli init-db

# 5. 启动 Streamlit
uv run streamlit run src/main.py
```

启动后浏览器打开 `http://localhost:8501`，按向导新建第一个训练。

---

## 🏗 架构

系统采用分层架构：Streamlit UI → services 业务层 → llm/db 基础设施层。LLM 输出用 JSON Schema 强约束，训练文件 md 落盘 + SQLite 元数据索引双轨制，机械能算的指标不让 LLM 算（节省 token、稳定）。

详细架构说明、模块边界、LLM 调用契约、数据库 schema、关键设计决策见 👉 [docs/architecture.md](docs/architecture.md)

---

## 🧪 测试

端到端脚本验证完整闭环：

```bash
uv run python scripts/e2e_full_flow.py        # 完整闭环：新建 → 基线 → 10 文件 → 日常 → 周复盘
uv run python scripts/e2e_llm_observability.py # LLM 可观测层验证
uv run python scripts/e2e_review_calibration.py # 周复盘校准验证
```

---

## 🗺 Roadmap

| Phase | 名称 | 状态 | 说明 |
|---|---|---|---|
| Phase 1 | MVP（自用） | ✅ 已完成 | Streamlit 单页 + 完整十要素闭环 + LLM 可观测层 |
| Phase 2 | 通用化 | ⏳ 计划中 | 多用户、权限、对象扩展（人/LLM/动物） |
| Phase 3 | Harness 化 | ⏳ 计划中 | A/B 实验框架、回归测试、prompt 版本管理 |
| Phase 4 | 数据飞轮 | ⏳ 计划中 | 真实使用数据回流、调优策略、模板迭代 |

---

## 📚 理论根基

- [训练之道·十要素完整闭环](docs/training_ten_elements.md) — 核心理论框架
- [学习的本质](docs/学习的本质.md) — 学习方法论
- [minimax-v3-SKILL](docs/minimax-v3-SKILL.md) — LLM 训练场景技能说明