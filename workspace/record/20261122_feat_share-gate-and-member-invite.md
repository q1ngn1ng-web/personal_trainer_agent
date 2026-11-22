# 2026-11-22 · 分享门禁与开放链接（share-gate）+ 成员邀请（member-invite）

> 类型：feat ｜ 对应 change：`share-gate`（tasks 全勾）、`member-invite`（站外邀请按拍板 3 后置）
> 双 change 同批实施（实施顺序按 member-invite tasks 文末建议：数据层先行，服务/端点/前端并行）
> 判分区文件零接触（两 change 的共同纪律）

## share-gate（建立在 content-visibility 之上，不重做可见性）

- **数据层**：`share_links.open_level`（org/anyone，默认 org；CHECK 列重建迁移；
  **修掉一个重复 DDL 隐患**——migrate 里新旧两份 `_SHARE_LINKS_DDL` 并存导致导入期旧版覆盖新版）
- **门禁服务**（`share_gate_service.py` 纯函数）：四类出向动作（publish/link_org/
  link_anyone/push）→ 受众级（public / specific(U)）；blocked 清单=enabled 文档逐份
  比较可见级（specific 按 source_shares 授权是否覆盖全部目标，标注 uncovered_targets）
- **两步协议**：`POST /share/gate`（只读）→ `POST /share/confirm`（单事务：定向升级
  + 分享动作，无部分生效）；确认集不完整 → 409 带最新清单
- **三端点收紧（行为变化申报）**：`POST /share/link`（新增 open_level + 一步式
  confirm_source_ids）、`POST /share/members`（push 接门禁——**顺带修掉原子性缺陷**：
  push_to_members 原先给 clone 开独立连接，升级未提交时撞写锁且违反同事务要求）、
  `PUT visibility`（目标 public 时接门禁）
- **开放通道**：pull_by_token 按 open_level 放宽（anyone → 任何登录用户，跨组织/
  无组织均可；org 链接回归不变）；clone_for_user 增 require_same_org 参数；
  预览不泄露题库的规则对 anyone 同样生效
- **审计**：确认写 `workspace/record/share-gate-confirmations.md`（谁/何时/哪次分享/
  哪些 source_id——design D5：MVP 不建新表）

## member-invite（四项拍板全部落地）

- **数据层**：memberships 三档角色迁移（employee→member、dept_manager→admin；
  **CASE 归一在复制时做**——先 UPDATE 会撞旧 CHECK 的真坑）+ invited_by/
  admin_quota/admin_can_remove 三列；sessions.org_id 放宽可空
- **注册不再自动进组（拍板 1）**：新用户 memberships 为空，viewer 解析为个人模式
  （org_id=None、member 档）——可见性判定加无组织分支（只看自己的训练）；
  `POST /api/org/create` 建组（个人用户 → org_admin）
- **邀请流**：候选列表（已注册 ∧ 非本组成员，搜索）→ 邀请（invited + invited_by；
  admin 受配额默认 10、org_admin 不限；**升 admin 必须同时给配额**）→ 我的邀请
  （GET/accept，invited→active，接受后共享计划拉取自动可用）→ 移除（admin 受
  admin_can_remove 开关且只能移 member；org_admin 总可）→ 角色升降（org_admin 专属）
- **互看进度（拍板 4）**：`GET /org/{id}/members/{uid}/progress` = 完成状态
  （passed/total）+ 分数聚合（avg quiz score），只聚合 public 训练，不暴露作答明细

## 排查中抓到的接线缺口（函数级测试盖不住的同类问题）

1. **wizard_start 不写 org_id**：新用户建训练 org NULL，而有组织用户的可见性按
   org 匹配 → 403。修复：wizard_start 把 viewer.org_id 一并落库（线上冒烟抓出）；
2. **push_to_members 丢 conn**：升级与推送不在同一事务（见上）；
3. **migrate 重复 DDL 常量**：`_SHARE_LINKS_DDL` 新旧两份并存，Python 导入期后者
   覆盖前者 → 新库建出的 share_links 没有 open_level → 幂等迁移重复触发
   （test_grading_service 的"迁移可重复执行"断言抓出）。

## 验证

- `tests/test_share_gate_and_invite.py` 26 用例：门禁矩阵（三档×四动作+specific
  部分覆盖）、不完整确认无部分生效、全选一次事务（升级+链接+推送）、审计落账、
  anyone 跨组织/无组织拉取幂等、org 链接回归、两级链接并存、预览不泄露、
  注册个人模式、角色迁移映射与矩阵、邀请配额/接受/移除开关/进度聚合；
- 全量 **402 passed**（唯一失败=并行基线已有 renderer 在飞项）；`npm run build` 通过；
- 线上 evidence：q1ng 体系外建组 → 邀请/接受 → 训练挂 2 份私有文档 → gate 查询
  （blocked 2）→ 未确认 409 → 全选确认 409→200（升级 2 份 + anyone 链接）→
  跨用户预览 200 且不含 question_text（服务已重启）。
