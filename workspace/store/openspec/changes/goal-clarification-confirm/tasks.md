# goal-clarification-confirm · 任务清单

> 按依赖顺序编号。每个任务写明验收方式。涉及选型的任务，ADR 未落盘视为未完成。

## 1. 数据层改造

- [ ] 1.1 `src/db/tables.sql` 为 `trainings` 增加字段：`goal_json`、`goal_confirmed_at`、`clarification_rounds`
  - 验收：`uv run python -m src.cli init-db` 后，`sqlite3 data/trainer.db ".schema trainings"` 能看到三个新字段
- [ ] 1.2 增加可重复执行的迁移逻辑（老库补字段不丢数据；`created` 状态读取时按 `draft` 兼容）
  - 验收：对已有 `data/trainer.db` 跑一次迁移，训练列表条数与迁移前一致
- [ ] 1.3 `src/db/models.py` 的 `Training` dataclass 同步新字段
  - 验收：`uv run pytest -q` 通过

## 2. 状态机（纯函数，先写测试）

- [ ] 2.1 实现状态迁移函数：`draft → pending_confirm → confirmed → active`，支持 `pending_confirm → pending_confirm`（改需求），任意状态 → `archived`
  - 验收：新增单测覆盖合法迁移，并断言非法迁移被拒绝（如 `confirmed → draft`）
- [ ] 2.2 在服务层暴露查询：当前训练是否允许进入生成阶段（仅 `confirmed`）
  - 验收：单测断言 `draft` / `pending_confirm` 返回 False

## 3. LLM 用途 goal_clarification

- [ ] 3.1 `src/llm/schema.py` 新增 `goal_clarification` 的 JSON Schema（draft 五字段、field_sources、missing_fields、follow_up_question、confidence）
  - 验收：用两条样本（完整 / 缺字段）跑校验，均通过
- [ ] 3.2 `src/llm/prompts.py` 新增 `GOAL_CLARIFICATION_PROMPT` 与版本常量 `v1.0.0`
  - 验收：调用后 `llm_calls.prompt_version` 落库为 `v1.0.0`
- [ ] 3.3 `src/llm/fallback.py` 增加降级：按缺失字段生成表单式追问模板
  - 验收：模拟 LLM 连续失败 3 次，流程不中断且页面能展示追问表单

## 4. 澄清服务

- [ ] 4.1 新增 `src/services/goal_clarification_service.py`：输入用户描述 → 调用 LLM → 返回草案与缺失字段
  - 验收：输入「我想学虚拟语气」，返回的 `missing_fields` 非空
- [ ] 4.2 追问轮次控制由规则层实现（上限 5 轮），超限输出带「系统假设」标注的草案
  - 验收：单测模拟 5 轮仍缺字段，断言对应字段来源被标为 `inferred`
- [ ] 4.3 确认动作：写 `goal_json`（含 `schema_version`）、`goal_confirmed_at`，状态迁移到 `confirmed`
  - 验收：确认后查询数据库能看到完整快照与时间戳

## 5. UI 改造

- [ ] 5.1 `src/ui/page_new_training.py` 改为「描述 → 追问 → 草案确认」三步，未确认时隐藏后续生成入口
  - 验收：手动跑一遍，输入模糊描述后出现追问，未点确认时看不到「生成训练文件」入口
- [ ] 5.2 首页训练列表展示 `draft` / `pending_confirm` 状态的训练，并提供「继续澄清」入口
  - 验收：刷新页面后未完成的训练仍可继续，澄清轮次不丢

## 6. 收尾

- [ ] 6.1 补单测并跑通 `uv run pytest -q`
- [ ] 6.2 手动验收记录写进 `workspace/evidence/`（澄清完成率、平均追问轮次、草案修改比例；未跑出的标【待验证】）
  - 验收：`workspace/evidence/` 下新增一份带口径与样本的 md
- [ ] 6.3 写 `workspace/record/` 变更记录，命名符合 `YYYYMMDD_feat_简短描述.md`
- [ ] 6.4 `openspec validate --all --store store` 通过
- [ ] 6.5 archive 本 change，并把 `goal-clarification` spec 的 `Purpose` 从 TBD 改成一句话
