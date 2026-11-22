# share-gate Specification

## ADDED Requirements

### Requirement: 分享链接支持开放级别

系统 SHALL 为分享链接提供 `org`（默认，行为与现行一致）与 `anyone` 两档开放级别。
`anyone` 链接允许**任何登录用户**（含跨组织与无组织个人）预览并导入该计划；
`org` 链接仍仅限本组织在册成员。存量链接 MUST NOT 因本变更改变行为。

#### Scenario: 跨组织用户通过 anyone 链接导入

- **WHEN** 一个不属于该组织且已登录的用户打开 `anyone` 链接并拉取
- **THEN** 导入成功，产出独立副本（进度清零、溯源完整、题库随副本复制）
- **THEN** 同一用户重复拉取返回既有副本（幂等沿用 plan-sharing）

#### Scenario: anyone 链接未登录被拒

- **WHEN** 未登录用户预览或拉取 `anyone` 链接
- **THEN** 请求被拒（401），不返回任何计划内容

#### Scenario: 存量 org 链接行为不变

- **WHEN** 本变更上线后使用既有的 `org` 链接
- **THEN** 非组织成员拉取仍被拒（403），组织成员拉取行为与上线前一致

### Requirement: 出向分享动作前置文档门禁

系统 SHALL 在以下四类分享动作执行前校验计划引用的全部启用文档
（`sources.enabled = 1`）的可见级是否达到该动作的受众级：
①训练可见性设为 `public`；②生成 `org` 链接；③生成 `anyone` 链接；④推送指定成员。
存在不达标文档且未全部确认时，系统 MUST 拒绝该动作并返回不达标文档清单。

#### Scenario: 计划设为 public 时被私有文档阻止

- **WHEN** 计划引用 2 份 private 文档，owner 将其可见性设为 public 且未确认这两份文档
- **THEN** 请求被拒（409），响应包含这 2 份文档的 id、标题与当前可见性

#### Scenario: 推送指定成员时 specific 未覆盖目标被阻止

- **WHEN** 计划引用 1 份 specific 文档，但授权集未覆盖全部推送目标
- **THEN** 请求被拒，该文档列入清单并标注授权未覆盖目标

#### Scenario: 无私有文档时直接放行

- **WHEN** 计划引用的全部文档均已达受众级
- **THEN** 分享动作直接执行，无需任何确认参数

### Requirement: 确认即定向升级且与分享原子完成

用户确认（勾选）一份不达标文档 SHALL 将其可见性升级到本次分享的受众级
（publish/link_* → `public`；push → `specific` 且授权覆盖全部目标成员）。
升级与分享动作 MUST 在同一事务内完成；确认集缺少任一不达标文档时 MUST 整体回滚。

#### Scenario: 全选确认后一次事务完成

- **WHEN** owner 在确认对话框全选 2 份 private 文档并提交（action=link_anyone）
- **THEN** 2 份文档可见性升级为 public、`anyone` 链接生成，两步在同一事务内
- **THEN** 响应返回链接 token，文档与训练的新可见性即时生效

#### Scenario: 确认集不完整整体失败

- **WHEN** blocked 清单含 2 份文档而确认集只含 1 份
- **THEN** 请求被拒（409）并返回最新完整清单；已确认的那份 MUST NOT 被升级
  （无部分生效）

### Requirement: 确认升级持久且有审计

文档可见性升级 MUST 是持久变更（不随分享结束回落），所有者可另行改回；
每次确认 MUST 留下可追溯记录（谁、何时、为哪次分享、确认了哪些文档）。

#### Scenario: 事后降级不追溯已生成链接

- **WHEN** owner 在 anyone 链接生成后将某文档改回 private
- **THEN** 该链接仍可被拉取（生成时点已过门禁，克隆本就是全量复制）
- **THEN** owner 撤销链接或收紧训练可见性的路径保持可用

### Requirement: 导入语义与预览保护沿用

公开导入 MUST 复用 plan-sharing 的克隆语义（独立副本、进度清零、溯源引用、
题库完整复制、同用户幂等）；预览 MUST NOT 泄露题库内容、参考答案与作答数据
（plan-sharing 既有规则对 anyone 链接同样生效）。

#### Scenario: anyone 链接预览不泄露题库

- **WHEN** 跨组织用户预览 anyone 链接
- **THEN** 响应只含主题、目标、阶段、训练项与验收标准
- **THEN** 不含题目文本、参考答案、要点清单或作答记录
