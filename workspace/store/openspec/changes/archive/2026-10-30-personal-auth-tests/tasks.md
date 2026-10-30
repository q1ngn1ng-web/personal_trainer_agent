# personal-auth-tests · 任务清单

- [x] 1.1 服务级注册/登录测试（含令牌只存哈希、统一文案防枚举、PBKDF2 格式、重复注册拒绝）
- [x] 1.2 会话生命周期测试（解析、滑动续期、吊销、过期、登出）
- [x] 1.3 权限纯函数矩阵测试（三角色超集链、viewer=None 放行、训练/资料可见性规则）
- [x] 1.4 API 访问控制测试（401/Set-Cookie/统一文案 401/跨用户 403；LLM 断网化）
- [x] 1.5 修复越权缺陷：Training 补 org_id/owner_user_id、Source 补 department_id（模型字段）
- [x] 1.6 修复 schema 二次漂移：tables.sql 补 3 列 + migrate `_ACCOUNT_COLUMNS` 机制
- [x] 1.7 全量回归 + 收尾（record/evidence/archive）
