# goal-clarification-confirm · 设计文档

## Context

### 背景

现有创建流程是"输入主题 → 具体性校验 → 关键词白名单 → 基线诊断 → 按十要素模板生成 10 份文件"，
**全程没有让用户确认的环节**，而且第一步只做二值判定，不能追问。

### 当前状态

- `src/services/topic_validation.py` 只判断主题是否"具体到可验证"，输出通过/不通过，没有澄清能力
- `trainings` 表状态：`created` / `active` / `paused` / `archived` / `failed`
- 目标信息没有结构化字段，只以自由文本 `topic` 保存
- 训练路径目前是固定十要素模板，没有目标输入可依赖

### 约束

- 沿用 ADR-0001：**LLM 只产出草案与信号，状态迁移由规则层执行**
- 所有 LLM 输出走 `src/llm/client.py` 统一客户端 + JSON Schema 校验 + `llm_calls` 审计
- 不新增第三方依赖；UI 沿用 Streamlit
- `data/trainer.db` 不提交 git，迁移脚本必须可重复执行

### 利益相关方

- 用户本人（自用 + 面试演示）

## Goals / Non-Goals

**Goals:**

- 用户用一句话描述学习内容，系统能追问并产出**结构化目标草案**
- 用户能确认或修改草案；确认后的目标有快照，可追溯
- 未确认的目标不会进入关键词生成与文件生成

**Non-Goals:**

- 不做资料来源选择、训练路径动态生成、达标判定（后续 change）
- 不做语音 / 面部等多模态输入

## Decisions

### D1 目标草案包含 5 个必填字段

| 字段 | 含义 | 示例 |
|---|---|---|
| `content` | 学习内容（保留用户原话） | 英语虚拟语气 |
| `level` | 目标等级 | 能在写作里正确使用（不是"了解"） |
| `horizon` | 周期 | 2 周 |
| `daily_budget` | 每日可投入时长 | 30 分钟 |
| `acceptance` | 验收标准 | 10 句改错题正确率 ≥ 80% |

任一本字段缺失时继续追问；单次会话追问上限 **5 轮**。超限则输出"部分字段由系统假设"的草案，
并在草案里逐字段标注来源是「用户提供」还是「系统假设」。

### D2 状态机

```
draft ──提交描述──▶ pending_confirm ──用户确认──▶ confirmed ──生成──▶ active
                         │  ▲
                         └──┘ 用户提出修改，重新生成草案
任意状态 ──放弃──▶ archived
```

`created` 保留给历史数据兼容，新流程不再写入该状态。

### D3 确认必须落库，不能只是 UI 复选框

如果确认只存在于界面，后续任何一次页面刷新或重新生成都可能让"用户确认的目标"与"实际训练的目标"
发生漂移，那么第 7、8 步的评测结果就无法归因——回答不了"这次达标是按哪个目标算的"。
因此确认是一次**状态迁移 + 快照写入**，由规则层执行。

### D4 LLM 输出契约（不让 LLM 决定流程）

新增用途 `goal_clarification`，Schema 输出：

```json
{
  "draft": { "content": "", "level": "", "horizon": "", "daily_budget": "", "acceptance": "" },
  "field_sources": { "level": "user | inferred" },
  "missing_fields": ["horizon"],
  "follow_up_question": "你打算用多久完成？",
  "confidence": 0.0
}
```

**是否继续追问由规则层判定**（`missing_fields` 非空 且 轮次 < 5），不由 LLM 决定停不停。
缺少必填字段时 LLM 失败降级为表单式追问模板（缺哪个字段问哪个），流程不阻塞。

### D5 快照存在 `trainings`，不新建表

新增字段：`goal_json`（含 `schema_version`）、`goal_confirmed_at`、`clarification_rounds`。
当前一个训练只有一个目标；等出现"一训练多目标"再拆独立表。

## Risks / Trade-offs

| 风险 | 影响 | 处理方式 |
|---|---|---|
| 5 轮上限截断真实需要的澄清 | 目标质量下降 | 草案逐字段标注"用户提供 / 系统假设"，允许用户改 |
| 目标 JSON 结构后续变更 | 历史快照无法解析 | 快照内带 `schema_version`，读取时按版本兼容 |
| LLM 追问质量不稳定 | 用户答非所问 | 降级为表单式追问模板；追问必须指明缺哪个字段 |
| 状态迁移写错导致训练卡住 | 用户无法继续 | 状态迁移写成纯函数并单测；非法迁移直接拒绝并记录 |
| 与历史 `created` 状态记录冲突 | 老数据无法进入新流程 | 读取时把 `created` 视为 `draft` 兼容处理 |

## 关联决策记录

- `workspace/decisions/ADR-0001-llm负责语义-规则负责状态.md`（本设计沿用其约束）
- `workspace/decisions/ADR-0004-目标澄清用多轮追问与显式确认状态.md`（本 change 的选型依据）

## 验收方式

- `uv run pytest -q`：状态迁移与目标字段校验的纯函数单测全绿
- 手动场景：输入"我想学虚拟语气" → 系统至少追问 `horizon` 与 `acceptance` → 确认后
  `trainings` 记录 `goal_json` 与 `goal_confirmed_at`
- 指标：澄清完成率、平均追问轮次、草案被修改比例——**实现后测量，当前标【待验证】**
