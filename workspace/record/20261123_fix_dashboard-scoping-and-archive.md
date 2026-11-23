# 2026-11-23 · 仪表盘可见集口径修复（跨用户数字泄漏）+ 归档完善

> 类型：fix + feat ｜ 用户报：q2ng 仪表盘"活跃训练 6、全部训练 10"，但我的训练里没有几个
> 用户三猜：有效未展示 / 删除残留 / **全系统总数 ← 命中**（另发现热力同源泄漏）

## 诊断（用户三猜的裁定）

1. **全系统总数 ✓ 命中**：`compute_home_dashboard` 用 `list_trainings()`（全库），
   `daily_activity` 热力 SQL 也**无任何训练/归属过滤**——q2ng 的"10/6"是整个系统
   （q1ng + demo + 冒烟数据）的数字，自己的列表却是空的；
2. 删除残留 ✗：`delete_training` 是级联硬删，删了就不在计数里；
3. 有效未展示 ✗：trainings 数组本身有可见性过滤，只是**指标没跟着过滤**。

**修复**：`compute_home_dashboard(visible_ids=)` 与 `daily_activity(training_ids=)`
按可见集计算；dashboard 端点把 `_visible_training_ids` 传给两者。**坑**：空集是
falsy——B 用户看不到任何训练时 `if training_ids:` 走回未过滤分支，必须 `is not None`。

## 归档完善（用户需求：训练结束后归档，表明项目完结）

- 详情页头部：completed → 显示「归档（项目完结）」按钮（二次确认）；
  archived → 「已归档 · 项目完结」徽章 + 说明行（数据保留、随时可查看、不再进待办）；
- 归档语义（既有端点沿用）：仅 owner、仅已达标；archived 状态对 owner 仍可见
  （列表"已归档"徽章），不出现在今日待办（due 过滤天然不命中）。

## 验证

- `test_session_plan` 新增两条端点级钉子：
  A 建 2 训练 → A 的 total_all=2/total_active=2；**B 无训练 → 0/0**（修复前是全系统数）；
  A 的作答只进 A 的热力（B 的热力 sum=0）；completed → 归档 → 状态 archived 且对
  owner 可见；
- 全量回归见 CI 记录；`npm run build` 通过、服务已重启。
