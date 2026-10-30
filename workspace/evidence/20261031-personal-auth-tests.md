# 2026-10-31 · 个人版认证测试集验证（personal-auth-tests）

## 一、越权缺陷复现与修复

```
修复前（测试抓到）：
  用户 Mallory（已登录）GET /api/trainings/{Alice 的训练}/path → 200 ❌（应 403）
  根因：Training.to_dict() 无 owner_user_id 字段 → can_view_training 视为组织级训练放行
修复后：
  同一请求 → 403 ✅（/path 与 /sources 两个端点均钉死）
```

## 二、测试结果

```
uv run pytest tests/test_auth_personal.py -q
15 passed

uv run pytest tests/ -q
295 passed, 1 skipped, 30 subtests passed in 218.69s
```

覆盖清单：注册建号+会话 / 令牌 sha256 对照 / 非法输入拒绝 / 重复注册拒绝 /
登录成功 / 统一文案防枚举（不存在与错密码同文案）/ PBKDF2 格式 /
会话解析 / 滑动续期 last_seen_at / 吊销拒绝 / 过期拒绝 /
EMPLOYEE 动作边界 / 超集链 / 个人版 None 放行 / 训练可见性规则 / 资料 scope 规则 /
API 401 / Set-Cookie 后 200 / 401 统一文案 / 跨用户 403。

## 三、schema 对齐

生产库与仓库 DDL 全量 PRAGMA diff（33 张表）：修复后列级零漂移
（trainings.org_id/owner_user_id、sources.department_id 已入库 + migrate 兜底）。
