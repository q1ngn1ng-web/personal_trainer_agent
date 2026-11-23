# oss-release-gate · 设计

## D0 审计证据（全部为 2026-11-23 实测，命令可复现）

| 事实 | 证据 | 核实方式 |
| --- | --- | --- |
| 项目不是 agent，是固定流程 + 单次结构化 LLM 调用 | `src` 与 `scripts` 内 `tools=` / `tool_calls` / `function_call` / `bind_tools` / `langgraph` / `StateGraph` 零命中；`src/llm/client.py:147-156` 每次调用都是"固定 system + 单条 user" | `grep -rnE "tools\s*=\|tool_calls\|function_call\|bind_tools\|langgraph\|StateGraph" src scripts --include=*.py` |
| 会话小结 500 | 堆栈落在 `session_summary.py:99`，`sqlite3.OperationalError: no such column: knowledge_point` | `journalctl -u trainer-api --since "2026-11-23 17:09:00" --until "2026-11-23 17:09:20"` |
| 生产库 `plan_items` 确无该列 | 列清单：id, training_id, item_key, round_index, kind, due_date, anchor_date, original_date, status, planned_minutes, practiced_at, reason, created_at, question, reference_answer, answer_text, verdict, graded_by, graded_at, points, question_type, options | 只读打开 `data/trainer.db` 执行 `PRAGMA table_info(plan_items)` |
| 触发面 | 带 `plan_id` 的作答 20 条 | 同上，`SELECT COUNT(*) FROM practice_attempts WHERE plan_id IS NOT NULL` |
| 测试为何没抓到 | `tests/test_coach_memory.py` 的 `_record_today(..., plan_id=None)` 默认不带 `plan_id` → `plan_ids` 为空 → 跳过元数据查询 | 读 `TestSessionSummary` 用例 |
| README 指向一代 UI | Quick Start 第 5 步 `uv run streamlit run src/main.py`，打开 8501 | 读 `README.md` |
| 依赖装不出来 | `requirements.txt` 11 行，无 fastapi / uvicorn / python-multipart / pytest；环境内实际为 fastapi 0.141.1、uvicorn 0.51.0、python-multipart 0.0.32、pytest 9.1.1 | 读文件 + `ls .venv/lib/python3.12/site-packages` |
| 一代流程已不可达 | `src/api/app.py` 对 trainer_service / scoring_service / keyword_service / baseline_service / renderer / file_writer 的引用数均为 0；这些模块只被 `scripts/` 引用。合计约 1,214 行 + `src/ui/` 2,661 行 + `src/main.py` 168 行 ≈ 4,043 行 | 逐模块反向 grep |
| 私人材料被跟踪 | `workspace/面试/` 7、`workspace/record/` 90、`workspace/evidence/` 19（含"真实数据"CSV）、`workspace/prompts/` 3、`data/` 下 1 个 PDF | `git -c core.quotepath=false ls-files`（**注意**：不加该参数时中文路径被八进制转义，按中文 grep 会误判为 0） |
| 历史无密钥 | 全部提交内 `sk-[A-Za-z0-9]{32,}` 零命中；`.env` 与 `data/trainer.db` 从未入库；跟踪内容里无测试账号口令 | `git rev-list --all` 逐提交 `git grep` |
| 无 LICENSE / CI | 根目录无 LICENSE、无 `.github/`、无 pyproject | `ls -la` + `git ls-files` |
| 暴露面 | `0.0.0.0:8501 uvicorn`、`0.0.0.0:80 nginx`（只代理 9090 的另一个项目）、无 443、`ufw` inactive；`_AUTH_EXEMPT_PATHS` 含 register / login；代码内无限流 | `ss -tlnp`、`ufw status`、读 `src/api/app.py:69-83` |
| 衰减时间口径 | `learner_service.py:37` 对带时区的时间戳直接 `replace(tzinfo=None)`（不换算），`:151` 用裸 `datetime.now()`；服务器时区 Asia/Shanghai → 流逝时间被多算 8 小时 | 读代码 + `timedatectl` |
| "当天"口径分叉 | `session_summary.py:89` 用 SQLite `date(created_at, 'localtime')`（跟数据库进程系统时区）；而 `src/core/plan.py::local_today()` 用 `TRAINER_TZ`（默认 Asia/Shanghai） | 读代码 |
| 追问原文为空 | `goal_clarification_service.py:296` `history.append({"question": "", "answer": ...})` | 读代码 |
| CLI 只有 init-db | `src/cli/__main__.py` 仅注册 `init-db`；文档里提到的 `serve-api` 子命令不存在 | 读代码 |
| 实施前测试基线 | 415 passed / 6 skipped / 1 failed（`test_units.py::TestRendererEmpty::test_render_empty_context_returns_ten_files`，TemplateNotFound——并行会话正在删 `src/templates/*.j2`） | `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`（6 分 13 秒） |

## D1 录制与公开解耦

视频录制只依赖"演示路径不崩"，不依赖 README、LICENSE、CI。所以门禁分两档：

- **录制前必须绿**：tasks 1.1–1.6（演示路径上的 bug）
- **公开仓库前必须绿**：1.x + 2.x + 已拍板的 0.x

时间不够时，照常录制，仓库链接等门禁全绿再放进简介。观众能接受"边做边修"，
不能接受自己的密码走明文、按 README 跑不起来。

## D2 会话小结的取数口径

现状：`SELECT id, knowledge_point, title, points FROM plan_items WHERE id IN (...)`。
`plan_items` 只有 `item_key` 与 `points`，没有知识点名。

修复后对每条作答：

1. 要点清单：`plan_items.points`（按 `practice_attempts.plan_id`）
2. 知识点名，按序回落：
   - `question_bank.knowledge_point`（`training_id` + `item_key`）——与
     `memory_service.knowledge_profile` 同源
   - `training_items.knowledge_point`（经 `item_key` 关联到最新确认路径下的阶段）——
     与 `answer_service._task_context` 同源
   - `item_key` 本身

不给 `plan_items` 加列：那要迁移并回填存量，而知识点的事实源本来就在另外两张表。
单条作答元数据缺失只影响该条的统计，不得让整份小结抛异常。

## D3 追问原文入史

现状只在 history 里存用户回答，系统问了什么没有落库（`ClarificationSession.question`
只在响应里，`_persist` 不写）。下一轮 LLM 看到"第 1 轮追问:（空）/ 用户回答: 能用就行"，
只能猜这句回答对应哪个字段。

修复：`_persist` 时把本轮待答问句写进 `goal_json`（新增键 `pending_question`）；
`continue_session` 追加 history 时取上一轮的 `pending_question` 作为 `question`。
旧训练没有该键 → 回落空串，行为与现状一致。

## D4 时间口径

项目已有统一口径：`src/core/plan.py::local_tz()` / `local_today()`（`TRAINER_TZ`，
默认 Asia/Shanghai），其 docstring 明确"所有与'今天'相关的判断都必须走这里"。
本 change 是把两处没走它的代码接回去，不新造时钟模块（全项目统一 `_now()` 属后续重构）。

- **衰减**：流逝时间与时区无关。带时区的时间戳按其时区解释，不带时区的按 UTC 解释，
  与 `datetime.now(timezone.utc)` 相减。
- **"当天"**：先用 `local_tz()` 把目标日期换算成当日起止两个 UTC 时刻，
  再按 `created_at >= 起 AND created_at < 止` 过滤。`created_at` 是 ISO 字符串，
  比较前需确认格式一致（现状为 `datetime.now(timezone.utc).isoformat()`，
  形如 `2026-11-23T09:00:00.123456+00:00`）；若库内混有其它格式，按
  `parse_local_date` 的容错方式在 Python 侧逐条判定，宁慢勿错。

## D5 公开仓策略（tasks 0.2 待拍板）

| 方案 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| A 直接公开现仓 | 改仓库可见性 | 最快 | 193 个提交的历史里带着面试材料、90 篇记录、PDF；`git rm --cached` 清不掉历史。**不建议** |
| B 清洗历史后公开 | `git filter-repo` 剔除路径 | 保留提交历史 | 破坏性、不可逆，必须先整仓备份；旧克隆全部失效 |
| C 全新历史公开仓（**推荐**） | `git archive` 导出白名单路径 → 新仓库首提交；现仓转私有存档 | 无破坏性操作；私人材料天然隔离；一天内可完成 | 丢失提交历史（可在公开仓放一份 CHANGELOG 或把 `workspace/record/` 带过去当编年史） |

选 C 之后的开发主仓问题（公开仓为唯一主仓 / 双仓并行）一并由作者拍板。

## D6 私人材料三分法

| 处置 | 路径 | 理由 |
| --- | --- | --- |
| 必须出库 | `workspace/面试/`、`workspace/evidence/判分一致性标注-工作表-真实数据.csv`（及含真实作答的工作表）、`data/*.pdf`、`workspace/prompts/`、`workspace/AUDIT-BRIEF.md`、`workspace/SUMMARY-*.md` | 求职材料、个人真实数据、个人学习资料、个人工作提示词 |
| 建议保留公开 | `workspace/decisions/`、`workspace/store/`、`docs/architecture.md` | ADR 与 openspec 规格是贡献者最需要的上下文，也是系列的素材 |
| 待作者定 | `workspace/record/`（90 篇）、`workspace/BACKLOG.md`、`workspace/HANDOFF.md` | 公开有"边做边修"的透明度价值，但需先逐个 grep 邮箱 / 手机号 / 真实姓名 |

## D7 "10 分钟上手"验收标准

在一台只有 Python 3.12 与 Node 22 的机器上，从 `git clone` 起按 README 逐条执行：
10 分钟内看到 Vue 登录页并完成注册；未配 key 时有明确提示。实测耗时写进 record。
这是吸引贡献者最有效的一项——比任何视频都重要。

## D8 暴露面威胁模型（tasks 4.x）

| 威胁 | 现状 | 护栏 |
| --- | --- | --- |
| 成本滥用：陌生人注册后建训练，触发大量 LLM 调用 | 无上限 | 每用户每日 LLM 调用上限（按 `llm_calls` 计数），超限返回可读错误且不写半成品 |
| 凭据明文：HTTP 下密码与 Cookie 明文传输 | 无 443 | nginx 反代 + 证书；HTTPS 下 `TRAINER_COOKIE_SECURE=1`；uvicorn 只监听 127.0.0.1 |
| 撞库 / 爆破登录 | 无限流 | 登录、注册、出题、判分、澄清端点按 IP 限流（进程内令牌桶，429 + Retry-After） |
| 开放注册 | 默认开 | `TRAINER_REGISTER_OPEN` 开关（默认 1 保持现状） |
| 越权改他人偏好：`preferences_service` 的读写都不带用户参数，`PUT /api/preferences` 不传当前用户，`submit_answer` 判断连败提示时读的也是全局键 | 偏好键无用户维度 | 偏好键带用户标识；读取顺序为「用户键 → 存量全局键 → 默认值」，写入只写用户键（无需迁移存量） |

单进程部署，令牌桶放进程内存即可；多实例时再换 Redis。限流阈值写成环境变量，给默认值。

## D9 与既有 change、并行会话的关系

- 2026-09-14 的 `public-repo-prep`（record `20260914_chore_public-repo-prep.md`）只做了
  `.gitignore` 里几条求职材料规则，未覆盖本 change 的任何一项，无重叠。
- 与 `ui-redesign`、`training-views-rework`、`grading-consistency` 等在案 change 无产出冲突；
  本 change 不碰它们的范围。
- 判分幂等（并发重复提交）是已知未修问题，**不在本 change**，避免与并行会话撞车。

**冲突避让清单**——并行会话在飞的文件，本 change 一律不碰：

- `src/templates/*.j2`（正在删除）、`src/services/renderer.py`、`tests/test_units.py`
- `web/src/App.vue`、`web/src/api_wizard.ts`
- `docs/architecture.md`、`workspace/record/share-gate-confirmations.md`

**改动纪律**：开工前先 `git status --short` 确认上述清单；提交只 `git add` 自己改的文件；
`.gitignore`、`src/api/app.py` 是共改热区，编辑前重读最新内容。

**禁止触碰项**：判分口径、排期、达标条件；`data/trainer.db`；`git push --force`、
`git filter-repo`、`git reset --hard`；并行会话的未提交改动。
