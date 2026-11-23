# oss-release-gate · 任务清单（未排期）

> 分四段，可按需截断移交：**1.x 录制前必须绿；2.x 公开仓库前必须绿；
> 3.x 一周内；4.x 条件触发**。第 0 节是作者决策，未拍板不阻塞 1.x / 2.x 里
> 不依赖它们的任务。开工前先读 design D9 的冲突避让清单。

## 0. 作者决策（拍板后回填本节）

- [ ] 0.1 许可证类型。推荐 **MIT**（同类项目如 pi-mono 皆为 MIT，对贡献者门槛最低；
      若在意专利授权与商标，选 Apache-2.0）。拍板前 LICENSE 不落盘。
- [ ] 0.2 公开仓策略：A 直接公开 / B `git filter-repo` 清洗 / **C 全新历史公开仓（推荐）**。
      选 C 时一并定：公开仓是否成为唯一开发主仓。
- [ ] 0.3 视频是否放演示地址。**推荐不放**；要放则 4.x 升级为发布前阻断项。
- [ ] 0.4 一代遗留代码处置（Streamlit UI + 一代生成流，约 4,043 行）：
      删除（推荐，另立 change）/ 移入 `legacy/` / 保留。拍板前本 change 只做"README 与
      AGENTS.md 不再把它当入口"。

## 1. 录制前必须绿

- [ ] 1.1 修会话小结 500：`src/services/session_summary.py::summarize_day` 的元数据查询
      不得引用 `plan_items` 上不存在的列。知识点名按 design D2 的顺序解析
      （`question_bank.knowledge_point` → `training_items.knowledge_point` → `item_key`），
      要点清单仍取 `plan_items.points`；单条元数据缺失不得让整份小结抛异常。
- [ ] 1.2 端点级回归钉子（`tests/test_coach_memory.py`）：补"带 `plan_id` 的真实计划项"
      链路——建训练与计划项 → `record_attempt(plan_id=...)` → 请求
      `GET /api/trainings/{id}/session-summary`，断言 200、题数正确、
      `weakest_knowledge_point` 有值。保留原有空日用例。
- [ ] 1.3 澄清追问入史（`src/services/goal_clarification_service.py`）：`_persist` 把本轮
      待答问句写进 `goal_json`（键 `pending_question`）；`continue_session` 追加 history 时
      用上一轮的 `pending_question` 作为 `question`；旧训练无该键时回落空串（design D3）。
- [ ] 1.4 测试（`tests/test_goal_clarification.py`）：两轮澄清后 `history[0]["question"]`
      等于第 1 轮的追问；经 `load_session` 恢复后再回答，历史仍带问句；无 `pending_question`
      的旧状态不报错。
- [ ] 1.5 衰减时间口径（`src/services/learner_service.py`）：`_parse` 与 `get_learner_model`
      改为按真实流逝时间计算——带时区按其时区、不带时区按 UTC，与
      `datetime.now(timezone.utc)` 相减（design D4）。测试用带 `+00:00` 的时间戳断言
      "刚作答完 → 距 last_seen 约为 0、`decayed_mastery == mastery`"。
- [ ] 1.6 "当天"口径（`src/services/session_summary.py`）：把 `date(created_at, 'localtime')`
      换成按 `local_tz()` 计算的当日 UTC 起止区间过滤（design D4）。测试：把 `TRAINER_TZ`
      设为非系统时区，断言跨日的两条作答落在各自的日子；测试结束恢复原值。
- [ ] 1.7 基线出题提示词错别字（`src/llm/prompts.py:36`）："哟怒火" → "用户"；
      `BASELINE_Q_PROMPT_VERSION` v1.0.0 → v1.0.1，并同步
      `tests/test_prompt_schema_contract.py` 的版本钉。该提示词属一代流程，非阻断，顺手修。
- [ ] 1.8 全量回归：`.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`。
      基线 415 passed / 6 skipped / 1 failed（renderer 模板那条属并行会话在飞区，不计入）；
      本 change 不得新增失败。改后 `sudo -n systemctl restart trainer-api`，
      用作者本人的账号对一个**当天练过日常题**的训练请求 `session-summary`，确认 200
      （线上复现用的是训练 144，2026-11-23 17:09 的两次 500）。

## 2. 公开仓库前必须绿

- [ ] 2.1 `requirements.txt`：补 fastapi、uvicorn、python-multipart、pytest（给下限约束，
      参照环境内版本，见 design D0）；删除与 python-dotenv 重复的 `dotenv`；
      streamlit 按 0.4 的决定保留或移除。
- [ ] 2.2 `.env.example`：补 `TRAINER_AUTH`、`TRAINER_COOKIE_SECURE`（注明本地 HTTP 调试必须为 0）、
      `TRAINER_TZ`、`LLM_LIGHT_MODEL`。以代码实际读取的变量为准——
      产品本体只读 `DEEPSEEK_*`，`DASHSCOPE_API_KEY` 只有 `scripts/` 里的评测脚本用。
- [ ] 2.3 README 重写（design D7 为验收标准）：
      - 定位一句话、技术栈（FastAPI + Vue 3 + SQLite + LLM）、界面截图或动图
      - Quick Start：后端（建虚拟环境 → 安装依赖 → `python -m src.cli init-db` → 配 `.env`
        → `uv run uvicorn src.api.app:app --port 8501`）；前端（`cd web && npm install &&
        npm run build`）；个人自用提示 `TRAINER_AUTH=0`。删除"启动 Streamlit 打开 8501"。
      - 环境变量表、测试命令（pytest；注明 `scripts/e2e_full_flow.py` 属一代流程且需 API key）
      - 架构说明链接 `docs/architecture.md`、路线图（按 openspec 现状）、
        License 一节、免责声明（学习项目；判分一致性人工标注仅 n=6，见
        `workspace/evidence/判分一致性标注-人工填写.md`）
- [ ] 2.4 AGENTS.md 更正失实描述（只更正、不改规则）：`src/` 不再是"仅作参考的 Streamlit
      demo"，入口是 `src/api/app.py`，启动命令同 2.3；目录表补 `web/`；
      "不要重构 src/ 下的 demo 代码"一条按 0.4 的决定改写适用范围。该文件是所有 AI
      协作者的入口文档，失实会误导每一个贡献者。
- [ ] 2.5 全新环境冒烟：在空目录 `git clone` 后按 README 逐条执行，记录"到登录页"的耗时与
      卡点，写进 record。不达标就改 README 再测。
- [ ] 2.6 LICENSE 落盘 + README 的 License 一节（依赖 0.1）。
- [ ] 2.7 私人材料出库（依赖 0.2）：对 design D6"必须出库"各项执行 `git rm --cached`
      并补 `.gitignore`；"待作者定"各项先 grep 邮箱 / 手机号 / 真实姓名再交作者定。
      注意 `git rm --cached` 只清索引不清历史，历史处理取决于 0.2。

## 3. 一周内（贡献者基础设施）

- [ ] 3.1 CI：`.github/workflows/ci.yml`——后端 pytest（Python 3.12）+ 前端
      `npm ci && npm run build`（Node 22）。streamlit 相关的既有失败用例若随 0.4 删除则一并清理。
- [ ] 3.2 `CONTRIBUTING.md`：本地启动、目录导览、openspec 流程怎么参与、提交信息规范、
      测试要求（可见性 / 权限 / 过滤类改动必须带端点级用例与跨用户隔离用例）。
- [ ] 3.3 `.github/ISSUE_TEMPLATE/`（bug 报告、功能建议、good first issue）与
      `PULL_REQUEST_TEMPLATE.md`。
- [ ] 3.4 `SECURITY.md`：私下报告漏洞的方式；明示演示实例（如有）不保证可用性。
- [ ] 3.5 good first issue 清单（至少 6 个，各配验收标准），建议来源：统一全项目 `_now()`
      时间口径、澄清追问入史的前端展示、出题资料接地的检索化、`app.py` 按业务域拆分路由、
      前端首个组件测试、部署文档。
- [ ] 3.6 `deploy/`：systemd 单元与 nginx 反代样例（路径与域名占位化），README 链接。

## 4. 暴露面护栏（放演示地址则为发布前阻断项）

- [ ] 4.1 注册开关 `TRAINER_REGISTER_OPEN`（默认 1 保持现状；为 0 时
      `POST /api/auth/register` 返回 403 与可读提示，登录不受影响）+ 测试。
- [ ] 4.2 限流：登录、注册、出题、判分、澄清端点按来源 IP 限流（进程内令牌桶，
      阈值走环境变量），超限 429 + `Retry-After` + 测试。
- [ ] 4.3 每用户每日 LLM 调用上限（按 `llm_calls` 计数，阈值走环境变量）：超限时出题、
      判分等入口返回可读错误，不调用 LLM、不写半成品 + 测试。
- [ ] 4.4 通用 500 处理：未捕获异常返回 JSON（含请求追踪 id），服务端日志带同一 id，
      便于观众报 bug 时直接贴。
- [ ] 4.5 部署走 HTTPS：nginx 反代 + 证书，`TRAINER_COOKIE_SECURE=1`，uvicorn 只监听
      127.0.0.1（样例见 3.6）。
