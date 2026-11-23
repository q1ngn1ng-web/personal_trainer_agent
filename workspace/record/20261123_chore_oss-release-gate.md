# 20261123 · chore · 登记 oss-release-gate（开源发布门禁）——设计评审 + 开播前就绪度审计

## 变更摘要

- 登记 openspec change **`oss-release-gate`**（仅提案，未实施；`openspec validate` 与
  `--strict` 均通过，0/31 任务）。本会话**不写业务代码**，实施移交另一会话。
- 来源：2026-11-23 应作者要求做的一次项目设计评审——为 B 站系列视频与 GitHub 开源
  评估就绪度，并回应"它没有被设计成 agent、没有记忆机制与上下文管理"的担忧。
- 任务分四段：1.x 录制前必须绿（3 个演示路径上的缺陷）；2.x 公开仓库前必须绿
  （依赖、README、AGENTS.md、LICENSE、私人材料出库）；3.x 一周内（CI、CONTRIBUTING 等）；
  4.x 条件触发（公网暴露面护栏）。第 0 节 4 项为作者决策。

## 审计发现（全部实测，复现命令见 change 的 design D0）

**定位层面**

- 项目不是 agent：`src`、`scripts` 内工具调用与编排框架关键字零命中；
  `src/llm/client.py` 每次调用都是"固定 system + 单条 user"的单次结构化调用，
  共 15 个注册提示词、17 个调用点。
- 记忆并非没有：`memory_service.py` 开篇即写明"不产生原始对话、记忆是库里的持久化状态"，
  `practice_attempts` 为唯一事实源、`learner_knowledge` 为可重放重建的派生层。
  真正缺的是**跨训练、用户级**的记忆——所有记忆表都以 `training_id` 为作用域。
- 上下文管理确实没有：无统一组装层；出题只喂按序前 2 片、截断 600 字符，无检索。

**缺陷（已写入 change）**

| 缺陷 | 位置 | 影响 |
| --- | --- | --- |
| 会话小结 500 | `session_summary.py:99` 查 `plan_items` 上不存在的 `knowledge_point` / `title` | 当天练过日常题必 500；线上 11-23 17:09 两次 |
| 测试绕开出错分支 | `tests/test_coach_memory.py` 用例的作答不带 `plan_id` | 全绿但线上炸 |
| 澄清追问原文为空 | `goal_clarification_service.py:296` | 下一轮 LLM 看不到自己上一轮问了什么 |
| 衰减多算时区偏移 | `learner_service.py:37,151` | 东八区下流逝时间多算 8 小时 |
| "当天"口径分叉 | `session_summary.py:89` 用 SQLite `localtime`，未走 `local_today()` | 部署在 UTC 服务器时跨日错位 |
| 提示词错别字 | `src/llm/prompts.py:36` "哟怒火" | 已随 7481b45 进主干 |
| 用户偏好全站共享 | `preferences_service.py` 的读写都不带用户参数，`PUT /api/preferences` 不传当前用户，`answer_service.py:626` 读的也是全局键 | 任一账号改动「连败提示 / 每日时长 / 题型倾向」，所有用户一起变 |

**开源就绪度**

- README 的 Quick Start 仍是 `streamlit run src/main.py`（一代 UI）；`requirements.txt`
  无 fastapi / uvicorn / python-multipart / pytest；`scripts/e2e_full_flow.py` 跑的是一代流程。
- 一代代码约 4,043 行在 Vue 产品里不可达（`app.py` 对 6 个一代服务模块引用数为 0）。
- 根目录无 LICENSE、无 `.github/`、无 pyproject。
- 被跟踪的私人材料：`workspace/面试/` 7 个、`workspace/record/` 90 篇、
  `workspace/evidence/判分一致性标注-工作表-真实数据.csv`、`data/` 下 1 个 PDF。
- git 全历史无密钥形态字符串；`.env` 与 `data/trainer.db` 从未入库。
- 暴露面：`0.0.0.0:8501` 明文 HTTP、无 443、ufw inactive、注册公开、无限流。

## 排查过程

1. 读 LLM 统一客户端与全部提示词 → 确认调用形态（单次、结构化、规则层掌控状态迁移）。
2. 读 `memory_service` / `learner_service` / `answer_service` / `session_summary` /
   `goal_clarification_service` → 逐个核对记忆的写入点与消费点。
3. 跑全量测试取基线（415 passed / 6 skipped / 1 failed，6 分 13 秒；失败项为并行会话
   正在删除的 renderer 模板）。
4. 翻 3 天服务日志 → 发现 `session-summary` 两次 500，取完整堆栈定位到行；
   只读打开生产库核对 `plan_items` 列清单与带 `plan_id` 的作答数（20 条）。
5. 审计被跟踪文件与全部历史提交。

**两个踩坑**

- `git ls-files` 默认把中文路径转成八进制转义，按中文路径 grep 会得到 0——
  必须用 `git -c core.quotepath=false ls-files`。第一次统计因此把 `workspace/面试/`
  和 `data/` 误判为"未跟踪"。
- 派出的三路后台审计子任务在限速导致运行环境重启后全部丢失、没有产出；
  关键事实改由定向命令逐项亲测。长审计应边查边落盘，不把结论只留在后台任务里。

## 验证

- `cd workspace && openspec validate oss-release-gate --store store` → valid；
  加 `--strict` → valid；`openspec list` 显示 0/30 tasks。
- 未运行实施后测试（本 change 尚未实施）。实施前基线见上。

## 纪律备注

- 本会话零业务代码改动；只新增 change 目录四件套与本记录。
- 未触碰并行会话在飞文件（`src/templates/*.j2`、`renderer.py`、`tests/test_units.py`、
  `web/src/App.vue`、`web/src/api_wizard.ts`、`docs/architecture.md`、
  `workspace/record/share-gate-confirmations.md`）。
- 未对 `data/trainer.db` 做任何写操作（只读方式打开核对表结构）。
- 未重写历史、未 force push；公开仓策略与许可证类型留待作者拍板。
