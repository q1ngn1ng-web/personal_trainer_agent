# 2026-10-26 · 测试隔离修复 + 日常训练要点接线 + 部署栈源码归位

> 对应审计：《项目成熟度审计与补齐路线》（for-work/03-项目导学）Trainer P0-1 部分、P0-2 核查、P0-3 收口。

## 一、做了什么

### 1. 修复长期失败的测试（test_plan_page）

`test_task_shows_question_and_accepts_answer` 的设计前提是「LLM 不可用」，但服务器配了真实
DEEPSEEK_API_KEY，真实判分返回 `graded_by='llm'` 与断言 `'unavailable'` 冲突。
修法：测试内 patch `answer_service.complete` 抛异常，环境无关地模拟 LLM 不可用。
（`5766752`）

### 2. 审计 P0-2 核查结论：**误报**

`explanation_service` 传 `schema=None` 被判为「按需解析永远失败」。实际 `_run_once` 按
prompt 名自动查 `SCHEMA_REGISTRY`，与调用方参数无关——真实链路可正常解析。
新增 `tests/test_explanation_service.py`：打桩 `_call_api` 返回合法 JSON、走真实
`complete()` 解析路径，把该契约钉死（2 用例，含落库断言）。

### 3. 审计 P0-3 收口：日常训练接入要点出题与判分（`5d2184b`）

此前仅测验链路按要点判分，日常训练 `ensure_question` 丢弃要点、`_grade_answer` 只读二元
verdict。现在：

- 出题时要点清单随题固化到 `plan_items.points`（判分只引用不再生成）；
- 判分时模型只做逐条四态判定，pass/fail 由 `grading_service` 规则层算出
  （覆盖率×正确性 + 必答否决 + 阈值 0.8）——**模型整体 verdict 无权直接定对错**，
  测试覆盖「必答要点缺失时模型说 pass、规则层判 fail」；
- `practice_attempts` 落 `score` / `point_results`，客观表现可解释；
- 无要点（旧数据/模型没吐）自动退回二元判定，与接线前行为一致。

### 4. 部署栈源码归位（审计 P0-1 第一步，`98bea60`）

8501 的 trainer-api 重启后崩溃复现：`src/api/*.py` 只在 `feat/enterprise-org-roles`
分支，磁盘上仅剩 `__pycache__`，服务一直靠常驻进程续命。已把 `src/api/` 与
权限/认证/组织/连接 6 个模块检出进主线并提交；服务重启后恢复（首页 200）。
`web/` 前端源码归位方案（合并分支 or 重建）待决策，dist 暂不入库。

## 二、验证

- 全量测试：`261 passed, 1 skipped, 30 subtests passed`（修复前 252 passed + 1 failed）
- 服务：`systemctl restart trainer-api` 后 active，`/` → 200，`/api/auth/login` → 401（空凭据）
- 迁移：生产库 `plan_items` 已自动补 `points` 列（init_db 内置 migrate）

## 三、遗留

- RAG 项目 P0-4（item_name 清理跨文件误删）、P0-1/P0-2（对象级授权）未动；
- KG 占位实现 vs 降级、web 前端源码归位，两个决策待用户拍板；
- 审计 P1-2（CI/测试统一隔离 DB_PATH）只修了单点，未做全局夹具。
