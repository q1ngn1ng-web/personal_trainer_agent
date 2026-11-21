# content-visibility · 设计

## 关键决策

### D1 · 训练与资料同口径，一套判定函数

`can_view_training` 与 `can_view_source` 同一形状：
`(viewer, row, shared_user_ids?) → bool`，三档语义逐字一致。资料没有独立 owner 列，
owner 取所属训练的创建者（调用方 join 提供）。

备选：资料沿用独立四档（personal/department/assigned/org_shared）。放弃：
department / assigned 无判定逻辑与 UI（有名无实），四档里两档是死代码；同口径
让"谁能看到什么"一次讲清。

### D2 · 指定人按邮箱解析，不开放成员列表

个人用户无 `/api/org/members` 权限（admin-only），前端选人不可行。改为前端
**邮箱输入**（逗号分隔），`VisibilityBody.shared_emails` 服务端解析：
`users ⋈ memberships`（本组织 + active），未命中 → 400 列出具体邮箱。
解析与校验在同一端点内完成，无新增端点、无权限面扩大。

### D3 · 历史数据迁移映射

- `sources.scope` 重建为三档 CHECK：`org_shared → public`，其余（personal 等）→ private；
- `trainings.visibility` ALTER 默认 private；
- owner 为 NULL 的历史训练回填给实际使用者（生产库 5 条 → q1ng/user 6），
  回填后"同组织可见"的旧行为消失，隔离即刻生效。

### D4 · 列表 payload 必须携带 visibility（回归钉子）

首轮线上验证发现：PUT 生效但列表过滤不生效——`_training_payload` 没带
`visibility`，`row.get("visibility")` 恒 None → 恒按 private 处理。函数级测试
（直接调 `can_view_training`）盖不住 payload 缺字段这类**接线缺口**，
新增端点级用例 `test_trainings_list_reflects_visibility` 钉死四态
（private 藏 / public 见 / specific 指定见 / 改回 private 藏）。

### D5 · 过滤统一走 shares 分组，不靠"共享给我的 id 并集"

`GET /api/trainings` 与资料端点的过滤改为按 `training_shares` / `source_shares`
按 key 分组后逐行判定；`_load_training_for` 同样带该训练的 shares。此前
`_visible_training_ids` 用"可见集合 ∪ 共享给我的 id"补洞，列表端点漏了同款
补洞——统一成"判定时带 shares"后不再有两套口径。
