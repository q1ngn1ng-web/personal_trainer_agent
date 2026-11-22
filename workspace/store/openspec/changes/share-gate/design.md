# share-gate · 设计

> 对应 proposal.md。实施前先读依赖两 change 的已实施代码：
> `src/services/training_clone_service.py`（克隆/链接/推送）、`src/core/permissions.py`
> （三档判定与 shares）。

## 依赖的已实施事实（2026-11-22 复核）

* `content-visibility`（`325ec89`）：`trainings.visibility` 与 `sources.scope` 均为
  `private/specific/public` 三档；`training_shares`/`source_shares` 按 user 授权；
  指定人按邮箱在 PUT 端点内解析（`VisibilityBody.shared_emails`）；
  列表/详情过滤已带 shares。
* `plan-sharing`（`e75fc84`）：`share_links`（token/created_by/revoked_at）、
  `pull_by_token` 校验组织成员、`get_share_preview` 不泄露题库、
  `clone_for_user` 幂等克隆、`push_to_members` 推送。

## D1 · 开放级别落在链接上，不动训练三档

`share_links.open_level ∈ {org, anyone}`（`TEXT DEFAULT 'org'`，ALTER 加列，
存量链接与现行行为零变化）：

* `org`（默认）：现行语义——本组织在册成员可预览/拉取；
* `anyone`：任何**登录用户**可预览/拉取（跨组织、无组织个人均可用）。

拉取授权统一式（`pull_by_token` 内实现）：

```
allow = is_org_member(user, training.org)          # 现行
     or link.open_level == 'anyone' and logged_in  # 新增
```

预览端点同规则放宽（anyone 链接未登录仍拒——预览内容含计划结构，登录是最低门槛，
且与现行"未登录预览 401"一致）。

## D2 · 受众级（audience）——门禁的比较基准

四类分享动作各自对应一个受众可见级，门禁用它比较文档达标情况：

| 分享动作 | 受众级 | 文档达标条件 |
| --- | --- | --- |
| 训练 visibility → `public` | `public` | 文档 = public |
| 生成 `org` 链接 | `public` | 文档 = public（组织公开受众=组织成员=public 档受众） |
| 生成 `anyone` 链接 | `public` | 文档 = public |
| 推送指定成员 | `specific(U)` | 文档 = public，或 specific 且 `source_shares` 覆盖 U 全部成员 |

文档可见级偏序：`private(0) < specific(1) < public(2)`；specific 的比较按授权集
是否覆盖目标成员。**引用集** = `sources WHERE training_id = 训练 AND enabled = 1`。

## D3 · 门禁两步协议（查询 → 事务确认）

**第一步 `POST /api/trainings/{id}/share/gate`**（只读，不产生副作用）：

```jsonc
// body: {"action": "publish" | "link_org" | "link_anyone" | "push",
//        "target_emails": ["a@x.com"]            // 仅 push 必填，复用邮箱解析
//        "open_level": "org" | "anyone"}          // link_* 时冗余校验
// 200 响应：
{
  "blocked": [
    {"source_id": 3, "title": "Redis 八股文.pdf", "visibility": "private"}
  ],
  "targets_resolved": [{"user_id": 11, "email": "a@x.com"}],  // push 时
  "ready": false        // blocked 非空即 false
}
```

邮箱解析复用 content-visibility 的规则（本组织在册成员，未命中 400 列出）。

**第二步 `POST /api/trainings/{id}/share/confirm`**（单事务）：

```jsonc
// body: 第一步的完整参数 + {"confirm_source_ids": [3, 7]}
// 服务端校验：confirm_source_ids ⊇ blocked 的全部 source_id，缺一即 409
//   （响应带回最新 blocked 清单——前端清单过期时能自愈）
// 事务内依次执行：
//   1. 定向升级：publish/link_* → 文档 UPDATE visibility='public'；
//      push → specific + source_shares 写入目标成员授权
//   2. 执行分享动作：publish → trainings.visibility='public'；
//      link_* → create_share_link(open_level)；push → push_to_members
// 200 响应：分享动作各自的现有载荷（token / delivered / …）
```

「全选」纯前端行为：把全部 blocked id 放进 `confirm_source_ids`，服务端无特判。

## D4 · 既有端点的门禁接入（破坏性收紧的申报）

以下既有端点改为**先过门禁**，未确认（请求未携带覆盖全部 blocked 文档的确认）时
返回 409 + blocked 清单——这是对外行为变化，需要在对应用户可见文案里说明：

* `POST /api/trainings/{id}/share/link` → 建议改为接受可选 `confirm_source_ids`，
  携带齐全则直接事务完成（一步式），不齐则 409 带清单（两步式的兜底）；
* `POST /api/trainings/{id}/share/members`（push）→ 同上；
* `PUT /api/trainings/{id}/visibility`（content-visibility 的端点）当目标为 `public`
  时 → 同上。

前端统一走"gate 查询 → 对话框确认 → confirm 提交"两步流，一步式参数留给
无对话框的场景（脚本/测试）。

## D5 · 升级的可逆性与审计

* 确认升级是持久的（proposal 已决策）：文档可见性被抬高后**不会自动回落**，
  所有者可随时再 PUT 改回（改回后已生成的 anyone 链接在下次拉取时重新过门禁
  ——见 D6）；
* 每次确认写入 `record/` 变更记录（谁在何时为哪次分享确认了哪几份文档）；
  审计粒度到 source_id，MVP 不建新表（record 文件即审计账）。

## D6 · 撤销与降级后的存量链接

* `anyone` 链接的**生成时点**过门禁；文档事后降级**不追溯**已生成的链接
  （拉取不重新校验文档级——克隆语义本来就是全量复制）。
  撤销路径：owner 撤销链接（plan-sharing 已有 revoke 数据层）或把训练降回
  private/org（链接仍在但训练可见性收口，预览与拉取以训练可见性+链接级双门槛判定）。
* 双门槛判定顺序：先训练可见性（private → 仅 owner 可拉），再链接开放级。

## 待实施确认（不阻塞规格）

1. `gate`/`confirm` 挂在训练维度的路径下（`/api/trainings/{id}/share/*`），
   与现有 share 端点同居——无需新前缀。
2. blocked 清单的 `visibility` 字段用 content-visibility 的现值（private/specific），
   specific 但授权不覆盖目标时单独标注 `uncovered_targets: true`。
