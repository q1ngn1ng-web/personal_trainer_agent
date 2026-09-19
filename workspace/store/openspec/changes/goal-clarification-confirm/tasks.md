# goal-clarification-confirm · 任务清单

> 按依赖顺序编号。每个任务写明验收方式。涉及选型的任务，ADR 未落盘视为未完成。

## 1. 数据层改造

- [ ] 1.1 `src/db/tables.sql` 为 `trainings` 增加字段：`goal_json`、`goal_confirmed_at`、`clarification_rounds`
  - 验收：`uv run python -m src.cli init-db` 后，`.schema trainings` 能看到三个新字段
- [ ] 1.2 增加可重复执行的迁移逻辑（老库补字段不丢数据；`created` 状态读取时按 `draft` 兼容）
  - 验收：对已有 `data/trainer.db` 跑一次迁移，训练列表条数与迁移前一致
- [ ] 1.3 `src/db/models.py` 的 `Training` dataclass 同步新字段
  - 验收：`uv run pytest -q` 通过

## 2. 目标参数定义与合并（纯函数，先写测试）

- [ ] 2.1 定义五个字段的取值空间与默认值：`horizon`（1 周 / 2 周 / 1 个月 / 自定日期）、
  `weekly_frequency`（2 / 3 / 5 / 7 次）、`daily_budget`（10 / 20 / 30 / 45 / 60 分钟）、
  `level`（了解 / 会用 / 熟练 / 能讲清）、`acceptance`（自由文本）
  - 验收：默认值为 2 周 / 每周 5 次 / 每次 30 分钟，单测断言
- [ ] 2.2 实现参数合并函数，优先级为 `ui_select > user_reply > default > inferred`
  - 验收：单测断言 UI 给定值不会被 LLM 输出覆盖
- [ ] 2.3 实现 `field_sources` 记录（`ui_select` / `user_reply` / `default` / `inferred`）
  - 验收：单测断言每个字段都有来源标记

## 3. 状态机

- [ ] 3.1 实现状态迁移：`draft → pending_confirm → confirmed → active`，支持
  `pending_confirm → pending_confirm`（改需求），任意状态 → `archived`
  - 验收：单测覆盖合法迁移，并断言非法迁移被拒绝（如 `confirmed → draft`）
- [ ] 3.2 服务层暴露查询：当前训练是否允许进入生成阶段（仅 `confirmed`）
  - 验收：单测断言 `draft` / `pending_confirm` 返回 False

## 4. LLM 用途 goal_clarification

- [ ] 4.1 `src/llm/schema.py` 新增 `goal_clarification` 的 JSON Schema（draft 五字段、
  field_sources、missing_fields、follow_up_question、confidence）
  - 验收：用两条样本（完整 / 缺语义字段）跑校验，均通过
- [ ] 4.2 `src/llm/prompts.py` 新增 `GOAL_CLARIFICATION_PROMPT` 与版本常量 `v1.0.0`，
  **prompt 必须接收前端已选参数作为既定输入**（不得留空让模型自由假设）
  - 验收：`llm_calls.prompt_version` 落库为 `v1.0.0`；检查 prompt 文本确实包含用户所选参数
- [ ] 4.3 `src/llm/fallback.py` 增加降级：按缺失的语义字段生成表单式追问模板
  - 验收：模拟 LLM 连续失败 3 次，流程不中断且页面能展示追问表单

## 5. 澄清服务

- [ ] 5.1 新增 `src/services/goal_clarification_service.py`：输入用户描述 + 前端参数 → 调用 LLM →
  返回草案、缺失字段与来源标记
  - 验收：输入「我想学虚拟语气」且不选参数，返回的 `missing_fields` 只包含语义字段
- [ ] 5.2 追问控制由规则层实现：软限 2 轮（给建议值 + 提示可采用）、硬限 3 轮（强制收口）
  - 验收：单测模拟 2 轮后触发建议值；3 轮后断言字段来源被标为 `inferred`
- [ ] 5.3 确认动作：写 `goal_json`（含 `field_sources` 与 `schema_version`）、`goal_confirmed_at`，
  状态迁移到 `confirmed`
  - 验收：确认后查询数据库能看到完整快照、各字段来源与时间戳

## 6. UI 改造

- [ ] 6.1 `src/ui/page_new_training.py` 改为三步：**① 描述 + 参数选择 → ② 追问（≤2 轮）→ ③ 草案确认**
  - 验收：手动跑一遍，不选参数也能走到确认页；追问不超过 2 轮
- [ ] 6.2 参数控件带默认值，并在草案页把 `inferred` 字段标出「系统建议」
  - 验收：界面能看到建议标识，且修改后 `field_sources` 变为 `user_reply`
- [ ] 6.3 未确认时隐藏「生成训练文件」入口
  - 验收：`draft` / `pending_confirm` 状态下页面提示「请先确认训练目标」
- [ ] 6.4 首页训练列表展示 `draft` / `pending_confirm` 状态的训练，并提供「继续澄清」入口
  - 验收：刷新页面后未完成的训练仍可继续，澄清轮次不丢

## 7. 收尾

- [ ] 7.1 补单测并跑通 `uv run pytest -q`
- [ ] 7.2 手动验收记录写进 `workspace/evidence/`（澄清完成率、平均追问轮次、默认值采用率、
  事后修改率；未跑出的标【待验证】）
  - 验收：`workspace/evidence/` 下新增一份带口径与样本的 md
- [ ] 7.3 写 `workspace/record/` 变更记录，命名符合 `YYYYMMDD_feat_简短描述.md`
- [ ] 7.4 `openspec validate --all --store store` 通过
- [ ] 7.5 archive 本 change，并把 `goal-clarification` spec 的 `Purpose` 从 TBD 改成一句话
