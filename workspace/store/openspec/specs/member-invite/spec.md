# member-invite Specification

## Purpose
TBD - created by archiving change member-invite. Update Purpose after archive.
## Requirements
### Requirement: 邀请制成员准入

组织成员资格 MUST 由显式邀请产生；系统 MUST NOT 把新注册用户自动加入
任何组织（默认组织自动准入的行为 SHALL 移除，存量成员资格保留）。
管理员添加成员 MUST 受其配额约束（默认 10，组织管理员逐人设置）。

#### Scenario: 管理员拉入已注册用户

- **WHEN** 管理员在候选列表中选择一个已注册且非本组织成员的用户并确认邀请
- **THEN** 该用户获得本组织 `invited` 状态的成员资格，记录邀请人
- **THEN** 该次邀请计入管理员配额

#### Scenario: 配额耗尽拒绝邀请

- **WHEN** 管理员名下的 invited+active 成员数已达其配额
- **THEN** 再次邀请 MUST 被拒绝并提示配额信息
- **THEN** 组织管理员不受配额约束

#### Scenario: 新注册用户保持无组织

- **WHEN** 一个新用户注册
- **THEN** 系统不创建任何组织成员资格
- **THEN** 该用户以个人模式使用，直到被邀请或自行创建组织

### Requirement: 邀请可见且可接受

被邀请用户 SHALL 能看到指向自己的待接受邀请，并可接受（`invited → active`）
或拒绝。管理员 SHALL 能撤销未接受的邀请。

#### Scenario: 被邀请人接受邀请

- **WHEN** 被邀请用户（invited 状态）登录并接受邀请
- **THEN** 其成员资格状态变为 `active`，获得对应角色的组织访问
- **THEN** 该成员计入邀请人的配额

#### Scenario: 管理员撤销邀请

- **WHEN** 管理员撤销一条未被接受的邀请
- **THEN** 该邀请失效，配额占用释放

### Requirement: 候选列表

管理员 SHALL 能获取"可邀请候选"列表：已注册用户中不属于本组织
（既非 active 也非 invited）的全部用户，支持按邮箱/昵称过滤。

#### Scenario: 候选列表排除现有成员

- **WHEN** 管理员打开候选列表
- **THEN** 本组织的 active 与 invited 用户不出现在候选中

### Requirement: 移除成员受开关约束

管理员移除 `member` 档成员 MUST 受组织管理员逐人授予的开关约束
（默认禁止）；MUST NOT 能移除 admin 或 org_admin 档成员。
组织管理员可移除包括 admin 在内的任何成员。

#### Scenario: 开关关闭时移除被拒

- **WHEN** 管理员（开关默认禁）尝试移除普通成员
- **THEN** 操作被拒绝并提示需组织管理员授权

#### Scenario: 组织管理员移除不受限

- **WHEN** 组织管理员移除任何 member/admin 档成员
- **THEN** 操作成功；被移除者的个人数据保留（成员资格置 disabled）

### Requirement: 三档个人版角色

组织成员角色 SHALL 为 `org_admin / admin / member` 三档
（现 `employee` 迁移为 `member`，`dept_manager` 档取消）；
角色判定保持纯函数（ADR-0001），企业版旧矩阵冻结于 git 历史。

#### Scenario: 角色迁移

- **WHEN** 存量成员资格执行迁移
- **THEN** employee → member、dept_manager → admin（含其配额默认值）、
  org_admin 保持不变

