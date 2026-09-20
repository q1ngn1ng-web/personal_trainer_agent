# goal-clarification Specification

## Purpose
把用户的一句模糊描述，澄清成可确认、可追溯的训练目的：只针对「学什么、到什么程度、怎么算学会」追问，澄清阶段不涉及训练周期与频次；用户确认后写入结构化快照，作为后续理解边缘定位与路径生成的唯一输入。
## Requirements
### Requirement: 用户能用自然语言描述学习内容

系统 SHALL 在新建训练入口提供自由文本输入框，接收用户对学习内容的自然语言描述，
并 MUST 把原始描述完整保留到目标草案的 `content` 字段，不做摘要式改写。

#### Scenario: 接收模糊描述

- **WHEN** 用户在新建训练页输入「我想学虚拟语气」并提交
- **THEN** 系统创建一条 `status=draft` 的训练记录
- **THEN** 原始描述被完整保存，未经过 LLM 摘要

#### Scenario: 输入为空

- **WHEN** 用户提交空白描述
- **THEN** 系统拒绝提交并提示「请用一句话描述你想训练的内容」

### Requirement: 澄清阶段只处理目的，不得索要投入参数

澄清阶段 SHALL 只产出 `content`、`level`、`acceptance` 三个字段。
系统 MUST NOT 在本阶段询问或要求用户选择训练周期、每周训练次数、每次训练时长等投入参数，
MUST NOT 在澄清页放置这类控件。这些参数属于训练路径阶段，由 AI 生成草案、用户微调后确认。

#### Scenario: 澄清页不出现投入参数控件

- **WHEN** 用户进入新建训练页
- **THEN** 页面只包含内容描述输入与澄清追问
- **THEN** 页面不包含周期 / 每周次数 / 每次时长的选择控件

#### Scenario: 用户主动提供投入参数

- **WHEN** 用户在描述里写「我想两周内学会虚拟语气，每天 30 分钟」
- **THEN** 系统把该信息作为描述的一部分保留，不因此发起澄清追问
- **THEN** 该信息不作为澄清阶段的产出参数，留给路径阶段使用

### Requirement: 系统只对语义字段追问，且追问有软限与硬限

系统 SHALL 仅对 `level`（目标等级）与 `acceptance`（验收标准）两个语义字段发起追问，
这两项 MUST NOT 由系统默认值替代而不告知用户。

追问 **软限 2 轮**：达到后系统 SHALL 给出建议值，并明确提示「可以直接用系统建议，也可以自己改」。
追问 **硬限 3 轮**：达到后系统 MUST 强制收口，输出草案并对仍缺失的字段标注来源为 `inferred`。

**是否继续追问 MUST 由规则层依据缺失字段与轮次判定，不得由 LLM 自行决定停止。**

#### Scenario: 缺语义字段时追问

- **WHEN** 用户描述「我想学虚拟语气」且草案缺少 `acceptance`
- **THEN** 系统提出一个针对 `acceptance` 的追问，并把 `clarification_rounds` 加 1
- **THEN** 系统不进入关键词生成与训练文件生成阶段

#### Scenario: 到达软限

- **WHEN** 追问轮次达到 2 轮且仍有语义字段缺失
- **THEN** 系统给出建议值并提示「可以直接用系统建议，也可以自己改」
- **THEN** 用户可以直接确认，不被迫继续回答

#### Scenario: 到达硬限

- **WHEN** 追问轮次达到 3 轮且仍有语义字段缺失
- **THEN** 系统输出草案，把缺失字段的来源标为 `inferred`
- **THEN** 系统进入 `pending_confirm` 状态，允许用户直接修改

#### Scenario: LLM 调用失败降级

- **WHEN** `goal_clarification` 用途的 LLM 调用重试后仍失败
- **THEN** 系统降级为表单式追问模板，逐字段向用户提问
- **THEN** 失败记录写入 `llm_calls` 表，但流程不阻塞

### Requirement: 验收标准必须是可判定判据

`acceptance` MUST 是量化判据或可观察的质性判据之一，MUST NOT 是纯主观形容词。
量化判据 SHALL 包含 `metric`（`accuracy` / `volume` / `speed` / `streak`）与 `target`；
质性判据 SHALL 包含可观察的 `statement` 与检查方式 `check`。
追问时系统 SHALL 优先引导用户给出数字。

#### Scenario: 用户给出可量化标准

- **WHEN** 用户回答「10 句改错题做对 8 句」
- **THEN** 系统记录 `type=quantitative`、`metric=accuracy`、`target=0.8`、`unit=10 句改错题`
- **THEN** 该判据可被后续评测模块直接消费

#### Scenario: 用户给不出数字

- **WHEN** 用户回答「能自己讲清楚就行」
- **THEN** 系统记录 `type=qualitative`，并追问或补充可观察的检查方式
- **THEN** 缺少检查方式时该字段仍视为未完成，继续追问

#### Scenario: 用户给出纯主观形容词

- **WHEN** 用户回答「练得比较熟练就行」
- **THEN** 系统不把该回答当作完成的判据
- **THEN** 系统继续追问一次；若到达硬限，则由 AI 给出建议判据并标为 `inferred`

### Requirement: AI 不得覆盖用户显式给出的值

系统 SHALL 在每个字段上记录来源 `goal_json.field_sources`，取值为
`user_input` / `user_reply` / `inferred`。当 LLM 输出与用户输入或用户回答冲突时，
系统 MUST 保留用户的值并丢弃 LLM 的该字段值。

#### Scenario: AI 不得覆盖用户表达

- **WHEN** 用户明确表示「我想达到能自己写句子的程度」，而 LLM 草案给出「了解即可」
- **THEN** 系统保留「能自己写句子」，丢弃 LLM 的该字段
- **THEN** `field_sources.level` 为 `user_reply`

#### Scenario: 推断值必须可识别

- **WHEN** 某字段由系统推断得出
- **THEN** 该字段在草案界面上带「系统建议」标识
- **THEN** `field_sources` 中对应字段为 `inferred`

### Requirement: 用户必须确认目的后才能进入后续流程

系统 SHALL 把目的确认实现为显式状态迁移：训练处于 `draft` 或 `pending_confirm` 状态时，
MUST NOT 生成关键词白名单、MUST NOT 渲染训练文件。确认动作 SHALL 由规则层执行并落库。

#### Scenario: 未确认时阻止后续步骤

- **WHEN** 训练状态为 `draft` 或 `pending_confirm`
- **THEN** 系统不调用关键词生成，也不创建任何训练文件
- **THEN** 页面提示「请先确认训练目标」

#### Scenario: 用户确认目的

- **WHEN** 用户点击「确认目标」
- **THEN** 训练状态由 `pending_confirm` 变为 `confirmed`
- **THEN** 系统写入 `goal_confirmed_at` 时间戳
- **THEN** 系统允许进入后续阶段

#### Scenario: 用户修改目的

- **WHEN** 用户在 `pending_confirm` 状态下修改任一目的字段
- **THEN** 系统重新生成草案并保持 `pending_confirm` 状态
- **THEN** `goal_confirmed_at` 保持为空

#### Scenario: 非法状态迁移被拒绝

- **WHEN** 代码尝试把 `confirmed` 直接迁回 `draft`
- **THEN** 状态迁移函数拒绝该操作并记录一条警告日志

### Requirement: 目的确认后必须留存快照

系统 SHALL 在确认时把目标草案以 JSON 形式写入 `trainings.goal_json`，并 MUST 在快照内包含
`schema_version` 字段，以便后续结构变更时做兼容读取。快照一旦确认即冻结，
MUST NOT 被后续 LLM 生成过程改写。

#### Scenario: 快照写入

- **WHEN** 用户确认目的
- **THEN** `trainings.goal_json` 包含 `content` / `level` / `acceptance` / `field_sources` /
  `schema_version`
- **THEN** 读取该训练的任意页面都能取到确认时的目的，不受后续 LLM 生成结果影响

#### Scenario: 确认后可追溯

- **WHEN** 用户或开发者查看该训练
- **THEN** 可看到 `goal_confirmed_at`、`clarification_rounds`、完整目的快照与各字段来源

#### Scenario: 确认标记与目的内容分开存储

- **WHEN** 用户确认目的
- **THEN** `trainings.status` 变为 `confirmed` 并写入 `goal_confirmed_at`
- **THEN** `goal_json` 中保存的是 `content` / `level` / `acceptance` 的具体取值，而不是布尔标记
- **THEN** 后续环节通过读取这些取值（而非"是否确认"）来决定训练内容与判分口径

#### Scenario: 快照作为路径生成的唯一输入

- **WHEN** 后续路径生成阶段启动
- **THEN** 它读取的是已确认的 `goal_json`，而不是重新解析用户原始描述
