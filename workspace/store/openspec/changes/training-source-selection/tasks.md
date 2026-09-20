# training-source-selection · 任务清单

> 按实现分层拆成两段：**阶段 A 静态层** 与 **阶段 B 网络层**。
> 接口契约见 `design.md` 的「接口冻结」一节——**已冻结，实现期间不改**。
> 节奏：每完成一小步跑 `uv run pytest -q` + `openspec validate --all --store store`，小步提交。

---

## 阶段 A：静态层（可独立 commit，change 暂不 archive）

### A1 数据层

- [ ] A1.1 新增 `sources` 表：字段与 CHECK 完全按 `design.md` 冻结的模型
  - 注意：`type` 的 CHECK **必须包含 `web_url`**，`parse_status` 必须包含 `unsupported`（阶段 B 用）
  - 验收：`init-db` 后 `.schema sources` 可见，且 `web_url` 在 CHECK 内
- [ ] A1.2 新增 `source_chunks` 表
  - 验收：`init-db` 后可查看，`ordinal` 非空
- [ ] A1.3 新增 `source_chunks_fts` 虚表与同步触发器（写入/更新/删除时同步索引）
  - 验收：插入一条切片后用 `MATCH` 能命中
- [ ] A1.4 迁移逻辑接入既有 `migrate()`（新表用 `CREATE TABLE IF NOT EXISTS`，无需重建）
  - 验收：对已有 `data/trainer.db` 跑 `init-db`，训练条数不变，新表出现
- [ ] A1.5 `src/db/models.py` 增加 `Source` / `SourceChunk` dataclass
  - 验收：`uv run pytest -q` 通过

### A2 解析与切片（纯函数优先）

- [ ] A2.1 Markdown / txt 解析：保留标题层级
  - 验收：单测断言 `heading_path` 形如 `第三章 > 3.2 虚拟语气`
- [ ] A2.2 切片函数：先按标题层级、再按段落边界；超长递归切分并保留标题前缀
  - 验收：单测覆盖「不跨知识点」「超长切分后前缀保留」
- [ ] A2.3 PDF 解析（选型见 ADR-0012，优先复用 `PythonProject16` 的方案）
  - 验收：一份真实 PDF 解析成功并输出 Markdown
- [ ] A2.4 Word（.docx）解析：按标题样式与段落层级转 Markdown
  - 验收：2 份真实 docx 讲义解析成功，层级正确
- [ ] A2.5 Excel（.xlsx）题库解析：识别题干 / 选项 / 正确答案 / 解析列，输出结构化题目
  - 验收：2 份真实题库表格解析成功；表头不规整时判失败并提示，不猜列含义
- [ ] A2.6 解析失败路径：写 `parse_status=failed` + `parse_error`，不阻塞其他来源
  - 验收：传入损坏文件，流程不中断且状态为 failed

### A3 来源服务（签名见冻结章节）

- [ ] A3.1 `create_source`：三类静态来源登记
  - 验收：三种来源各跑一遍都能在库里看到记录
- [ ] A3.2 `parse_source`：解析 + 切片 + 建索引，幂等
  - 验收：同一内容导入两次，第二次日志显示跳过解析
- [ ] A3.3 `list_sources` / `get_source` / `list_chunks`
  - 验收：查询接口返回结构与冻结签名一致
- [ ] A3.4 `search_chunks`（FTS5）：返回按相关度排序的切片，**不产生任何 LLM 调用**
  - 验收：单测断言查询路径不触发 `complete()`
- [ ] A3.5 `compute_impact`：切片的新增 / 删除 / 修改清单
  - 验收：修改资料后能看到清单，且**不自动删除任何训练项**

### A4 训练项回指

- [ ] A4.1 训练项增加 `source_chunk_ids`，写入时校验切片 ID 存在性
  - 验收：单测断言无效 ID 被丢弃 + 记日志，训练项本身保留
- [ ] A4.2 提供「查看出处」查询：返回切片原文与标题路径
  - 验收：能把某训练项对应原文取出来

### A5 UI（静态部分）

- [ ] A5.1 来源选择页：三类来源入口 + 已导入资料列表（标题 / 类型 / 切片数 / 状态）
  - 验收：手动跑一遍，能看到三类入口与资料列表
- [ ] A5.2 资料详情页：按标题层级展示切片
  - 验收：上传一份 Markdown 后能看到按章节组织的切片
- [ ] A5.3 训练处于 `draft` / `pending_confirm` 时不提供导入入口
  - 验收：未确认目的时页面提示需先确认目的
- [ ] A5.4 `web_url` 入口**不出现**在界面上
  - 验收：页面检查，无网络来源入口

### A6 阶段 A 收尾

- [ ] A6.1 补单测并跑通 `uv run pytest -q`
- [ ] A6.2 用 3 份真实资料统计解析成功率、切片数分布、解析耗时，写入 `workspace/evidence/`
- [ ] A6.3 写 `workspace/record/` 变更记录（标注「阶段 A 完成，change 未归档」）
- [ ] A6.4 `openspec validate --all --store store` 通过
- [ ] A6.5 提交（**不 archive**）

---

## 阶段 B：网络层（完成后与 A 一起 archive）

> **前置**：阶段 A 已提交；出现任一 stop signal 立即停下交接 high。

### B1 抓取与快照

- [ ] B1.1 抓取：URL → HTML → 记录 HTTP 状态与 `fetched_at`
  - 验收：可访问页面成功；不存在的域名得到明确失败原因
- [ ] B1.2 正文抽取：剥离导航 / 页脚 / 脚本，转带层级的 Markdown
  - 验收：单测用含导航与脚本的样本，断言输出不含导航文本
- [ ] B1.3 保存快照：`snapshot_text` + `origin_url` + `fetched_at` + `checksum`
  - 验收：抓取后库中可见快照与时间戳，界面展示原链接与快照时间
- [ ] B1.4 失败显式化：DNS / 超时 / 403 / 人机校验 / 正文为空（单页应用）
  - 验收：用本次调研真实失败的三类页面各测一次，均得到明确失败提示而非空来源
- [ ] B1.5 手动刷新快照：重新抓取后走增量重建与影响面流程
  - 验收：改动页面后刷新，能看到切片变更清单与受影响训练项
- [ ] B1.6 边界约束：不跟随页面链接、不做定时重抓、不绕过反爬
  - 验收：代码检查确认抓取实现中不存在递归抓链接的逻辑

### B2 UI（网络部分）

- [ ] B2.1 来源页增加网络图标入口：粘贴 URL → 添加 → 显示为可开关的知识来源
  - 验收：添加两个网址后均显示为活动来源
- [ ] B2.2 来源开关：可停用某个来源而不删除
  - 验收：停用后该来源不参与检索与出题

### B3 阶段 B 收尾

- [ ] B3.1 补单测并跑通 `uv run pytest -q`
- [ ] B3.2 做一次 FTS5 召回对照实验并写入 `workspace/evidence/`（是否引入 embedding 的判断依据）
- [ ] B3.3 写 `workspace/record/` 变更记录（阶段 B 完成）
- [ ] B3.4 `openspec validate --all --store store` 通过
- [ ] B3.5 archive 本 change，并把 `source-management` spec 的 `Purpose` 从 TBD 改成一句话
