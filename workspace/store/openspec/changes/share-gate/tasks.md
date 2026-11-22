# share-gate · 任务清单（已实施 2026-11-22）

> 按依赖顺序编号。
> 实施前先读 design.md 的「依赖的已实施事实」，改动集中在 share 链路，判分区零接触。

## 1. 数据层

- [x] \1（TEXT，CHECK `org/anyone`，DEFAULT `org`）
      ——tables.sql + migrate ALTER + schema 守卫
  - 验收：全新库含列与默认值；老库迁移后存量链接 open_level='org'（行为不变断言）

## 2. 门禁服务

- [x] \1：`audience_level(action, targets)` +
      `blocked_sources(training_id, audience)`（引用集=enabled 文档；
      specific 需授权覆盖全部目标；产出 blocked 清单与 uncovered 标注）
  - 验收：单测覆盖三档 × 四动作矩阵 + specific 部分覆盖场景
- [x] \1：push 目标解析走 content-visibility 的
      `VisibilityBody.shared_emails` 同款规则（本组织在册，未命中 400 列清单）
- [x] \1（只读）与 `confirm` 事务端点（升级 + 分享动作原子）；
      确认集不完整 → 409 + 最新清单，无部分生效
  - 验收：全选确认后文档升级与链接生成/推送一次完成；缺一确认整体回滚

## 3. 既有端点接入（行为收紧，需用户可见说明）

- [x] \1 接受可选 `open_level` 与 `confirm_source_ids`
      （齐全一步完成；不齐 409 带清单）
- [x] \1（push）同款接入
- [x] \1 目标为 public 时接入门禁
  - 验收：三类端点各一条"未确认被拒 + 确认后放行"端点级用例
      （接线缺口教训：payload 级断言，不只测函数）

## 4. 开放通道

- [x] \1 按 open_level 放宽
      （anyone → 任何登录用户；未登录仍 401；org 链接行为不变）
- [x] \1：先训练可见性（private → 仅 owner），再链接开放级
  - 验收：跨组织用户 anyone 链接拉取成功 + 幂等；org 链接仍拒非成员（回归）；
      anyone 预览不含 question_text/reference_answer/points（沿用 plan-sharing 断言）

## 5. 前端

- [x] \1：gate 查询 → 缺失文档清单（标题/当前可见性/受众说明）
      + 逐个勾选 + 全选 + 确认提交（confirm 端点）；409 清单过期自愈（刷新重显）
- [x] \1（anyone 附"任何登录用户可导入"提示）
- [x] \1在目标为 public 时走同一确认流
  - 验收：publish / link_org / link_anyone / push 四路径手工走通；构建通过

## 6. 审计与收尾

- [x] \1 `workspace/record/` 变更记录（谁/何时/哪次分享/哪些 source_id）
- [x] \1：q1ng 含私有文档的计划 → 生成 anyone 链接（被阻 → 全选确认 →
      成功）→ q2ng（跨组织）拉取成功且预览不泄露题库 → 双方进度互不影响
- [x] \1 通过并归档

## 明确不做（本期）

部分确认/题库裁剪（未确认文档的题库不分享）｜公共广场列表页｜独立资料库｜
订阅式共享｜判分区任何改动
