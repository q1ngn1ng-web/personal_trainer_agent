# content-visibility · 内容三档可见性（训练与资料同口径）

> **状态：已实施**（commit `325ec89`，2026-11-21）。
> 用户需求原话（2026-11-21）：新注册用户进去能直接看到别人的训练——
> "注册一个新用户 q2ng，进去是直接用用户 q1ng 的训练"；要求训练与资料
> 都有「私有 / 指定人 / 组织公开」三档；资料总览放到训练页。

## Why

可见性此前只有一条隐式规则：**同组织即全可见**（owner 缺失时）或**仅 owner**（owner
落库后）——两套口径并存且互相矛盾：

1. 历史数据 `owner_user_id` 为 NULL 的训练沿用"同组织可见"——q2ng 注册后直接
   看到 q1ng 的全部训练（跨用户越权的可见性版本）；
2. 资料的 `scope` 只有 `personal / org_shared` 两档，且**写入端仍在写 `personal`**、
   `department / assigned` 档位有名无实（无判定逻辑、无 UI）。

用户要的是可解释的三档：**私有（默认）/ 指定人 / 组织公开**，训练与资料同口径。

## What Changes

* **数据层**：`trainings.visibility`（private/specific/public，默认 private）+
  `training_shares` / `source_shares` 两张指定成员授权表；`sources.scope` 从两档
  重建为三档 CHECK（迁移按旧值映射：org_shared→public，其余→private）；
  历史 owner 为 NULL 的训练回填给实际使用者（q1ng，user 6）。
* **判定层**：`can_view_training` / `can_view_source` 统一三档——owner 恒可见；
  public 同组织可见；specific = owner + 指定成员；private 仅 owner；跨组织一律不可见。
* **端点层**：PUT 训练/资料可见性（仅 owner 或组织管理员）；指定人按**邮箱**
  输入、服务端解析为本组织在册成员（个人用户无成员列表权限，绕开 admin-only
  的成员查询端点）；列表 / 详情 / 资料端点接入 shares 过滤，payload 必须携带
  visibility（端点级回归钉子）。
* **前端**：训练详情页新增训练级 + 每条资料的可见性选择器（指定人 = 邮箱输入）；
  资料总览从桌面迁至训练页。

### 联动说明（按最小关联原则申报）

- 旧 scope 写入端清理：`create_source` / `create_source_from_file` 默认值、
  `Source` 模型默认、克隆服务沿用来源自身 scope——原 `'personal'` 撞新 CHECK，
  **不改则全部建资料路径 IntegrityError**（全量 49 处失败证实）；
- `test_auth_personal` 的四档契约测试改写为三档契约（旧四档已被本 change 取代）；
- `test_source_service` 默认 scope 断言随默认值更新。

## 验证

- 全量 363 passed + 30 subtests；`test_content_visibility` 四用例钉死三档判定、
  端点 owner-only、shares 替换语义、列表 payload 携带 visibility；
- 线上实测（q1ng ↔ q3ng）：初始隔离（0 个训练）→ public 可见（1）→
  specific 按邮箱指定可见（1，详情 200）→ 改回 private 隔离恢复（0，详情 403）。
