# training-source-selection · 设计文档

---

## 阶段 A 设计（静态层）

### 分层与拆法

| 阶段 | 范围 | 完成后 |
|---|---|---|
| **A 静态层** | 数据模型、来源列表、静态来源选择（AI 生成 / 上传文件 / 粘贴文本）、解析切片、FTS5、训练项回指、测试骨架 | 可先 commit，**change 暂不 archive** |
| **B 网络层** | 网络来源（URL 抓取、正文抽取、快照）、信任源判定、引用可复核、缓存与刷新 | 与 A 一起 archive |

**为什么不拆成两个 change**：`source-management` capability 由本 change 新建，
两个 change 同时创建同一 capability 会在归档时冲突。

### 关键决策：阶段 A 就把网络字段建好

阶段 A 建表时**一并包含 `web_url` 枚举值与网络字段**（可空、不暴露 UI）。
这样阶段 B 只写行为、**完全不需要改数据模型或迁移**，
从根上消除了"阶段 B 触发迁移"这个高风险动作。

### 数据模型（冻结）

```
sources
  id, training_id,
  type TEXT CHECK IN ('ai_generated','user_upload','user_paste','web_url'),
  title TEXT NOT NULL,
  origin TEXT,                    -- 文件名 / 说明
  origin_url TEXT,                -- 阶段 B 使用
  fetched_at DATETIME,            -- 阶段 B 使用
  snapshot_text TEXT,             -- 阶段 B 使用
  org_id INTEGER,                 -- 预留，阶段 A 填默认值 1
  scope TEXT CHECK IN ('org_shared','personal') DEFAULT 'personal',
  checksum TEXT,
  parse_status TEXT CHECK IN ('pending','ok','failed','unsupported') DEFAULT 'pending',
  parse_error TEXT,
  imported_at DATETIME NOT NULL

source_chunks
  id, source_id, ordinal, heading_path, text, char_count

source_chunks_fts         -- FTS5 虚表，rowid 关联 source_chunks.id
```

**约束**：阶段 A 的 `CHECK` 里已经包含 `web_url` 与 `unsupported`，
但 UI 与抓取逻辑在阶段 B 之前不暴露、不写入。

### 函数签名（冻结）

```python
# src/services/source_service.py
def create_source(training_id: int, *, type: str, title: str,
                  origin: str | None = None, content: str | None = None,
                  scope: str = "personal") -> Source
def parse_source(source_id: int) -> Source            # 解析 + 切片 + 索引，幂等
def list_sources(training_id: int) -> list[Source]
def get_source(source_id: int) -> Source | None
def list_chunks(source_id: int, *, limit: int = 200) -> list[SourceChunk]
def search_chunks(training_id: int, query: str, *, limit: int = 10) -> list[SourceChunk]
def compute_impact(source_id: int, new_content: str | None = None) -> ImpactReport
```

阶段 B 只**新增**函数，不修改以上签名：

```python
def fetch_web_source(training_id: int, url: str) -> Source
def refresh_snapshot(source_id: int) -> Source
```

### 验收判据（冻结，阶段 A）

| # | 判据 |
|---|---|
| 1 | 三种来源（AI 生成 / 上传 / 粘贴）都能在 `sources` 落记录 |
| 2 | 粘贴文本解析后切片数 ≥ 1，`heading_path` 为顶层 |
| 3 | Markdown 解析后 `heading_path` 形如 `第三章 > 3.2 虚拟语气` |
| 4 | 可解析 PDF 成功；损坏文件 → `parse_status=failed` 且不阻塞其他来源 |
| 5 | 相同内容重复导入 → 第二次跳过解析（`checksum` 命中，日志可验证） |
| 6 | FTS5 查询能命中切片，且**不产生任何 LLM 调用** |
| 7 | 训练项回指：写入不存在的切片 ID 被丢弃并记日志，训练项本身保留 |
| 8 | 全部测试使用临时库（`DB_PATH`），**不触碰 `data/trainer.db`** |

### 测试骨架（先写，冻结）

`tests/test_source_service.py`：

- 纯函数：切片（层级与超长递归）、`checksum`、影响面计算
- 服务：三种来源各一条用例 + 幂等导入 + FTS5 查询
- 边界：损坏文件、空文本、不存在的切片 ID

**节奏**：每完成一小步跑 `uv run pytest -q` 与 `openspec validate --all --store store`，
小步提交（一次不超过 3 个文件）。

---

## Context

### 背景

现有流程的资料**全部由 AI 生成**，`tables.sql` 里 6 张表没有任何与"来源"相关的字段。
后果有两个：用户无法带入自己的教材与讲义；训练项没有出处，既无法核对，也无法在资料更新后追溯影响范围。

同时，下一次 change（训练路径生成）需要两个并列输入——已确认的目的、可用的资料来源。本 change 负责后者。

### 当前状态

- `trainings` 只记录 `topic` 与关键词白名单，没有来源概念
- 训练内容由 `src/services/trainer_service.py` 按固定模板生成
- 无任何检索能力（既没有向量检索，也没有全文检索）
- `goal-clarification-confirm` 已确定：目的确认后才允许进入后续阶段

### 约束

- 沿用 ADR-0001：LLM 只做语义，解析/切片/索引/判定由确定性代码做
- 沿用 ADR-0002：不引入 embedding，除非触发条件满足（本 change 判断为**未触发**）
- 存储仍是 SQLite，不新增外部服务
- 所有 Python 脚本用 uv 运行

### 利益相关方

- 用户本人（自用 + 面试演示）

## Goals / Non-Goals

**Goals:**

- 用户能把教材 / 讲义 / 笔记带进来，并看到它们被拆成了什么
- 用户也能把**网页内容**带进来，且任何时候都能看到"当时抓的是哪一版"
- 每个训练项能回指到原文具体切片，点得回去
- 资料变更后能知道影响了哪些训练项

**Non-Goals:**

- 不做向量检索与混合检索
- 不做 Word / Excel / 网页抓取 / OCR
- 不做引用一致性校验

## Decisions

### D1 表结构

```
sources
  id, training_id,
  type(ai_generated|user_upload|user_paste|web_url),
  title, origin(文件名或 URL 或说明),
  origin_url,          -- 仅 web_url 使用
  fetched_at,          -- 网络来源的抓取时间
  snapshot_text,       -- 网络来源的正文快照
  org_id,              -- 预留：组织隔离（权限校验由后续 change 实现）
  scope(org_shared|personal),  -- 预留：企业公共区 / 个人资料
  checksum, imported_at, parse_status

source_chunks
  id, source_id, ordinal, heading_path, text, char_count

source_chunks_fts        -- FTS5 虚表，索引 text 与 heading_path
  (rowid 关联 source_chunks.id)

training_items（后续路径阶段新建）
  ..., source_chunk_ids   -- JSON 数组，回指来源切片
```

### D2 解析与切片

1. 解析（第一批格式，选型见 ADR-0012）：

   | 格式 | 处理方式 |
   |---|---|
   | PDF | 解析为 Markdown，保留标题层级 |
   | Markdown / txt | 直接读取 |
   | **Word（.docx）** | 解析标题样式与段落层级，转为 Markdown |
   | **Excel（.xlsx）** | **按表头语义解析为结构化题目**（题干 / 选项 / 正确答案 / 解析），不当普通表格切片 |
   | 扫描件 | 第一批不支持；第二批引入 OCR 后需保留原图并标 `ocr=true` 与置信度 |

2. 切片：**先按标题层级切，再按段落边界切**，不用固定字数
3. 每个切片记录 `heading_path`（如 `第三章 > 3.2 虚拟语气 > 用法一`），用于溯源与展示
4. 切片过长（超过设定上限）时递归按段落再切，保留标题前缀
5. 解析失败不阻塞：`parse_status` 记为 `failed` 并保留原始文件路径，界面提示可重试

### D3 检索：SQLite FTS5（本 change 的核心取舍）

| 方案 | 结论 | 理由 |
|---|---|---|
| FTS5 全文检索 | **采用** | 零新增依赖、结果可解释、可单测；当前资料规模（1-3 份、数百切片）完全够用 |
| 向量检索 | 暂不 | 引入 embedding 依赖、阈值校准、缓存与调用成本；ADR-0002 的触发条件未满足 |
| 混合检索 | 暂不 | 是向量检索的超集，同上 |

**重评估触发条件**：当出现"跨多份资料找同类知识点""相似题推荐""单训练切片量超过数千"时，重新评估并新写 ADR。

### D4 训练项回指来源

训练项保存 `source_chunk_ids`，界面上可展开查看原文片段。
由 AI 生成训练项时，**必须把候选切片一并传入 prompt**，并要求模型在输出里标注使用了哪些切片 ID；
模型标注不存在的 ID 时，该标注被丢弃并记一条日志（与字段来源标记同样的处理思路）。

### D5 增量重建与影响面

1. 导入时计算 `checksum`（文件内容或文本的哈希）
2. `checksum` 未变 → 跳过解析，直接复用已有切片
3. 变了 → 重新解析，比对切片集合：新增 / 删除 / 修改
4. 对受影响的训练项给出清单，让用户选择"保留旧训练项"或"标记为重练"
5. **不自动删除**任何训练项——删除是用户的决定

### D6 在流程中的位置

```
描述 → 澄清 → ✅确认目的 → 【本 change：选择/导入来源】→ 生成训练路径 → ...
```

约束：训练处于 `confirmed` 且**没有可用来源**时，不允许进入路径生成。
来源为空与"用户明确选择 AI 生成"是两种不同状态，前者是未完成，后者是有效选择。

### D7 与 `goal-clarification-confirm` 的边界

两个 change 都要参与"新建训练"的流程，但**不改同一条 Requirement**：

- `goal-clarification-confirm` 修改 `trainer-generation` 的「用户能创建新训练主题」
- 本 change 把"来源选择必须在目的确认之后"写进自己的 `source-management` 规格

这样两个 change 可以各自归档，不会产生 delta 冲突。

### D8 网络来源：抓取、正文抽取与快照

**为什么必须有这一节**：网页不同于文件——它会变。只存 URL，训练项将来回指时打开的可能已经是
另一段内容，"可追溯"当场失效。所以网络来源必须**存正文快照**。

流程：

1. 用户在界面上粘贴 URL（可一次加多个）
2. 抓取页面 HTML，记录 `fetched_at` 与 HTTP 状态
3. **抽取正文**：剥离导航、页脚、脚本、广告，只保留内容主体（用 readability 类算法）
4. HTML → Markdown，保留标题层级
5. 正文写入 `snapshot_text`，计算 `checksum`，进入与文件相同的切片与索引流程
6. 界面上同时展示**可点击的原始 URL** 与**快照时间**，用户知道读的是哪一版

边界与失败处理：

| 情况 | 处理 |
|---|---|
| DNS 失败 / 超时 / 403 | `parse_status=failed`，记录失败原因，不阻塞其他来源 |
| 页面是 JS 渲染的单页应用 | 抓到的正文可能为空——**明确记为失败并提示"该页面需要浏览器渲染，暂不支持"**，不假装成功 |
| 遇到人机校验（Cloudflare 等） | 直接记失败，不尝试绕过 |
| 页面内容变更 | 用户手动点「刷新快照」重新抓取；`checksum` 变化时走与文件相同的增量重建与影响面流程 |

**这不是理论担忧，是本次调研的真实经历**：抓 `docs.dify.ai` 时拿到的只有营销文案（单页应用），
抓 `help.quizlet.com` 时被 Cloudflare 拦截，抓 `support.google.com` 直接超时。
这三种失败模式都会在用户身上发生，所以失败必须显式暴露，而不是悄悄产出一个空来源。

## Risks / Trade-offs

| 风险 | 影响 | 处理方式 |
|---|---|---|
| FTS5 无法命中同义表达 | 召回不足 | 先量化影响（用真实资料做对照测试）；确认严重再触发 embedding 重评估 |
| 解析质量参差（扫描件、复杂版式） | 切片不可用 | `parse_status` 显式暴露失败；先只支持可解析的 PDF，扫描件明确不支持 |
| AI 标注的切片 ID 不存在 | 回指失效 | 校验 ID 存在性，无效标注丢弃并记日志 |
| 单个切片过长挤占上下文 | 生成质量下降 | 设切片长度上限，超限递归切分 |
| 资料多来源时训练项归属混乱 | 追溯困难 | 一个训练项只回指它实际使用的切片，不绑定"主来源" |
| 网页是 JS 渲染的单页应用 | 抓到的正文为空，来源不可用 | 显式判失败并提示"需要浏览器渲染，暂不支持"，不产出空来源 |
| 目标站点反爬或超时 | 导入失败 | 记录失败原因并可重试；不绕过人机校验、不做高频重试 |
| 网页内容后续变更 | 快照过期，出处与训练项对不上 | 保留 `fetched_at`；用户可手动刷新快照，刷新后走增量重建与影响面流程 |
| OCR 识别错误 | 产出看似合理、实则错误的训练项 | OCR 延后到第二批；引入后必须保留原图、标置信度，低置信度提示"需人工确认" |
| Excel 表头不规整 | 解析出错误题目 | 识别失败即判 `parse_status=failed`，提示用户调整表头，不猜列含义 |
| 组织隔离未实现期间写入的数据 | 将来迁移困难 | **本 change 就写入 `org_id` 与 `scope`**，即使当前只有一个组织 |

## 关联决策记录

- `workspace/decisions/ADR-0001-llm负责语义-规则负责状态.md`
- `workspace/decisions/ADR-0002-评测用组合分-暂不上embedding.md`（本 change 判断触发条件未满足）
- `workspace/decisions/ADR-0007-资料检索先用FTS5不上向量库.md`（本 change 的核心选型）

## 验收方式

- 单测：切片按标题层级正确分层、checksum 判定、影响面计算、无效切片 ID 被丢弃
- 手动场景：上传一份 PDF，能看到按章节切好的切片列表；训练项点开后能看到对应原文
- 手动场景：粘贴一个网页 URL，能看到正文快照、抓取时间与可点击的原始链接；
  再粘一个 JS 渲染的页面，应明确提示失败而不是产出空来源
- 手动场景：重复上传同一文件，第二次应跳过解析（日志可验证）
- 指标：解析成功率、切片数分布、解析耗时、FTS5 命中率——**待实测，当前标【待验证】**
