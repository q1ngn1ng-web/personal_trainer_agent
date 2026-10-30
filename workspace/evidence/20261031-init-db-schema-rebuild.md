# 2026-10-31 · 全新库 schema 重建验证（account-schema-in-repo）

> 对应 change：`account-schema-in-repo`（10 张账户/组织表 DDL 入库）
> 验证方式：临时目录全新 `init_db` + 注册/登录冒烟 + 守卫测试

## 一、全新库重建

```
DB_PATH=<tmpdir>/fresh.db → init_db()
fresh init-db: 33 tables
account/org tables present: OK
```

33 张普通表全集（不含 FTS5 虚表与 sqlite_sequence）与生产库一致，
其中本次入库的 10 张：users / sessions / login_tokens / organizations / departments /
memberships / roster_entries / assignments / assignment_targets / assignment_receipts。

## 二、全新库注册→会话→登录冒烟（守卫测试 tests/test_db_schema.py）

- `register_account("fresh@example.com", ...)` → 返回 viewer（新 user id）+ session（明文 token 只返回一次）
- `viewer_from_session(token)` → 解出同一 user_id
- `login_password`（正确密码）→ 成功；（错误密码）→ PermissionError
- 结果：`uv run pytest tests/test_db_schema.py -q` → **2 passed**

## 三、全量回归

```
uv run pytest tests/ -q
270 passed, 1 skipped, 30 subtests passed in 197.91s
```

（修复前基线 2026-10-26：261 passed, 1 skipped；新增 2 个 schema 守卫用例及其余差异来自既有提交。）

## 四、幂等性说明

生产库执行 `init_db` 时新增 DDL 全部为 `CREATE TABLE/INDEX IF NOT EXISTS`，已存在的表全部跳过，零结构变化。
