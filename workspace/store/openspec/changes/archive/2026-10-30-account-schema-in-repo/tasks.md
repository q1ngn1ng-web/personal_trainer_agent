# account-schema-in-repo · 任务清单

- [ ] 1.1 从生产库导出 10 张表的 `CREATE TABLE` 与二级索引原文，确认与代码中的裸 SQL 列名逐一对应
  - 验收：导出清单落盘本 change `design.md` 附录；`auth_service` / `org_service` / `assignment_service` 引用的每一列都能在 DDL 中找到
- [ ] 1.2 规范化 DDL（`IF NOT EXISTS`、按外键依赖排序、去引号）并追加进 `src/db/tables.sql`
  - 验收：与生产库 `sqlite_master.sql` 逐列 diff 为空（除 `IF NOT EXISTS` 与引号差异）
- [ ] 1.3 全新库重建验证：临时路径 `init-db` → 33 张普通表齐全 → 直接调用 `register_account` / `login_password` 冒烟
  - 验收：注册返回 viewer 与 session；登录通过；`viewer_from_session` 解出身份
- [ ] 1.4 守卫测试 `tests/test_db_schema.py`：`init_db` 后断言 33 张表存在；全新库上注册→会话→登录链路可用
  - 验收：`uv run pytest tests/test_db_schema.py -q` 通过；测试用独立 `DB_PATH`，不触碰生产库
- [ ] 1.5 全量回归 + 收尾：`uv run pytest tests/ -q` 全绿；证据回填 `workspace/evidence/`；`workspace/record/` 变更记录；归档 change
  - 验收：`openspec archive account-schema-in-repo --store store` 成功，spec `account-schema` 生成且 Purpose 非 TBD
