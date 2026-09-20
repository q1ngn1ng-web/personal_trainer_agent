# org-and-roles Specification

## ADDED Requirements

### Requirement: 组织与成员管理

系统 SHALL 支持创建组织、创建用户并把用户加入组织。每个用户 MUST 至少属于一个组织，
每条业务数据 MUST 归属到一个组织。系统 MUST NOT 允许跨组织读取或写入数据。

#### Scenario: 创建组织与成员

- **WHEN** 管理员创建组织并添加成员
- **THEN** 成员记录包含 `org_id` 与角色
- **THEN** 该成员只能看到本组织的数据

#### Scenario: 跨组织访问被拒

- **WHEN** 某组织成员尝试读取另一组织的资料、训练或进度
- **THEN** 系统拒绝该请求并记录一条警告日志

### Requirement: 两种角色及其权限边界

系统 SHALL 支持 `admin`（管理层）与 `employee`（员工）两种角色。
`admin` SHALL 能上传企业公共区资料、发布培训任务、查看本组织的汇总与明细；
`employee` SHALL 能接收任务、训练并查看自己的进度。`employee` MUST NOT 发布任务或查看他人进度。

#### Scenario: 管理员发布任务

- **WHEN** `admin` 发布培训任务
- **THEN** 系统允许该操作，并记录发布人

#### Scenario: 员工尝试发布任务

- **WHEN** `employee` 调用发布任务的服务函数
- **THEN** 系统拒绝并抛出权限异常

#### Scenario: 员工查看他人进度

- **WHEN** `employee` 请求查看另一名员工的训练进度
- **THEN** 系统拒绝该请求

### Requirement: 资料可见范围

资料 SHALL 带可见范围：`personal`（个人）与 `org_shared`（企业公共区）。
`personal` 资料 MUST 仅本人可见；`org_shared` 资料 MUST 对本组织全部成员可见，
MUST NOT 对组织外成员可见。`org_shared` 资料 MUST 仅能由 `admin` 上传。

#### Scenario: 个人资料私有

- **WHEN** 员工上传一份个人资料
- **THEN** 其他成员无法检索或读取该资料

#### Scenario: 企业公共区资料共享

- **WHEN** 管理员把资料存放在企业公共区
- **THEN** 本组织所有成员均可在训练中选择该资料

#### Scenario: 员工上传到企业公共区被拒

- **WHEN** `employee` 尝试把资料放入 `org_shared`
- **THEN** 系统拒绝该操作

### Requirement: 权限校验必须在服务层执行

系统 SHALL 在服务层统一校验 `org_id` 与角色。UI 层的按钮隐藏或页面跳转
MUST NOT 作为权限控制手段。所有服务函数入口 MUST 执行校验，校验失败 MUST 抛出统一异常。

#### Scenario: 绕过界面直接调用

- **WHEN** 某调用方跳过界面直接调用服务函数访问无权数据
- **THEN** 服务层拒绝该调用
- **THEN** 该次拒绝被记录

#### Scenario: 权限矩阵单测

- **WHEN** 运行权限测试
- **THEN** 覆盖「员工读他人资料」「员工读他人进度」「管理员跨组织读取」「员工发布任务」四类越权场景，全部预期被拒绝

### Requirement: 内容层与进度层分离

系统 SHALL 把内容（资料来源、切片、训练项的题干与答案、关键句、结构难度、来源回指）
按组织保存一份，并把进度（作答记录、评测结果、经验难度、完成状态、路径进度）按人保存。
系统 MUST NOT 把一个用户的作答数据写入内容层。

#### Scenario: 内容只加工一次

- **WHEN** 同一份企业公共区资料被多名员工使用时
- **THEN** 解析、切片、打标与出题只执行一次
- **THEN** 多名员工共用同一批训练项内容

#### Scenario: 进度按人隔离

- **WHEN** 两名员工使用同一道训练项
- **THEN** 各自的作答记录、经验难度与完成状态分别保存，互不影响

#### Scenario: 人群经验难度聚合

- **WHEN** 需要为新员工提供经验难度参考
- **THEN** 系统按人群标签聚合，且样本量低于设定的最小样本量时回退到结构难度
