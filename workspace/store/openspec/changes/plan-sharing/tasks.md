# plan-sharing · 任务清单

> 按依赖顺序编号。每个任务写明验收方式。实施前先过 4.6 的三个待拍板项。

## 1. 数据层

- [ ] 1.1 新增 `share_links` 表（tables.sql + migrate 重建守卫）
  - 验收：全新库 `init_db` 含该表；token 有 UNIQUE 约束；`test_db_schema.py` 表清单更新
- [ ] 1.2 `trainings` 补 `shared_from_training_id` / `shared_by_user_id` 两列（ALTER 轻量迁移）
  - 验收：老库迁移后两列存在；新库 DDL 含两列

## 2. 克隆服务

- [ ] 2.1 `training_clone_service.clone_for_user(training_id, target_user_id)`：
      单事务内按 design 复制清单（trainings → sources → source_chunks →
      question_bank → question_points → 路径骨架 → generate_plan 重锚拉取日）
  - 验收：克隆后逐表抽查——副本资料切片数与原一致、题库练习计数归零、
    `practice_attempts` 计数为 0、副本训练项 `source_chunk_ids` 回指新 chunk id
- [ ] 2.2 幂等：同用户对同来源重复克隆返回已有副本
  - 验收：单测断言不产生第二个训练

## 3. 端点

- [ ] 3.1 `POST /api/trainings/{id}/share/link`（owner 或组织管理员；幂等返回 token）
  - 验收：非 owner 403；重复调用返回同一 token
- [ ] 3.2 `GET /api/share/{token}`（预览：结构 + 验收标准，无题库/参考答案）
  - 验收：响应断言不含 `question`/`reference_answer`/`points` 字段
- [ ] 3.3 `POST /api/share/{token}/pull`（同组织成员；幂等）
  - 验收：组织内成员拉取成功；非组织成员 403；重复拉取返回同一训练 id
- [ ] 3.4 `POST /api/trainings/{id}/share/members`（owner；逐成员克隆）
  - 验收：指定两个成员 → 各自得到独立副本；非组织成员被跳过并报告

## 4. 前端

- [ ] 4.1 训练详情页「分享」入口：生成链接 + 复制到剪贴板 + 推送给指定成员选择器
- [ ] 4.2 预览页（/share/{token} 路由）：计划结构展示 + 「拉取为我的训练」按钮
- [ ] 4.3 「我的训练」列表：副本带「来自分享」来源标记，点击可进入
  - 验收：三个入口手工走通；构建通过

## 5. 证据与收尾

- [ ] 5.1 端到端演示记录（evidence）：A 建训练 → 分享链接 → B 拉取 → 双方各自作答 →
      进度互不影响的截图/断言
- [ ] 5.2 `openspec validate` 通过并归档

## 待拍板（实施前确认）

- 题库副本的冷却期/练习计数重置口径（design 默认：全部重置）
- 链接撤销 UI（数据层已留 `revoked_at`，MVP 不做界面）
- 纯个人（无组织）用户之间的分享形态（MVP 限组织内）
