# 2026-10-31 · 个人版认证与会话最小测试集（personal-auth-tests）

> 类型：fix ｜ 对应 change：`personal-auth-tests` ｜ 关联：auth/permissions 零测试（审计缺口）

## 变更摘要

按用户决策（2026-10-29：企业版不作为产品主线）补个人版路径的最小测试集，
并修复测试过程中发现的两个真实缺陷：

1. **跨用户越权（安全缺陷）**：`Training` RowModel 缺 `owner_user_id` 字段，
   `to_dict()` 丢字段 → `can_view_training` 把全部训练当「组织级训练」放行，
   任何登录用户可读任何训练的路径与资料。修复：模型补 `org_id`/`owner_user_id`、
   `Source` 补 `department_id`；HTTP 层跨用户用例钉死 403。
2. **schema 二次漂移**：`trainings.org_id/owner_user_id`、`sources.department_id`
   生产库有、仓库 `tables.sql` 无——新库向导第一步即崩。
   修复：DDL 补 3 列 + `migrate._ACCOUNT_COLUMNS` 老库自动补列。

测试覆盖（15 用例 / 4 类）：注册登录（令牌只存 sha256、统一文案防枚举、PBKDF2 格式）、
会话生命周期（滑动续期/吊销/过期/登出）、权限矩阵（三角色超集链、个人版 None 放行、
四种资料 scope）、API 契约（401/Set-Cookie/401 统一文案/跨用户 403；LLM 断网化离线确定性）。

## 影响范围

- `tests/test_auth_personal.py` 新增；`src/db/models.py` 3 个字段；`src/db/tables.sql` 3 列；`src/db/migrate.py` 补列机制
- 行为变化：跨用户隔离从「静默失效」恢复为设计意图（403）——个人版多账号场景的安全性修正

## 验证

- `uv run pytest tests/test_auth_personal.py -q` → 15 passed
- 全量回归 → **295 passed, 1 skipped, 30 subtests**（本日基线 261 → 295）
- 生产库 migrate 幂等（`IF NOT EXISTS` + 补列判重）

## 遗留

- org/assignment/一次性登录码（企业版）行为测试：用户决策后置
- 密码复杂度与 secure cookie 默认值：单机 MVP 维持现状，面试作为 trade-off 主动讲
