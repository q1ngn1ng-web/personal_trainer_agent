# 2026-10-31 · 账户/组织 10 张表 DDL 入库（account-schema-in-repo）

> 类型：fix ｜ 对应 change：`account-schema-in-repo` ｜ 关联审计：成熟度审计 P0-1 后续发现的 schema 缺口

## 变更摘要

仓库 schema 唯一来源 `src/db/tables.sql` 缺 10 张账户/组织表的 DDL
（users / sessions / login_tokens / organizations / departments / memberships /
roster_entries / assignments / assignment_targets / assignment_receipts），
导致全新环境 `init-db` 后注册登录直接不可用（INSERT users 报 no such table）。

- 从生产库 `sqlite_master` 导出 10 张表与 7 个二级索引的真实 DDL；
- 规范化（`IF NOT EXISTS`、按外键依赖排序、去引号）后追加进 `src/db/tables.sql`；
- 列定义与生产库逐列一致（CHECK 枚举、UNIQUE、外键全保留），不改任何列；
- 新增守卫测试 `tests/test_db_schema.py`：33 表全集断言 + 全新库注册→会话→登录冒烟。

## 影响范围

- `src/db/tables.sql`：追加约 150 行 DDL（幂等，生产库零变化）
- `tests/test_db_schema.py`：新增（2 用例）
- 无任何 Python 代码改动

## 验证

- 全新临时库 `init_db` → 33 表齐全（证据：`workspace/evidence/20261031-init-db-schema-rebuild.md`）
- 全量测试 `270 passed, 1 skipped, 30 subtests`（修复前基线 261 passed, 1 skipped）

## 遗留

- auth/permissions 行为级测试集属 `personal-auth-tests` change（个人版范围，org/assignment 不测）；
- 6 个 spec 的 Purpose 仍为 TBD，另行回填。
