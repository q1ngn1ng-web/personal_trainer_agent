# source-management Specification

## ADDED Requirements

### Requirement: 用户能选择或提供训练资料来源

系统 SHALL 支持三种资料来源类型：`ai_generated`（AI 生成）、`user_upload`（用户上传文件）、
`user_paste`（用户粘贴文本）。用户 MUST 能明确选择使用哪一种，选择结果 MUST 落库到 `sources` 表。

#### Scenario: 选择 AI 生成

- **WHEN** 用户选择「由 AI 生成训练资料」
- **THEN** 系统写入一条 `type=ai_generated` 的来源记录
- **THEN** 视为来源已就绪，允许进入路径生成

#### Scenario: 上传文件

- **WHEN** 用户上传一份 PDF 或 Markdown 文件
- **THEN** 系统写入 `type=user_upload` 的来源记录，并开始解析
- **THEN** 解析完成前该来源状态为处理中，不允许进入路径生成

#### Scenario: 粘贴文本

- **WHEN** 用户粘贴一段纯文本并提交
- **THEN** 系统写入 `type=user_paste` 的来源记录，内容直接进入切片流程

#### Scenario: 来源为空不得继续

- **WHEN** 训练已确认目的但没有任何来源
- **THEN** 系统不进入训练路径生成
- **THEN** 页面提示需要选择或提供资料

### Requirement: 系统必须解析并结构化切片

系统 SHALL 把来源内容解析为带标题层级的结构，并按**标题层级与段落边界**切片，
MUST NOT 使用固定字数硬切。每个切片 SHALL 记录 `heading_path`、`ordinal` 与 `char_count`，
并 MUST 在切片超长时递归按段落再切且保留标题前缀。

#### Scenario: 按标题层级切片

- **WHEN** 一份文档包含「第三章 > 3.2 虚拟语气 > 用法一」这样的层级
- **THEN** 系统产出对应切片，且每个切片都能取到完整的 `heading_path`

#### Scenario: 切片超长

- **WHEN** 某个标题下的内容超过设定的字符上限
- **THEN** 系统按段落递归切分，每段保留该标题前缀
- **THEN** 不产生跨越两个知识点的切片

#### Scenario: 解析失败

- **WHEN** 文件无法解析（扫描件、加密、格式损坏）
- **THEN** 系统把该来源的 `parse_status` 置为 `failed` 并保留原始记录
- **THEN** 界面提示失败原因与重试入口，且不阻塞其他来源

### Requirement: 训练项必须回指来源切片

系统 SHALL 在训练项上保存其实际使用的来源切片标识集合。
当由 AI 生成训练项时，系统 MUST 把候选切片一并传入，并 MUST 校验模型标注的切片标识是否真实存在；
不存在的标识 MUST 被丢弃并记录一条日志。

#### Scenario: 回指有效

- **WHEN** 用户在训练项详情中点开「查看出处」
- **THEN** 系统展示该训练项引用的原文切片及所在标题路径

#### Scenario: 模型标注了不存在的切片

- **WHEN** LLM 输出里引用了不存在的切片标识
- **THEN** 系统丢弃该引用并记录一条警告日志
- **THEN** 训练项仍被保留，只是该条回指失效

### Requirement: 资料变更必须增量重建并提示影响面

系统 SHALL 为每个来源计算内容校验值。校验值未变时 MUST 跳过解析并复用已有切片；
校验值变化时 SHALL 重新解析、比对切片集合，并列出受影响的训练项供用户决定，
MUST NOT 自动删除任何训练项。

#### Scenario: 重复导入同一文件

- **WHEN** 用户再次导入内容完全相同的文件
- **THEN** 系统根据校验值跳过解析，并提示「内容未变化，已复用原有切片」

#### Scenario: 资料内容变化

- **WHEN** 用户导入同名但内容已变的文件
- **THEN** 系统重新解析并给出切片的新增 / 删除 / 修改清单
- **THEN** 系统列出受影响的训练项，并提供「保留旧训练项」与「标记为重练」两种操作
- **THEN** 系统不自动删除任何训练项

### Requirement: 来源选择必须在目的确认之后

系统 SHALL 要求训练处于 `confirmed` 状态才允许进行来源选择与导入。
未确认目的的训练 MUST NOT 导入资料，也 MUST NOT 生成训练路径。

#### Scenario: 目的未确认时导入被拒

- **WHEN** 训练处于 `draft` 或 `pending_confirm` 状态
- **THEN** 系统不提供资料导入入口
- **THEN** 页面提示需要先确认训练目的

### Requirement: 资料检索使用全文索引，不引入向量检索

系统 SHALL 使用 SQLite FTS5 建立切片全文索引，并在本阶段 MUST NOT 引入 embedding 或向量库。
引入向量检索的前提是满足 ADR-0002 与 ADR-0007 写明的重评估触发条件。

#### Scenario: 检索走全文索引

- **WHEN** 系统需要为训练项查找候选切片
- **THEN** 通过 FTS5 查询返回按相关度排序的切片
- **THEN** 该过程不产生任何 LLM 调用，也不产生 embedding 调用

#### Scenario: 未满足条件不得引入向量检索

- **WHEN** 有人提议加入向量库
- **THEN** 必须先给出当前 FTS5 的召回评测结果，并新写 ADR 取代 ADR-0007
