# personal-auth-tests · 个人版认证与会话最小测试集

## Why

`auth_service` 模块 docstring 声称「三条硬约束（都有单测）」，但 `tests/` 此前对
auth/permissions **零覆盖**——安全模块的行为没有任何回归保护。

范围按用户决策（2026-10-29）：**企业版不作为产品主线，本 change 只覆盖个人版路径**——
注册/登录/会话生命周期/权限纯函数矩阵/API 访问控制（401/403）。
组织与作业（org/assignment）不在范围。

**测试立刻抓到并修复了两个真实缺陷**（写测试的价值证明）：

1. **跨用户越权（安全缺陷）**：`Training` RowModel 缺 `owner_user_id` 字段，
   `to_dict()` 里永远没有它 → `can_view_training` 把所有训练当「组织级训练」（owner 为空→放行），
   **任何登录用户可以读任何训练的路径与资料**。修复：模型补 `org_id`/`owner_user_id`
   （`Source` 补 `department_id`），越权用例钉死 403。
2. **schema 二次漂移**：`trainings.org_id/owner_user_id`、`sources.department_id` 在生产库存在
   （个人账户功能引入）但仓库 `tables.sql` 缺失——新库上向导第一步
   `UPDATE trainings SET owner_user_id` 直接崩溃。修复：DDL 补列 + migrate 补列机制（`_ACCOUNT_COLUMNS`）。

## What Changes

- 新增 `tests/test_auth_personal.py`（15 用例，四个测试类）：
  - `TestRegisterAndLogin`：注册建号+会话、令牌只存 sha256（对照预期哈希）、非法输入 400 语义（ValueError）、
    重复注册拒绝、登录成功、**统一文案防用户枚举**（不存在/错密码同为「邮箱或密码不正确」）、PBKDF2 格式
  - `TestSessionLifecycle`：会话解析、**滑动续期写 last_seen_at**、吊销后拒绝、过期后拒绝、登出语义
  - `TestPermissionsMatrix`：EMPLOYEE 仅自用动作、三角色超集链、**viewer=None 直接放行（个人版语义）**、
    can_view_training 的 org/owner 规则、can_view_source 的四种 scope
  - `TestApiAccessControl`：未登录 401、注册 Set-Cookie 后 /api/me 200、错误登录 401+统一文案、
    **跨用户隔离**（B 读 A 的训练 → 403）、LLM 断网化（patch `_call_api`）保证离线确定性
- 修复 1：`src/db/models.py` `Training` 补 `org_id`/`owner_user_id`、`Source` 补 `department_id`
- 修复 2：`src/db/tables.sql` 补 3 列；`src/db/migrate.py` 新增 `_ACCOUNT_COLUMNS` 补列机制（老库自动对齐）

### 关键取舍

| 选择 | 备选方案 | 放弃理由 |
|---|---|---|
| 只测个人版路径 | 连 org/assignment 一起测 | 用户决策：企业版非产品主线；测试成本花在主线上 |
| API 测试 patch `_call_api` 断网 | 依赖无 key 环境 | 环境无关（生产 .env 有真实 key，测试不能真调） |
| 越权用例走 HTTP 层 | 只测 can_view_training 纯函数 | 纯函数测不出「模型字段缺失」这类集成缝隙——本次缺陷恰是缝隙型 |

## 非目标（Non-goals）

- org/assignment/一次性登录码（企业版）行为测试
- 前端测试
- 密码复杂度策略与 secure cookie 默认值（已知取舍，单机 MVP 维持现状）

## Capabilities

### Modified Capabilities

- `account-schema`：补「模型层必须暴露归属字段」的要求（越权缺陷的根因是 schema 列与 ORM 模型脱节）

## Impact

- **代码**：`tests/test_auth_personal.py`（新增）；`src/db/models.py`（3 个字段）；`src/db/tables.sql`（3 列）；`src/db/migrate.py`（补列机制）
- **风险**：低——模型补字段是纯增量；migrate 幂等；越权修复让行为回归设计意图
- **证据**：测试输出；全量回归
