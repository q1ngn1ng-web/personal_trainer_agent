# 交接说明（HANDOFF）

> 更新日期：2026-09-20
> 当前状态：个人版第一个 change 已实现并归档；整条链路的规格设计已完成

---

## 1. 项目目标与技术栈

**目标（个人版）**：意图驱动的自适应训练 AI 教练。用户用一句话描述想学什么，系统澄清目标、
定位理解边缘、生成训练路径，再通过训练与反馈推进到达标。

**完整链路**：

```
描述学习内容 → AI 澄清目标 → 用户确认 → 选资料来源 → 定位理解边缘
→ 生成训练路径 → 训练 → 反馈（四失 + 测验）→ 达标
```

**技术栈**：Python 3.12、Streamlit、SQLite（`data/trainer.db`）、LLM API（DeepSeek）、
Jinja2、tenacity、uv。规格与变更走 OpenSpec（store id = `store`）。

**企业版**：组织 / 角色 / 培训任务已设计但**后置**（ADR-0019），与个人版同一条代码线，
差异用 `profile` 开关承载而不是开分支（ADR-0020）。

---

## 2. 已归档 change

| change | 状态 | 产出 |
|---|---|---|
| `goal-clarification-confirm` | **已 apply + 已归档**（`2026-09-20`） | 目标澄清链路：描述 → 追问 → 确认；`specs/goal-clarification/` + 修改 `trainer-generation` |

归档件在 `workspace/store/openspec/changes/archive/2026-09-20-goal-clarification-confirm/`。

**已实现的文件**：

| 层 | 文件 |
|---|---|
| 领域（纯函数） | `src/core/goal.py` |
| 服务 | `src/services/goal_clarification_service.py` |
| LLM | `src/llm/schema.py`、`prompts.py`、`fallback.py`（新增用途 `goal_clarification`） |
| 数据 | `src/db/tables.sql`、`migrate.py`、`models.py`、`queries.py` |
| UI | `src/ui/page_new_training.py`（第 1 步已改造） |
| 测试 | `tests/test_goal_clarification.py`、`tests/test_goal_flow.py` |

---

## 3. 剩余 change 及建议顺序

| 顺序 | change | 做什么 | 任务数 |
|---|---|---|---|
| 1 | `training-source-selection` | 资料来源：四种来源（AI 生成 / 上传文件 / 粘贴文本 / 网络 URL）、解析切片、FTS5、训练项回指 | 33 |
| 2 | `understanding-edge-assessment` | 理解边缘定位：逐知识点三态（已掌握 / 边缘 / 未达）、分层自适应探测 | 30 |
| 3 | `training-path-generation` | 训练路径：骨架一次生成 + 阶段细节滚动生成、预算硬约束、难度依据 | 29 |
| 4 | `training-execution-feedback` | 执行与反馈：四失信号 → 动作、定期测验、三级达标判据 | 33 |
| 5 | `org-and-roles` | 组织、角色、培训任务（**已后置**，规格保留备用） | 29 |

**依赖关系**：1 → 2 → 3 → 4 是链路顺序；5 与个人版同线但后置。

**当前建议**：下一步做 1，**不急着写**——先按本文档第 4 节把设计约束对齐。

---

## 4. 关键设计约束（违反就会返工）

1. **三个目标字段是「值」不是「布尔」**
   `content` / `level` / `acceptance` 存具体取值；"用户已确认"由 `status=confirmed` 与
   `goal_confirmed_at` 承载。只存 true/false 会让下游不知道确认了什么。
2. **验收标准必须可判定**
   量化判据要 `metric` + `target`；质性判据要可观察并带检查方式；
   **纯主观形容词（"比较熟练"）判为不合格**，继续追问或由系统给建议值。
3. **AI 不得覆盖用户值**
   合并优先级写死：用户显式值 > AI 输出。冲突时丢弃 AI 的值并记日志。
4. **追问双限**
   软限 **2 轮**：给出建议值并提示「可以直接用系统建议，也可以自己改」；
   硬限 **3 轮**：强制收口，缺失字段标 `inferred`。是否继续追问**由规则层判定，不由 LLM 决定**。
5. **LLM 只出内容，规则管状态**（ADR-0001）
   日期、状态迁移、统计一律由确定性代码负责。
6. **澄清阶段不碰投入参数**
   周期 / 每周次数 / 每次时长属于训练路径阶段，澄清 prompt 里已明令禁止询问。
7. **不做多模态情绪识别**（ADR 边界）
   用一键标签 + 可选自由文本，不上面部 / 语音。

---

## 5. 数据库迁移三件套（血的教训）

SQLite 无法修改 CHECK 约束，新增状态值或新枚举必须**重建表**。重建时三件事缺一不可：

```python
conn.isolation_level = None          # 1) 关掉 sqlite3 的隐式事务，避免 DDL 前隐式提交
conn.execute("PRAGMA foreign_keys = OFF")        # 2) 关外键，否则 DROP 旧表触发约束失败
conn.execute("PRAGMA legacy_alter_table = ON")   # 3) 关键！否则 RENAME 会改写其他表的外键引用
conn.execute("BEGIN IMMEDIATE")
... 重建 ...
conn.execute("COMMIT")   # 失败则 ROLLBACK
```

**曾发生的事故**：只关了 `foreign_keys` 没关 `legacy_alter_table`，加上 Python 的隐式提交，
导致 `data/trainer.db` 变成半迁移状态（数据留在 `trainings_old`、子表外键指向它）。
已修复并验证（数据无丢失，`PRAGMA foreign_key_check` = 0）。
完整记录见 `workspace/record/20260920_feat_goal-clarification-confirm.md`。

---

## 6. 常用命令

```bash
# 跑测试（提交前必做）
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q

# 校验所有规格与变更
openspec list --store store
openspec validate --all --store store
openspec status --change <id> --store store

# 启动应用
UV_CACHE_DIR=/tmp/uv-cache uv run streamlit run src/main.py

# 初始化 / 迁移数据库（幂等，可重复执行）
UV_CACHE_DIR=/tmp/uv-cache uv run python -m src.cli init-db

# 归档已完成的 change
openspec archive <change-id> --store store --yes
```

> 本机 `/home/ubuntu/.cache/uv` 只读，所以命令前要带 `UV_CACHE_DIR=/tmp/uv-cache`。
> Streamlit 在沙箱内无法创建 socket，本地启动需要提权。

---

## 7. 关键文件路径

| 类别 | 路径 |
|---|---|
| **决策记录（ADR）** | `workspace/decisions/`（21 条，含模板；索引在 `README.md`） |
| **变更记录** | `workspace/record/`（每次变更一个文件） |
| **效果证据** | `workspace/evidence/`（数字必须有出处，未实测标【待验证】） |
| **面试素材** | `workspace/面试/`（竞品调研、差异化、设计边界，分两层表述） |
| **规格与变更** | `workspace/store/openspec/specs/` 与 `changes/` |
| **已实现代码** | `src/core/goal.py`、`src/services/goal_clarification_service.py`、`src/ui/page_new_training.py` |
| **仓库地图** | `codemap.md`、`docs/architecture.md` |

---

## 8. 验证状态

| 项 | 结果 | 时间 |
|---|---|---|
| 单测 | `73 passed, 17 subtests` | 2026-09-20 |
| 规格校验 | `12 passed, 0 failed` | 2026-09-20 |
| Streamlit 启动 | HTTP 200 / `_stcore/health` = ok | 2026-09-20 |
| UI 全流程（AppTest） | 描述 → 追问 → 软限建议 → 确认 → 状态 `confirmed`，无异常 | 2026-09-20 |
| 数据库迁移 | 3 条训练与全部子表数据无丢失，外键检查 0 问题，幂等 | 2026-09-20 |

**未验证（标【待验证】）**：真实 LLM 下的澄清质量、澄清完成率、平均追问轮次。
本机网络受限，LLM 调用均走了降级路径；接入真实模型后再补。

---

## 9. 下一步

### 9.1 下一件事：`training-source-selection`（已拆两段，接口已冻结）

这个 change 拆成 **阶段 A 静态层**与 **阶段 B 网络层**，接口契约冻结在
`workspace/store/openspec/changes/training-source-selection/design.md` 的「接口冻结」一节。

**开工前只读三份**：`HANDOFF.md`（本文件）→ 该 change 的 `proposal.md` → `design.md` 的接口冻结节。

**关键决策**：阶段 A 建表时就把 `web_url` 枚举与网络字段一起建好（可空、不暴露 UI），
这样阶段 B **完全不用改数据模型或做迁移**，从根上避开最高风险的动作。

### 9.2 会话分工：设计用长上下文，实现用短上下文

| 角色 | 做什么 | 会话 |
|---|---|---|
| **high（长上下文）** | 拆解、冻结接口、判断停不停、修架构问题 | 当前会话 |
| **low（短上下文）** | 按冻结接口写实现、跑测试、小步提交 | **新会话** |

**实现一定要开新会话**：长上下文对设计是资产，对实现是负债——注意力被稀释，
越往后越容易漏早期约束，而且每改一次都要重读一遍长历史。

### 9.3 low 档工作流

1. 先读接口冻结节，确认字段、签名、验收判据
2. **先写测试，再写实现**
3. 每完成一小步跑 `uv run pytest -q` 与 `openspec validate --all --store store`
4. 小步提交（一次不超过 3 个文件）

### 9.4 立即停下并交接给 high 的信号

出现任一情况就停：

1. 需要改已有 spec
2. 需要改数据模型或迁移
3. 需要跨模块重构
4. 测试写不出来，或验收判据说不清
5. 同一个地方反复修 2 次以上

> 理由：**局部 bug 让 high 修很便宜；架构 bug 让 high 修很贵**，而且它还得重新读上下文、
> 缓存重算。所以让 high 过核心设计，让 low 写机械实现。

### 9.5 其他

- 待决问题（记录在 `training-path-generation/proposal.md`）：关键词白名单的去留，暂缓
- 企业版相关内容一律**后置不删**，规格留在 store 里
