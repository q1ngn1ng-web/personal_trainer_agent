# 20260919 · feat · 训练资料来源选择 proposal（未写代码）

## 变更摘要

为「用户选择训练资料来源」建立规格与选型依据。本次只产出 proposal / design / specs / tasks
与一条 ADR，**未改动任何业务代码**。

要解决的具体问题：

1. 现有训练资料**全部由 AI 生成**，用户无法带入自己的教材、讲义、题库
2. 生成内容没有出处，无法核对，也无法在资料更新后追溯影响范围
3. 下一步「训练路径生成」需要两个并列输入（已确认的目的 + 可用的资料来源），来源这一半是空的

## 产出

| 文件 | 内容 |
|---|---|
| `workspace/store/openspec/changes/training-source-selection/proposal.md` | Why / What Changes / 关键取舍表 / **三条待确认假设** / 非目标 / Capabilities / Impact |
| `.../design.md` | 表结构、解析切片策略、FTS5 选型、训练项回指、增量重建、流程位置、与另一 change 的边界处理 |
| `.../specs/source-management/spec.md` | 新增能力：6 条 Requirement |
| `.../tasks.md` | 6 组任务，每项写明验收方式 |
| `workspace/decisions/ADR-0007-资料检索先用FTS5不上向量库.md` | 核心选型：4 个备选方案的代价对比 + 4 条重评估触发条件 |

### 关键设计决定

1. **检索用 SQLite FTS5，不引入向量库**——当前单训练 1-3 份资料、切片数百级，
   ADR-0002 的触发条件未满足；上向量库要额外付阈值校准、缓存与调用成本
2. **按标题层级 + 段落边界切片**，不用固定字数——教材的章节结构本身就是语义边界
3. **训练项回指切片**，AI 标注不存在的切片 ID 时丢弃并记日志（与字段来源标记同一思路）
4. **增量重建不自动删除训练项**——变更后给影响面清单，删除由用户决定
5. **不改 `trainer-generation` 的同一条 Requirement**——避免与进行中的
   `goal-clarification-confirm` 在归档时产生 delta 冲突

## 影响范围

- **代码**：无（proposal 阶段）
- **规格**：新增 `source-management` capability；两个进行中的 change 互不冲突
- **验证**：两个 change 均为 4/4 artifacts complete；`openspec validate --all` 8 passed, 0 failed

## 待用户确认的三条假设

1. 来源只有三类（AI 生成 / 上传文件 / 粘贴文本），不做公开教材库对接
2. 允许中途追加来源，走增量重建 + 影响面提示
3. 一个训练可有多个来源，但一个训练项只回指它实际使用的切片

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `workspace/store/openspec/changes/training-source-selection/` | 新增（proposal / design / specs / tasks） |
| `workspace/decisions/ADR-0007-资料检索先用FTS5不上向量库.md` | 新增 |
| `workspace/decisions/README.md` | 索引新增一行 |

## 关联 OpenSpec change id

`training-source-selection`（状态：进行中，尚未 archive）

## 修订记录

### 2026-09-20 v2：新增「网络来源（URL）」

**触发**：用户参照 Microsoft AI Learning Advisor 的设置指南提出——来源还可以再加一类，直接粘贴网址把网页作为知识来源添加进去。

**改了什么**：

| 项 | v1 | v2 |
|---|---|---|
| 来源类型 | 三种（AI 生成 / 上传文件 / 粘贴文本） | **四种**，新增 `web_url` |
| 网页内容存储 | 不涉及 | **必须保存正文快照** + 原始网址 + 抓取时间 + 校验值 |
| 抓取边界 | 非目标里写"不做网页抓取" | 允许抓取，但**只抓用户显式给出的网址**；不跟随链接、不定时重抓、不绕过反爬 |
| 切片流程 | 文件专用 | 网页正文抽取后**进入同一套切片与索引流程** |

**新增决策记录**：`ADR-0008-网络来源必须保存正文快照.md`。核心判断是：网页会变，只存链接等于放弃"出处可追溯"；四个备选方案里选择"存快照 + 用户手动刷新"。

**顺带落进设计的实证**：ADR-0008 与 design.md 里写明的三类抓取失败（单页应用抓不到正文、Cloudflare 拦截、连接超时），全部来自本次调研的真实经历——`docs.dify.ai`、`help.quizlet.com`、`support.google.com`。这三个页面可以直接复用为测试样本。

**面试素材同步更新**：`workspace/面试/01-资料来源与知识导入.md` 新增 Microsoft AI Learning Advisor 一行（标注为"用户提供、服务器未能独立核实"），并写明网页来源同样是入场券而非差异化。

**当前状态**：`openspec status` 显示 4/4 artifacts complete，`openspec validate --all` 通过。

### 2026-09-20 v3：格式范围放宽 + 为组织隔离预留字段

**触发**：用户指出两处排除过窄——企业场景里 Word 讲义与 Excel 题库是主流形态，扫描件 OCR 也并非不能做；并且如果产品定位面向企业，就需要登录、角色、企业公共区这类能力，否则"培训周期缩短、达标率"根本无从量化。

**改了什么**：

| 项 | v2 | v3 |
|---|---|---|
| Word / Excel | 非目标，明确不做 | **纳入第一批**；Excel 按表头语义解析为结构化题目，不当普通表格切片 |
| 扫描件 OCR | 非目标，明确不做 | **列入第二批**，带触发条件与三条硬要求（保留原图、标置信度、低置信度提示人工确认） |
| 组织与权限 | 非目标，"不做多用户共享资料库与权限" | `sources` **预留 `org_id` 与 `scope`（企业公共/个人）**；登录、角色、鉴权明确划归独立的「组织与角色」change |

**新增决策记录**：`ADR-0012-文档格式支持范围与OCR策略.md`。核心判断：原来"每多一种格式就多一类失败模式"的理由成立，但它推出的是**分批支持 + 独立验收 + 失败显式化**，而不是一律不做。

**关于组织隔离的取舍说明**：登录可以后补，**数据隔离不能后补**。一旦引入组织，资料、路径、训练记录、达标数据都要带 `org_id`，逐表回改的成本远高于现在预留字段。因此本 change 即使当前只有一个组织，也照常写入 `org_id` 与 `scope`，但**不实现任何鉴权**。

**当前状态**：4/4 artifacts complete，`openspec validate --all` 通过。
