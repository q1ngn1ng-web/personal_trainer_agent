# personal-auth-tests · 设计

## D1 测试分层的取舍

四层各测各的缝隙：服务层测「业务规则」（哈希格式、统一文案、续期）；纯函数层测「矩阵」；
HTTP 层测「集成缝隙」——本次越权缺陷（模型字段缺失）只有 HTTP 层能暴露，
这也是「只测纯函数不够」的直接证据。

## D2 断网化

`TestClient` 请求会触发向导澄清的 LLM 调用。测试 patch `client._call_api` 抛 LLMError
（goal_clarification 有静态 fallback，链路照常走通），并把 DEEPSEEK_API_KEY 置为测试值——
生产 .env 有真实 key，测试 MUST NOT 依赖环境。

## D3 越权缺陷的根因与修法

根因：schema 列（owner_user_id）与 ORM 模型（Training dataclass）脱节，
`to_dict()` 丢字段 → 权限判定拿到的是「无主训练」→ 按组织级放行。
修法是补模型字段（声明式，from_row 自动带出），而不是在权限函数里绕过 to_dict——
后者会留下第二处「字段必须记得手动带」的坑。

## D4 回滚

revert 提交即可；新增列/字段为纯增量，无行为依赖之外的耦合。
