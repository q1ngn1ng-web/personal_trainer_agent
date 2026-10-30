# account-schema Specification

## MODIFIED Requirements

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
