# content-visibility Specification

## ADDED Requirements

### Requirement: 训练可见性三档

训练 SHALL 支持三档可见性：`private`（默认，仅 owner）、`specific`（owner +
指定成员）、`public`（同组织成员）。owner 恒可见；跨组织一律不可见；
owner 缺失的历史数据沿用同组织可见口径。

#### Scenario: 私有训练对他人不可见

- **WHEN** owner 以外的同组织成员列出或访问一个 private 训练
- **THEN** 该训练不出现在训练列表中，直接访问返回 403

#### Scenario: 公开训练对同组织可见

- **WHEN** owner 将训练设为 public
- **THEN** 同组织的任何成员都能在训练列表中看到并访问该训练
- **THEN** 非本组织成员仍不可见

#### Scenario: 指定人可见且可替换

- **WHEN** owner 将训练设为 specific 并指定成员集合
- **THEN** 被指定的成员可见、未指定的不可见
- **WHEN** owner 再次设置 specific 指定另一批成员
- **THEN** 授权表按替换语义更新（旧集合清空，新集合生效）

### Requirement: 资料可见性与训练同口径

资料 SHALL 复用同一三档语义，owner 取所属训练的创建者；
每条资料可独立设置可见性。

#### Scenario: 资料按自身 scope 判定

- **WHEN** 一条资料被设为 specific 并指定成员
- **THEN** 该资料仅 owner 与被指定成员可见，训练内其他成员不可见

### Requirement: 可见性仅 owner 或组织管理员可改

修改训练或资料的可见性 SHALL 仅允许 owner 或拥有
`publish_assignment` 权限的组织管理员；非法取值返回 400。

#### Scenario: 非 owner 修改被拒

- **WHEN** 非 owner 且无 publish_assignment 权限的成员调用可见性修改端点
- **THEN** 返回 403，可见性与授权表不变

#### Scenario: 指定成员按邮箱解析

- **WHEN** owner 提交 `shared_emails` 邮箱列表
- **THEN** 系统解析为本组织在册成员的 user_id 落授权表
- **WHEN** 邮箱不存在或不属于本组织
- **THEN** 返回 400 并列出未命中的邮箱，不产生部分写入

### Requirement: 列表与详情端点携带可见性口径

训练列表 payload SHALL 携带 `visibility` 字段，列表 / 详情 / 资料端点的
过滤 SHALL 基于同一判定函数与 shares 数据。

#### Scenario: payload 缺字段不回退为私有

- **WHEN** owner 将训练设为 public 或 specific 后列表被拉取
- **THEN** 指定/同组织成员能看到该训练（payload 未携带 visibility 视为回归缺陷）
