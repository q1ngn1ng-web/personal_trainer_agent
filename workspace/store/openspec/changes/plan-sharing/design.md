# plan-sharing · 设计

> 对应 proposal.md。所有复制均为**纯 SQL、单事务**；判分/记忆/导入链路零改动。

## 数据模型

```sql
CREATE TABLE share_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,          -- secrets.token_urlsafe(16)
    created_by INTEGER NOT NULL,         -- 用户 id（分享人）
    created_at DATETIME NOT NULL,
    revoked_at DATETIME,                 -- 撤销后链接失效（MVP 可不暴露 UI）
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

-- trainings 追加溯源列（NULL = 原创训练）
ALTER TABLE trainings ADD COLUMN shared_from_training_id INTEGER;
ALTER TABLE trainings ADD COLUMN shared_by_user_id INTEGER;
```

## 克隆语义（`training_clone_service.clone_for_user`）

一次事务内按序复制，接收者为副本 owner：

| 复制对象 | 规则 |
| --- | --- |
| `trainings` 行 | topic 加「（来自分享）」标记；org_id = 接收者所在组织；owner_user_id = 接收者；status = `pending_confirm`（目标已带过来，重新确认一次=知行合一的起点）；写溯源列 |
| `sources` | 全部复制，scope = `personal`（接收者私有），owner 随副本；`parse_status=ok` 的原样复制 |
| `source_chunks` | 内容原样复制（新 chunk_id）；副本训练项的 `source_chunk_ids` 回指**新** chunk id |
| `question_bank` | 复制；`practiced_count = 0`、`last_practiced_at/cooldown_until = NULL`、`banked_at = now`（练习计数与冷却期**重置**） |
| `question_points` | 随题复制（判分锚不变——判分口径跨副本一致） |
| 路径骨架（`training_paths`/`path_stages`/`training_items`） | 结构复制；`item_key` 按 `hash(新 training_id, knowledge_point, title)` 重新计算（副本内自洽稳定） |
| 计划轮次 | **不复制旧轮次**：复制骨架后调用 `generate_plan`，锚定拉取/接收日 |
| `practice_attempts` / `baseline_history` / `review_archives` / `grading_cache` | **MUST NOT 复制**——进度从零（ADR-0013 进度层分离）；错因与记忆画像随作答重新积累 |

## 端点与权限

| 端点 | 方法 | 权限 | 行为 |
| --- | --- | --- | --- |
| `/api/trainings/{id}/share/link` | POST | 训练 owner（或组织管理员） | 生成/返回 share_links token（幂等：同训练同人一条） |
| `/api/share/{token}` | GET | 登录用户 | 预览：主题/目标/阶段/轮次安排/验收标准；**不含**题库、参考答案、作答数据 |
| `/api/share/{token}/pull` | POST | **同组织成员**（校验 memberships） | 克隆为独立副本；幂等：同用户同 token 返回已存在的副本 |
| `/api/trainings/{id}/share/members` | POST | 训练 owner | body: `user_ids[]`；逐个 clone_for_user（推送副本，含题库） |

* 链接 token 不含权限：拿到链接的**非组织成员**在拉取时被拒（403），预览同样拒绝。
* 拉取幂等：`trainings` 上以 `(shared_from_training_id, owner_user_id)` 判重。

## 待拍板（不阻塞规格，实施前确认）

1. 分享链接是否提供**撤销** UI（表结构已留 `revoked_at`，MVP 可只做数据层）。
2. 纯个人（无组织）用户之间的分享形态（MVP 限组织内；个人版双人组队走"邀请进组织"流程）。
3. 推送副本是否给接收者任何提示（MVP 无通知系统，副本出现在其「我的训练」列表并带来源标记）。
