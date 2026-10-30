# account-schema Specification

## Purpose
保证全新环境 `init_db` 即可产出包含账户/组织全部表的可运行库，注册与登录不依赖仓库外任何建表步骤。
## Requirements
### Requirement: init-db 产出完整可运行的 schema

`init_db` SHALL 创建应用全部运行所需的数据表——包括账户与会话（`users` / `sessions` / `login_tokens`）、
组织与名单（`organizations` / `departments` / `memberships` / `roster_entries`）与培训作业
（`assignments` / `assignment_targets` / `assignment_receipts`）。
全部表定义 SHALL 以 `src/db/tables.sql` 为唯一仓库来源，MUST NOT 依赖任何仓库外的建表过程。

#### Scenario: 全新库初始化后表齐全

- **WHEN** 在一个空目录设置 `DB_PATH` 并执行 `init_db`
- **THEN** `sqlite_master` 中存在全部 33 张普通表（含上述 10 张账户/组织表）及 FTS5 虚表
- **THEN** 对生产库重复执行 `init_db` 不产生任何结构变化（`IF NOT EXISTS` 幂等）

### Requirement: 全新库上注册与登录可用

在仅执行过 `init_db` 的全新库上，账户链路 SHALL 可用：
`register_account` 成功创建用户与会话并返回 viewer；
`viewer_from_session` 以会话明文 token 解出同一身份；
`login_password` 以正确密码登录成功、错误密码被拒绝（与「用户不存在」返回**统一文案**，不暴露账号存在性）。
账户链路 MUST NOT 依赖任何预置数据之外的初始化步骤。
ORM 模型（`Training` / `Source`）SHALL 声明归属字段（`org_id` / `owner_user_id` / `department_id`），
使权限判定经 `to_dict()` 拿到的数据与 schema 一致——
MUST NOT 出现「列在库里、字段在模型外」的脱节（该脱节曾导致跨用户隔离静默失效）。

#### Scenario: 全新库注册→会话→登录

- **WHEN** 在全新初始化的库上以新邮箱注册（密码 ≥8 位）
- **THEN** 返回的 viewer 带有新用户 id，且 `sessions` 表新增一行只存 sha256 哈希的记录
- **WHEN** 用该邮箱与正确密码调用 `login_password`
- **THEN** 登录成功；用错误密码则抛出 `PermissionError`，文案与「用户不存在」一致

#### Scenario: 跨用户隔离

- **WHEN** 用户 B（已登录）请求用户 A 创建的训练的路径或资料
- **THEN** 返回 403；训练归属判定基于 `owner_user_id`，组织级训练（owner 为空）才对所有同组织成员可见

#### Scenario: 未登录访问受保护接口

- **WHEN** 鉴权开启（TRAINER_AUTH=1）且请求未携带有效会话 Cookie
- **THEN** 返回 401 与统一提示「请先登录」

