# 20260919 · chore · 建立「ADR + 规格 + 证据 + 门禁」文档工作流

## 变更摘要

把原先散落在 AGENTS.md 和各处文档里的"为什么这么做"，拆成四类固定载体，并给 OpenSpec 补上项目上下文与生成规则。

四层结构：

| 层 | 载体 | 回答的问题 |
|---|---|---|
| 决策 | `workspace/decisions/`（MADR 格式 ADR） | 为什么选 A 不选 B |
| 规格与验收 | `workspace/store/`（OpenSpec） | 要做什么、怎么算做到 |
| 证据 | `workspace/evidence/` | 做完到底有没有效果 |
| 变更记录 | `workspace/record/` | 这次改了什么 |

### 具体动作

1. **`AGENTS.md` 新增第 5 节「文档与决策工作流（四件套）」**，含三块内容：
   - 四件套对应表（哪类信息写到哪里）
   - **开工前读取分级**：每次必读（本文件 + 当前 change 的 `proposal.md`）／按任务触发（改 LLM、改调度、改 DB 各读不同文档）／**不要整体加载**（`workspace/record/` 历史全文、evidence 明细、`docs/` 理论资料、`data/`）
   - **硬性门禁**：选型先写 ADR、规格走 propose→apply→archive 闭环、数字必须有出处、收尾三件事
   - 目录约定表新增 `workspace/decisions/`、`workspace/evidence/`、`workspace/prompts/` 三行

2. **`workspace/store/openspec/config.yaml` 从空模板填充为实际配置**：
   - `context`：项目定位、技术栈、架构分层、三条核心设计原则（LLM 只管语义 / Schema 校验与 `llm_calls` 审计 / 机械指标走 SQL）、uv 运行约定
   - `rules`：`proposal` 必须含 Non-goals 与备选方案、验收标准必须可执行；`design` 必须指向对应 ADR；`tasks` 必须写验收方式、单个任务 ≤2 小时

3. **新建 `workspace/decisions/`**：一页 ADR 模板 + 索引，并按既有设计依据回填首批 3 条 ADR：
   - `ADR-0001` LLM 负责语义，规则负责状态迁移
   - `ADR-0002` 评测用 strict/fuzzy 组合分，暂不上 embedding
   - `ADR-0003` 训练主题用 `topic_path` 分层，暂不建分类表
   每条含"备选方案表 + 放弃理由 + 代价 + 验证方式 + 重评估触发条件"。

4. **新建 `workspace/evidence/`**：证据三条硬规则（口径/样本/时间窗口、必须指向脚本、未实测标 `【待验证】`）、命名与记录模板、优先补的三类证据。

5. **新建 `workspace/prompts/`**：一套可复制到其他项目的引导提示词（`codex-workflow-bootstrap.md`：先侦察→问三问→落四件套→交付三样）和日常固定口令（`codex-daily-prompts.md`）。

## 影响范围

- 纯文档与工作流配置，**无任何代码逻辑改动**。
- 后续所有 OpenSpec proposal 会自动带上 Non-goals、备选方案与可执行验收标准；技术选型会先落 ADR 再写代码。
- 量化结论从此必须能在 `workspace/evidence/` 找到出处，避免出现无法复现的数字。

## 待办（本次未做，已记录）

1. `workspace/store/openspec/specs/` 下 6 个 spec 的 `Purpose` 仍是归档时生成的 `TBD`，需各补一句话。
2. `ADR-0002` 的阈值校准、`workspace/evidence/` 的指标当前均为 `【待验证】`，需建人工标注集后回填。
3. `workspace/decisions/` 只回填了 3 条，SQLite vs PostgreSQL（原 5.8 节）等决策待补。

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `AGENTS.md` | 新增第 5 节 + 目录约定 3 行 |
| `workspace/store/openspec/config.yaml` | 从空模板填充 `context` 与 `rules` |
| `workspace/decisions/README.md`、`ADR-0000-template.md` | 新增 |
| `workspace/decisions/ADR-0001~0003-*.md` | 新增 |
| `workspace/evidence/README.md` | 新增 |
| `workspace/prompts/README.md`、`codex-workflow-bootstrap.md`、`codex-daily-prompts.md` | 新增 |

## 关联 OpenSpec change id

无（本次为工作流与文档规范调整，未改动任何 spec 要求或 change）。
