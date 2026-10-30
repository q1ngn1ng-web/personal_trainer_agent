# account-schema-in-repo · 设计

## D1 为什么追加进 tables.sql 而不是独立文件

`src/db/sqlite.py:33-37` 的 `init_db` 只执行一个 schema 文件。引入第二个文件意味着：
两个文件的执行顺序、重复表、漂移检测都要新造机制——为修"schema 与仓库不一致"再引入一个新的不一致源，方向反了。

## D2 DDL 从哪来

生产库 `data/trainer.db` 是唯一"确认能跑"的 schema（62 篇 record 里多次个人账户/组织上线的真实结构）。
逐表 `SELECT sql FROM sqlite_master` 导出后做三类规范化，**列定义零改动**：

1. `CREATE TABLE` → `CREATE TABLE IF NOT EXISTS`；`CREATE INDEX` → `CREATE INDEX IF NOT EXISTS`；
2. 按外键依赖排序：`organizations → users → departments → memberships → sessions → login_tokens → roster_entries → assignments → assignment_targets → assignment_receipts`；
3. `"memberships"` 的引号去掉（非保留字，与全文件风格统一）。

## D3 守卫测试怎么写

`tests/test_db_schema.py`，unittest 风格与既有测试一致，`setUp` 里把 `DB_PATH` 指到 `tempfile.TemporaryDirectory`
（沿用 17 个既有测试的环境变量隔离惯例），`tearDown` 恢复原值：

- `test_init_db_creates_all_tables`：`init_db` 后查 `sqlite_master`，断言 33 张表名全集（含 10 张账户/组织表）；
- `test_fresh_db_supports_register_and_login`：全新库直接调
  `auth_service.register_account` → 断言 viewer/session；
  `auth_service.viewer_from_session(token)` → 断言同一 user_id；
  `auth_service.login_password` → 断言成功；错误密码 → 断言 PermissionError。
  该测试同时是"注册登录不依赖外部状态"的最小行为证明（行为级测试集另属 `personal-auth-tests`）。

## D4 风险与回滚

- 生产库执行 `init_db`（服务启动时自动）会因为 `IF NOT EXISTS` 全部跳过，零影响；
- 若 DDL 与某处代码预期不一致，冒烟测试会在合并前暴露；回滚 = revert tables.sql 追加段。
