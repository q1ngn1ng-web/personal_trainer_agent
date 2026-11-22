# member-invite · 设计

## 现状事实（2026-11-15 探针证实）

1. **注册即自动进默认组织**：register → provision 流程会给新用户建
   `memberships(user, org 1, employee, active)`——所有新用户无差别同组。
2. **成员资格状态机现成**：`memberships.status ∈ invited / active / disabled`。
3. **企业版名单流程现成但形态不符**：roster 预导入 + issue-login（公司分发培训）。
4. plan-sharing 拉取副本时校验"接收者是训练所属组织的在册成员"——
   邀请进组后，共享计划的拉取自动可用（零改动）。

## 核心设计：候选数据模型（"哪些人能被拉入同一个组织"）

**候选 = 已注册用户 ∧ 不是该组织的在册/挂起成员**。两个入口覆盖全部场景：

| 场景 | 入口 | 数据动作 |
| --- | --- | --- |
| 拉已注册用户（站内） | 成员页候选列表（按邮箱/昵称搜索） | 直接建 `memberships(status='invited', invited_by=管理员)` |
| 拉未注册的人（站外） | 邀请链接（含 org token）或邮箱邀请 | 建挂起记录；对方注册时命中挂起邀请 → 自动建 invited 成员资格 |

**默认组织语义（关键待决项）**：现状注册即进 org 1。本 change 的目标态：
新注册用户**不再自动进任何组织**（org_id NULL、viewer 解析为个人模式），
"我的小组"完全由邀请产生。这一条改变对外行为，**必须用户拍板**（见文末）。
过渡兼容：老用户的 org 1 成员资格保留不动。

## 数据模型

```sql
-- memberships 变更
ALTER TABLE memberships ADD COLUMN invited_by INTEGER;   -- 邀请人（配额归属）
-- role CHECK 迁移：('org_admin','dept_manager','employee') → ('org_admin','admin','member')

-- 站外邀请的挂起记录（站内邀请直接建 memberships.invited，不需要本表）
CREATE TABLE org_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    invited_by INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'expired')),
    created_at DATETIME NOT NULL,
    accepted_at DATETIME,
    UNIQUE (org_id, email)
);

-- 每管理员配额与删除开关（个人版三档角色的托管语义）
ALTER TABLE memberships ADD COLUMN admin_quota INTEGER;      -- NULL=非管理员/不限
ALTER TABLE memberships ADD COLUMN admin_can_remove INTEGER DEFAULT 0;
```

## 配额与开关（托管式管理）

* `invite_member`（admin 调用）：校验 `COUNT(memberships WHERE invited_by=管理员
  AND status IN ('invited','active')) < admin_quota`（默认 10，组织管理员逐人设置）；
* `remove_member`（admin 调用）：需 `admin_can_remove=1`（默认 0）；仅可移除
  `member` 档成员，不可动 admin/org_admin；
* org_admin：不受配额、总可移除任何人、可升降 admin 与逐人设配额；
* **角色↔配额的对称性**：把某人升为 admin 时必须同时给配额（默认 10）。

## 端点与权限

| 端点 | 方法 | 权限 | 行为 |
| --- | --- | --- | --- |
| `/api/org/{org_id}/candidates` | GET | admin+ | 候选列表（已注册 ∧ 非本组织成员，支持搜索） |
| `/api/org/{org_id}/invite` | POST | admin+（受配额） | 站内：建 invited 成员资格；站外：建 org_invites + 返回邀请链接 |
| `/api/org/{org_id}/members` | GET | 成员 | 成员列表（含 invited 待接受标记；普通成员可见聚合） |
| `/api/org/{org_id}/members/{uid}` | DELETE | admin（受开关）/ org_admin | 移除成员（成员资格置 disabled，数据保留） |
| `/api/org/{org_id}/members/{uid}/role` | PUT | org_admin | 升降 admin / 逐人配额与开关 |
| `/api/my/invites` | GET/POST | 被邀请人 | 查看/接受邀请（invited → active） |

## 邀请接受语义

* 站内邀请：被邀请人登录后「我的邀请」显示待接受项 → 接受 → `invited → active`；
* 站外链接：未注册者经邀请链接注册，命中 `org_invites(token)` → 自动建
  membership(active) 并消费邀请；
* **拒绝/忽略**：被邀请人可忽略（邀请长期有效）或明确拒绝（status → expired）；
* 过期策略：MVP 不做自动过期（邀请长期有效，管理员可手动撤销）。

## 与 plan-sharing 的衔接

邀请接受（active）后，该成员即满足"拉取副本的组织成员校验"——共享计划对
新成员自动可见可拉取。本 change 不改 plan-sharing 任何代码。

## 待用户拍板（实施阻塞项）

1. **新注册用户是否保留"自动进默认组织"**？目标态是不自动（邀请制），
   但这改变所有新用户的默认体验——需要明确确认。
2. **MVP 是否同时落"个人版三档角色迁移"**（employee→member、取消
   dept_manager 档）？还是先沿用现角色值只加邀请流程（推荐：一起做，避免两次迁移）。
3. 站外邮箱邀请（org_invites + 邀请链接）MVP 是否纳入，还是先只做站内拉人。
4. 普通成员互看进度的粒度（聚合口径）沿用上轮对齐的"完成状态＋分数聚合"。
