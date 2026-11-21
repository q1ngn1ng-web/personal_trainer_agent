# 2026-11-21 · 内容三档可见性（content-visibility）

> 类型：feat ｜ 对应 change：`content-visibility`（已实施）｜ commit：`325ec89`

## 变更摘要

用户报告：新注册的 q2ng 进去直接看到 q1ng 的全部训练。排查出可见性有两套
互相矛盾的旧口径（owner NULL → 同组织可见；owner 落库 → 仅本人），资料
scope 四档有名无实（department/assigned 无判定无 UI）。统一为三档：

- **数据层**：`trainings.visibility` + `training_shares` / `source_shares`；
  `sources.scope` 迁移重建为三档 CHECK（org_shared→public，其余→private）；
  历史 owner NULL 训练回填给实际使用者（5 条 → q1ng/user 6）；
- **判定层**：`can_view_training` / `can_view_source` 三档（owner 恒可见 /
  public 同组织 / specific 指定人 / private 仅 owner / 跨组织拒绝）；
- **端点层**：PUT × 2（owner 或 publish_assignment），指定人按邮箱服务端解析
  为本组织在册成员（个人用户无成员列表权限，绕开 admin-only 查询端点）；
- **前端**：详情页训练级 + 每条资料可见性选择器；资料总览迁至训练页。

## 排查与两个真 bug

1. **全量 49 失败**：三档 CHECK 上线后，写入端还在写旧值 `personal`
   （create_source/模型默认/克隆硬编码）——CHECK 约束把所有建资料路径打挂。
   修写入端 + 枚举同步，10 个测试文件的契约测试随默认值更新；
2. **列表过滤不生效**（线上验证发现）：PUT 生效但 q3ng 列表仍看不到 public 训练
   —— `_training_payload` 没带 `visibility`，`row.get("visibility")` 恒 None →
   恒按 private。**函数级测试盖不住 payload 缺字段的接线缺口**，新增端点级
   四态回归钉子（`test_trainings_list_reflects_visibility`）。

另修：`_load_training_for` 与列表端点原先漏了 shares 补洞（specific 分享给
我的训练进详情会 403）——统一为"判定时带该内容的 shares 分组"。

## 验证

- 全量 **363 passed + 30 subtests**（含新增 4 个可见性用例）；`npm run build` 通过；
- 线上实测（q1ng ↔ q3ng）：初始隔离 0 → public 可见 1 → specific 按邮箱指定
  可见 1（详情 200）→ 改回 private 隔离恢复 0（详情 403）；
- 服务已重启（PID 505190，端口 8501）。

## 纪律备注

- 旧 scope 写入端清理与旧契约测试改写属于**最小关联联动**（不改则建资料路径
  全挂），已在 proposal 联动说明申报；
- `docs/architecture.md`（并行改动）与 `web/index.html`（行尾噪音）未纳入本提交。
