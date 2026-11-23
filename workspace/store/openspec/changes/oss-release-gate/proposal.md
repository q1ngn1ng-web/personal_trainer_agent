# oss-release-gate · 开源发布门禁（提案，待实施）

> 状态：**仅提案，未实施**。本文件为**自包含交接文档**——实施会话只读本 change
> （proposal / design / tasks / specs）即可动手，不需要创建者的对话上下文。
> 来源：2026-11-23 项目设计评审（为 B 站系列视频与 GitHub 开源做的就绪度审计）。
> 实施者注意：tasks 第 0 节四项是**作者决策**，未拍板不阻塞 1.x / 2.x 里不依赖它们的任务。

## Why

作者计划开源本仓库，并用系列视频吸引贡献者。审计（证据见 design D0）发现五类问题，
按"会不会伤害来访者和贡献者"排序：

1. **线上真 bug（在演示路径上）**：`GET /api/trainings/{id}/session-summary` 在
   "当天有带 `plan_id` 的判分作答"时必然 500——`session_summary.py:99` 查了 `plan_items`
   上不存在的 `knowledge_point` / `title` 列。线上 2026-11-23 17:09 连续两次 500；
   生产库有 20 条带 `plan_id` 的作答。测试没抓到，是因为用例造的作答都没带 `plan_id`，
   恰好绕开出错分支。
2. **README 把新人带到已下线的产品**：Quick Start 仍是 `streamlit run src/main.py`
   （一代 UI，Vue 版已完整取代）；`requirements.txt` 没有 fastapi / uvicorn /
   python-multipart / pytest，按 README 装不出可运行的后端；"测试"一节指向的
   `scripts/e2e_full_flow.py` 跑的是一代生成流程；AGENTS.md 仍称 `src/` 是
   "仅作参考的 Streamlit demo"。
3. **仓库里混着私人材料**：`git ls-files` 里有 `workspace/面试/`（7 个文件）、
   `workspace/record/`（90 篇个人开发记录）、含真实作答数据的
   `workspace/evidence/判分一致性标注-工作表-真实数据.csv`、
   `data/Redis 持久化八股文.pdf`。
4. **没有 LICENSE**：根目录无许可证文件——法律上不是开源，他人无权使用、修改、分发。
5. **公网暴露面**：服务直接监听 `0.0.0.0:8501` 明文 HTTP（无 443、ufw inactive），
   注册接口公开、未见限流；任何注册用户都能触发消耗作者 API 额度的 LLM 调用。

另有三处小缺陷随本 change 一并修（都在演示路径上或影响正确性）：澄清对话历史里
追问原文是空串、学习者模型衰减与"当天"口径的时区基准、基线出题提示词错别字。

## What Changes

**A. 今晚阻断（tasks 1.x）**：修会话小结 500 并补带 `plan_id` 的端点级回归钉子；
澄清追问原文入史；学习者模型衰减按真实流逝时间计算、会话小结"当天"接回
`local_today()` 口径；基线提示词错别字与版本号。

**B. 仓库对外可读（tasks 2.x）**：`requirements.txt` 补齐真实依赖；README 重写为
FastAPI + Vue 的真实启动方式；`.env.example` 与 AGENTS.md 更正失实描述；
全新环境按 README 冒烟（10 分钟标准）。

**C. 作者决策（tasks 0.x）**：许可证类型；公开仓策略（直接公开 / 清洗历史 / 全新历史）；
视频是否放演示地址；一代遗留代码（约 4,000 行）如何处置。

**D. 贡献者基础设施（tasks 3.x）**：CI、CONTRIBUTING、issue / PR 模板、SECURITY、
good first issue 清单、部署样例。

**E. 暴露面护栏（tasks 4.x，条件触发）**：注册开关、限流、每用户每日 LLM 上限、
通用 500 的可读错误。**视频不放演示地址时，4.x 不阻断发布。**

### 关键取舍

| 选择 | 备选 | 放弃理由 |
| --- | --- | --- |
| 录制与公开解耦 | 等所有 bug 清零再录 | 观众容忍"边做边修"，不容忍泄露与跑不起来；录制不依赖 README |
| 会话小结按既有列解析知识点 | 给 `plan_items` 加 `knowledge_point` 列 | 加列要迁移 + 回填两张表的存量；知识点的事实源在 `question_bank` / `training_items`，`answer_service._task_context` 已是这么解析的 |
| 衰减用真实流逝时间（带时区相减） | 把时间戳转成本地再去时区 | 流逝时间与时区无关；转本地只是把 bug 换个写法 |
| 全新历史公开仓（推荐） | `git filter-repo` 清洗 | 清洗是破坏性操作且不可逆；历史里没有密钥，私人材料用新仓自然隔离 |
| 限流用进程内令牌桶 | 引入 Redis / 网关 | 单进程部署，零新依赖；多实例时再升级 |
| 一代代码本 change 只"不再指向" | 本 change 内直接删除 | 删除面 4,000 行且并行会话正在 renderer / 模板区施工，撞车风险高 |

## 非目标（Non-goals）

- 不做任何业务功能，不改判分口径、排期、达标条件
- 不做 agent 化、不换底座、不引入 FSRS（另行提案）
- 不重写 git 历史、不 force push（除非作者拍板 0.2 选 B 并本人在场）
- 不删除一代遗留代码（等 0.4 拍板，另立 change）
- 不动 `data/trainer.db`，不动并行会话在飞文件（清单见 design D9）

## Capabilities

### New Capabilities

- `oss-release-readiness`：仓库对外可读、可安装、可授权、不带私人材料、公网部署有护栏

### Modified Capabilities

- `coach-memory`：会话小结不依赖不存在的列、"当天"口径接回 `local_today()`
- `goal-clarification`：追问原文随对话历史留存
- `learner-memory`：掌握度衰减按真实流逝时间计算

## Impact

- **代码**：`src/services/session_summary.py`、`src/services/goal_clarification_service.py`、
  `src/services/learner_service.py`、`src/llm/prompts.py`（仅基线提示词错别字 + 版本号）、
  `tests/test_coach_memory.py` / `tests/test_goal_clarification.py` / `tests/test_learner_model.py`
  / `tests/test_prompt_schema_contract.py`（版本钉）；4.x 另涉 `src/api/app.py`、
  `src/services/auth_service.py`
- **仓库文件**：`README.md`、`AGENTS.md`、`requirements.txt`、`.env.example`、`.gitignore`、
  `LICENSE`、`.github/`、`deploy/`
- **数据**：零迁移、零新表
- **风险**：中——README / AGENTS / 依赖属于"人人都会读"的文件，改错影响面大，
  每一项都要在全新环境里实测后再提交；业务代码改动面很小但都在主链上，改后跑全量回归
