# content-visibility · 任务清单（已实施）

## 1. 数据层

- [x] 1.1 `trainings.visibility` 列（private/specific/public，默认 private）+ 两张 shares 表（tables.sql + 迁移守卫）
- [x] 1.2 `sources.scope` 三档重建迁移（org_shared→public，其余→private）
- [x] 1.3 历史 owner 为 NULL 的训练回填（生产库 5 条 → q1ng/user 6）
  - 验收：q2ng/q3ng 注册后列表为空（线上实测 ✓）

## 2. 判定层

- [x] 2.1 `can_view_training` 三档（owner/public/specific/private + 跨组织拒绝）
- [x] 2.2 `can_view_source` 同口径（owner=训练创建者）
- [x] 2.3 `SourceScope` 枚举同步三档
  - 验收：`test_content_visibility` 三档判定用例 ✓；`test_auth_personal` 契约改写 ✓

## 3. 端点层

- [x] 3.1 PUT 训练/资料可见性（owner 或 publish_assignment；非法取值 400）
- [x] 3.2 `shared_emails` 邮箱解析（本组织 active 成员；未命中 400 列明细）
- [x] 3.3 列表 / 详情 / 资料端点接入 shares 过滤；`_training_payload` 携带 visibility
  - 验收：`test_trainings_list_reflects_visibility` 四态钉子 ✓；线上 q1ng↔q3ng 四步实测 ✓
- [x] 3.4 `_TRAINING_FIELDS` 白名单补 visibility
  - 验收：端点更新不再 ValueError ✓

## 4. 写入端清理（联动）

- [x] 4.1 `create_source` / `create_source_from_file` / `Source` 模型默认 scope → private
- [x] 4.2 克隆服务沿用来源自身 scope（原硬编码 'personal'）
  - 验收：全量 363 passed（修复前 49 处 IntegrityError）

## 5. 前端

- [x] 5.1 训练详情页：训练级 + 每条资料可见性选择器（指定人邮箱输入）
- [x] 5.2 资料总览从桌面迁至训练页
  - 验收：`npm run build` 通过 ✓
