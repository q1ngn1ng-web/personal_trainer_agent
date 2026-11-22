# 2026-11-22 · AI 训练标题 + 仪表盘知识点覆盖 + 主题设置迁移

> 类型：feat ｜ 用户需求四项：AI 起标题（重复 -02）/ 热力图能看到知识点、题量、进度、
> 覆盖 / 主题设置进个人中心与头像菜单 / 顶栏主题按钮移除

## 变更

1. **AI 训练标题**：goal_clarification schema 顶层加 `title`（可选——服务端有
   fallback：描述前 12 字；prompt v1.3.0 要求 4-16 字体现主题与用途）；
   `wizard_start` 对同 owner 现有标题去重（`-02/-03` 递增，用户拍板口径）；
   澄清页草案框显示训练标题；load_session 返回最终标题；
   - 实现坑：首次编辑因目标串不匹配**静默 no-op**（replace 无 assert）——补 assert
     后才发现替换进了 load_session 而非 _build_session；
2. **仪表盘知识点覆盖**：`compute_training_progress` 增 `_knowledge_coverage`
   （当前路径训练项：题量 + 知识点去重、任一 passed 即覆盖）→ TrainingProgress 四个
   新字段 → /api/dashboard payload → 训练行显示「题量 / 知识点覆盖 M/N / 覆盖 chips
   （✓ 绿=已覆盖，前 8 个 + 溢出计数）」，热力卡头加全局「知识点 X/Y 已覆盖」；
3. **主题设置迁移**：theme.ts 加 `setPref`；MeView 新增「外观」卡（跟随系统/浅色/
   深色三态按钮）；头像菜单加「主题：xxx」快速切换项；顶栏 theme-toggle 移除；
4. 顺带修 style.css 悬挂 `}`（210 闭 vs 209 开，esbuild minify 警告）。

## 验证

- 线上实测（q1ng）：两次创建真实 LLM 生成「Redis 面试八股精讲」「Redis面试与Agent实战」
  （去重递增由固定 stub 单测钉死 -02/-03）；训练 50 仪表盘显示题量 19、知识点覆盖
  1/8、chips（Redis的持久化机制/写时复制技术/…）；
- 测试：goal_flow 标题生成+去重（-02/-03）+ 仪表盘知识字段端点级钉子（payload 必须携带）；
- `npm run build` 通过（css 警告清零）、服务已重启。
