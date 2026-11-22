# 2026-11-23 · 前端完全重构 ui-redesign（shadcn-vue + Tailwind v4，五批次）

> 类型：feat（纯前端）｜ 对应 change：`ui-redesign`（tasks 全勾，站外邀请等后置项不变）
> 用户三项拍板：方案 A shadcn-vue + Tailwind / 布局重做（图标 rail）/ 黑白灰 + 青绿点缀
> 提交：`322dcdc` 批次1 → `9b45603` 批次2 → `5f76190` 批次3+4 → 本 record + 归档（批次5）

## 实施

- **批次 1（322dcdc）**：Tailwind v4 接入（**禁 preflight** 与 style.css 共存，utilities 进
  layer(utilities)）+ `@theme` token（zinc 灰阶 + 青绿 primary，.dark 覆盖块搬现有深色值）+
  `.dark` 类与 data-theme 双轨同步（theme.ts + 防闪脚本，三态零变化）+ ui 三基础件
  （Button/Card/Badge，cva+cn 拷源码）+ **72px 图标 rail 新骨架**（hover tooltip、active
  左缘 2px 青绿指示条、logo 回首页、rail 底部主题/关于 mini）+ 52px 顶栏 + 1080px 内容区
  + Dashboard 样板页全量 Tailwind 化。宽侧栏/collapse/tabbar/shortLabel 退役。
- **批次 2（9b45603）**：TodayView + TaskCard 全量迁移（指标卡/组卡/逾期聚合条/紧凑行/
  出题/单选/填空/要点编辑/判分面板/coach_hint/深度解析/四失信号），script 零改动。
- **批次 3+4（5f76190，合并提交）**：**兼容层策略**——tailwind.css @layer components 用
  新 token 重实现全部旧语义类（card/badge 五色/btn 五变体/input/textarea/list-item/
  progress/stat/question-box/error-tip/section-switch/stage/chat/draft-box/wizard-steps/
  login 三类/ico-svg 等 40+ 类），未迁移视图即刻获得新设计语言，迁移面收敛到结构层；
  style.css 本体退役（-466 行）；base 块接管 body 字体栈/底色（顺带修了 logo「练」字
  因字体栈缺失不显示的问题）。
- **批次 5**：ui 组件已在 `src/components/ui/` 归位；validate 通过；record + 亮/暗截图
  evidence 在 /tmp/ui-shots/（dashboard/detail-dark/wizard-dark/login）。

## 关键工程决策（与 design 的偏差已申报）

- **批次 3/4 合一**：D5 预期两批独立提交；实际采用**兼容层策略**后，两批的实现收敛为
  一次内聚 diff（compat 层 + style.css 删除），拆开反而不可回退——合并提交并在本文申报；
- 兼容层让「迁移」的重心从"逐类改写"变成"语义类名经新 token 重实现"——旧类名保留，
  新语言即刻全站生效，回归风险大幅下降（playwright 探针 + 全页截图验证）。

## 验证

- `npm run build` 每批通过（css 警告 0）；playwright 全页截图：dashboard（新视觉）、
  detail 亮/暗、wizard 亮/暗、login、trainings、today——深色全站无白块、rail/指示条/
  tooltip 正常、console 零报错；行级 3x 放大探针证实旧"- 占位符"已不存在；
- 判分区零接触；`api.ts` 本 change 未改动；后端零改动（服务重启仅为静态文件生效）。
