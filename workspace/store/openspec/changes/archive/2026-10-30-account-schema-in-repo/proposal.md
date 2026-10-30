# account-schema-in-repo · 账户/组织 10 张表 DDL 入库

## Why

仓库的 schema 唯一来源是 `src/db/tables.sql`（`init_db` 用 `executescript` 执行，见 `src/db/sqlite.py:33-37`），
但实测 `data/trainer.db` 有 33 张普通表，`tables.sql` 只定义 23 张——
`users / sessions / login_tokens / organizations / departments / memberships / roster_entries /
assignments / assignment_targets / assignment_receipts` 共 **10 张账户与组织表的 DDL 不在任何仓库文件里**。

这些表不是"企业版预留"：**个人版注册登录自己就踩在上面**——
`auth_service.register_account` 调用 `org_service.upsert_roster_entry` / `provision_user_from_roster`，
每次请求 `resolve_viewer` 读 `memberships` / `organizations`（见 `src/services/auth_service.py:281-310`、
`src/services/org_service.py:109/205/268`）。

后果：**新环境跑 `init-db` 后，注册登录直接不可用**（INSERT users 报 no such table）。
2026-10-26 的部署事故（`src/api` 只在分支、靠常驻进程续命）已经演示过一次"目录看起来有、能力不可复现"的代价；
本 change 修掉 schema 维度的同一类问题。

## What Changes

- 把生产库中 10 张表的真实 DDL 导出并规范化（`IF NOT EXISTS` 前缀、按外键依赖排序、去掉 `memberships` 的引号），
  追加进 `src/db/tables.sql`——保持"schema 唯一来源"原则，不另开 SQL 文件
- 保留生产库已有的全部约束：CHECK（角色/状态枚举）、UNIQUE（邮箱、token_hash、成员唯一性等）、外键、7 个二级索引
- **不改列名、不改语义、不加新列**——生产库在用，仓库 DDL 必须与现存结构逐列一致
- 新增守卫测试 `tests/test_db_schema.py`：
  1. `init_db` 后断言 33 张普通表全部存在（含 10 张账户/组织表）；
  2. 在全新库上走通 `register_account → viewer_from_session → login_password`（注册登录不依赖任何外部状态）
- 验证口径：删除临时库 → `uv run python -m src.cli init-db` → 33 表齐全 → 注册/登录冒烟通过

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 追加进 `tables.sql`（单一来源） | 新开 `account_schema.sql` 由 init_db 追加执行 | 两个 schema 文件必然漂移，重演本次事故 |
| 与生产库逐列一致 | 顺手"优化"列类型/约束 | 生产库在用，任何漂移都会让"仓库可重建"变成假命题；约束优化留待专门迁移 |
| 守卫测试断言表存在 + 冒烟注册 | 只加表存在断言 | 表存在但列缺失同样会让注册崩；冒烟测试钉住"全新库可注册"这个真实验收 |

## 非目标（Non-goals）

- 不改认证/组织任何 Python 代码（本 change 只动 schema 与测试）
- 不补 auth/permissions 的行为测试（属 `personal-auth-tests` change）
- 不做 schema 演进工具（Alembic 等）；`init_db` 内置 migrate 的轻量迁移维持现状
- 不回填 6 个 TBD spec 的 Purpose（另行处理）

## Capabilities

### New Capabilities

- `account-schema`：账户与会话的持久化 schema——`init_db` MUST 产出包含账户/组织全部表的可运行库，
  全新库上注册/登录 MUST 可用

## Impact

- **代码**：`src/db/tables.sql`（追加约 120 行 DDL）；`tests/`（新增 1 个守卫测试文件）
- **数据**：生产库零变化（`IF NOT EXISTS` 幂等）；全新库从 23 表变为 33 表
- **风险**：极低——纯 DDL 追加，无代码路径变化
- **证据**：init-db 重建清单（临时库 33 表 + 注册/登录冒烟输出）回填 `workspace/evidence/`
