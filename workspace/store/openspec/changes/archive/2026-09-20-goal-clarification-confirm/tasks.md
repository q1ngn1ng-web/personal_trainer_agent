# goal-clarification-confirm · 任务清单

> 按依赖顺序编号。每个任务写明验收方式。涉及选型的任务，ADR 未落盘视为未完成。
> 本 change 只做**澄清与目的确认**；投入参数（周期 / 频次 / 时长）一律留到下一次 change。

## 1. 数据层改造

- [x] 1.1 `src/db/tables.sql` 为 `trainings` 增加字段：`goal_json`、`goal_confirmed_at`、`clarification_rounds`
  - 验收：`uv run python -m src.cli init-db` 后，`.schema trainings` 能看到三个新字段
- [x] 1.2 增加可重复执行的迁移逻辑（老库补字段不丢数据；`created` 状态读取时按 `draft` 兼容）
  - 验收：对已有 `data/trainer.db` 跑一次迁移，训练列表条数与迁移前一致
- [x] 1.3 `src/db/models.py` 的 `Training` dataclass 同步新字段
  - 验收：`uv run pytest -q` 通过

## 2. 目的字段定义与来源标记

- [x] 2.1 定义三个目的字段的取值：`content`（自由文本）、`level`（了解 / 会用 / 熟练 / 能讲清）、
  `acceptance`（结构化判据，见 2.1b）
  - 验收：单测断言 `level` 只接受枚举内取值
- [x] 2.1b 定义 `acceptance` 的两种形状（`quantitative` 含 metric/target/unit；`qualitative` 含
  statement/check），并实现"纯主观形容词不算完成"的校验
  - 验收：单测断言「比较熟练」被判为未完成，「正确率 ≥ 80%」被判为完成
- [x] 2.2 实现 `field_sources` 记录（`user_input` / `user_reply` / `inferred`）
  - 验收：单测断言每个字段都有来源标记
- [x] 2.3 实现合并函数：LLM 输出与用户值冲突时保留用户值，并记录一条冲突日志
  - 验收：单测断言 LLM 不能覆盖用户已确认的字段

## 3. 状态机

- [x] 3.1 实现状态迁移：`draft → pending_confirm → confirmed`，支持 `pending_confirm → pending_confirm`（改目的），
  任意状态 → `archived`；`confirmed` 之后由下一次 change 接续
  - 验收：单测覆盖合法迁移，并断言非法迁移被拒绝（如 `confirmed → draft`）
- [x] 3.2 服务层暴露查询：当前训练是否允许进入生成阶段（仅 `confirmed`）
  - 验收：单测断言 `draft` / `pending_confirm` 返回 False

## 4. LLM 用途 goal_clarification

- [x] 4.1 `src/llm/schema.py` 新增 `goal_clarification` 的 JSON Schema（draft 三字段、field_sources、
  missing_fields、follow_up_question、confidence）
  - 验收：用两条样本（完整 / 缺 `acceptance`）跑校验，均通过
- [x] 4.2 `src/llm/prompts.py` 新增 `GOAL_CLARIFICATION_PROMPT` 与版本常量 `v1.0.0`
  - 验收：`llm_calls.prompt_version` 落库为 `v1.0.0`
- [x] 4.3 `src/llm/fallback.py` 增加降级：按缺失的语义字段生成表单式追问模板
  - 验收：模拟 LLM 连续失败 3 次，流程不中断且页面能展示追问表单

## 5. 澄清服务

- [x] 5.1 新增 `src/services/goal_clarification_service.py`：输入用户描述 → 调用 LLM →
  返回草案、缺失字段与来源标记
  - 验收：输入「我想学虚拟语气」，返回的 `missing_fields` 只可能是 `level` 或 `acceptance`
- [x] 5.2 追问控制由规则层实现：软限 2 轮（给建议值 + 提示可采用）、硬限 3 轮（强制收口）
  - 验收：单测模拟 2 轮后触发建议值；3 轮后断言字段来源被标为 `inferred`
- [x] 5.3 确认动作：写 `goal_json`（含 `field_sources` 与 `schema_version`）、`goal_confirmed_at`，
  状态迁移到 `confirmed`
  - 验收：确认后查询数据库能看到完整快照、各字段来源与时间戳
- [x] 5.4 用户主动写出投入参数时（如「两周内、每天 30 分钟」），只作为描述保留，不因此追问
  - 验收：单测断言这种情况不产生投入参数追问

## 6. UI 改造

- [x] 6.1 `src/ui/page_new_training.py` 改为三步：**① 描述 → ② 追问（≤2 轮）→ ③ 目的确认**
  - 验收：手动跑一遍，追问不超过 2 轮
- [x] 6.2 澄清页**不得出现**周期 / 每周次数 / 每次时长控件
  - 验收：页面元素检查，只保留内容描述与追问
- [x] 6.3 草案页把 `inferred` 字段标出「系统建议」
  - 验收：界面能看到建议标识，且用户修改后 `field_sources` 变为 `user_reply`
- [x] 6.4 未确认时隐藏「生成训练文件」入口
  - 验收：`draft` / `pending_confirm` 状态下页面提示「请先确认训练目标」
- [x] 6.5 首页训练列表展示 `draft` / `pending_confirm` 状态的训练，并提供「继续澄清」入口
  - 验收：刷新页面后未完成的训练仍可继续，澄清轮次不丢

## 7. 交接给下一次 change（训练路径生成）

- [x] 7.1 确保 `confirmed` 状态的训练能通过一个明确入口进入路径阶段（本 change 只留入口，不实现生成）
  - 验收：`confirmed` 训练在界面上有「生成训练路径」按钮位，点击提示「即将支持」
- [x] 7.2 在下一次 change 的 proposal 里复用本 change 的输出口径：路径生成只读已确认的 `goal_json`
  - 验收：proposal 中写明该输入约定

## 8. 收尾

- [x] 8.1 补单测并跑通 `uv run pytest -q`
- [x] 8.2 手动验收记录写进 `workspace/evidence/`（澄清完成率、平均追问轮次、目的草案修改率；
  未跑出的标【待验证】）
  - 验收：`workspace/evidence/` 下新增一份带口径与样本的 md
- [x] 8.3 写 `workspace/record/` 变更记录，命名符合 `YYYYMMDD_feat_简短描述.md`
- [x] 8.4 `openspec validate --all --store store` 通过
- [x] 8.5 archive 本 change，并把 `goal-clarification` spec 的 `Purpose` 从 TBD 改成一句话
