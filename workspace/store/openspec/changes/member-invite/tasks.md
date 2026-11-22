# member-invite · 任务清单

> 按依赖顺序编号。**实施前先过 design.md 文末的四个待拍板项**（其中第 1 项
> "是否取消注册自动进默认组织"会改变对外行为，必须用户明确确认）。

## 1. 数据层

- [ ] 1.1 `memberships` 迁移：role CHECK 迁移（employee→member、dept_manager→admin）、
      新列 `invited_by` / `admin_quota` / `admin_can_remove`
  - 验收：老库迁移后存量成员角色正确映射、新列就位、数据零丢失；`test_db_schema` 同步
- [ ] 1.2 新表 `org_invites`（站外邮箱挂起邀请；MVP 可与 2.3 一起做）
  - 验收：UNIQUE(org_id, email)；status CHECK 四态
- [ ] 1.3 注册流程移除自动准入（provision 不再对无名单用户建默认组织成员资格）
  - 验收：新注册用户的 memberships 为空、viewer 解析为个人模式；存量用户不受影响

## 2. 权限矩阵（个人版三档）

- [ ] 2.1 `permissions.py`：Role = org_admin/admin/member；动作矩阵按对齐设计重写
      （成员互看进度=完成状态+分数聚合；判分区零改动）
  - 验收：单测逐角色×动作；`can_view_training` 在组织语义下保持 owner/组织两级
- [ ] 2.2 配额与开关：`invite_member` 配额校验、`remove_member` 开关校验、
      org_admin 逐人设置端点
  - 验收：边界测试（9/10/11、开关开/关、org_admin 不受限）

## 3. 端点

- [ ] 3.1 候选列表 `GET /api/org/{org_id}/candidates`（搜索过滤）
- [ ] 3.2 邀请 `POST /api/org/{org_id}/invite`（站内建 invited；受配额）
- [ ] 3.3 成员列表带 invited 标记 + 移除端点（admin 受开关 / org_admin 总可）
- [ ] 3.4 被邀请人 `GET /api/my/invites` + `POST /api/my/invites/{id}/accept`
- [ ] 3.5（可选，待拍板）站外邮箱邀请 `org_invites` + 邀请链接注册自动接受

## 4. 前端

- [ ] 4.1 成员管理页：候选搜索 + 拉人按钮（显示剩余配额）+ 移除/升降/配额设置
      （org_admin 专属）
- [ ] 4.2 「我的邀请」入口（被邀请人侧）+ 接受/忽略
- [ ] 4.3 新注册用户的引导：个人模式提示（"创建小组或等待邀请"）
  - 验收：三个流程手工走通；构建通过

## 5. 证据与收尾

- [ ] 5.1 端到端演示记录（evidence）：org_admin 建组 → admin 邀请（配额内）→
      成员接受 → 拉取共享计划 → 进度互见聚合口径验证
- [ ] 5.2 `openspec validate` 通过并归档

## 待拍板（阻塞项，见 design.md 文末）

- [x] 拍板 1：取消"注册自动进默认组织"——**已决议（2026-11-22）：取消**，邀请制为准
- [x] 拍板 2：个人版角色迁移与邀请流程同批实施——**已决议（2026-11-22）：同批**
- [x] 拍板 3：站外邮箱邀请——**已决议（2026-11-22）：后置**，MVP 只做站内拉人
- [x] 拍板 4：普通成员互看进度的聚合口径——**已决议（2026-11-22）：完成状态+分数聚合**

> 拍板齐备（2026-11-22），与 `share-gate` 同批实施；实施顺序建议：本 change 数据层 →
> `share-gate` 数据层 → 两者服务/端点/前端可并行。
