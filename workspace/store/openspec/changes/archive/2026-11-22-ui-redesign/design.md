# ui-redesign · 设计

## D1 · Tailwind v4 接入与共存（关键工程约束）

```bash
npm install tailwindcss @tailwindcss/vite class-variance-authority clsx tailwind-merge
```

- `vite.config.ts`：`plugins: [vue(), tailwindcss()]`（`@tailwindcss/vite`）。
- 新建 `web/src/styles/tailwind.css`，**禁 preflight** 与现有 `style.css` 共存：

```css
@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);
@custom-variant dark (&:where(.dark, .dark *));
/* 不 import preflight——旧页面过渡期依赖 style.css 自己的 reset */
```

- `main.ts` 在 `style.css` 之前 import `tailwind.css`；过渡期两套并存，
  视图逐批迁走，最后一批删除 `style.css` import。
- 工具函数 `web/src/lib/utils.ts`：`cn(...inputs)` = `twMerge(clsx(inputs))`
  （shadcn 模式标配，组件源码里大量使用）。

## D2 · 设计 token（zinc 灰阶 + 青绿 primary）

`tailwind.css` 内用 v4 `@theme` 定义（同时供 `bg-primary` 等 utility 生成）：

| Token | 亮色 | 暗色 | 用途 |
| --- | --- | --- | --- |
| `--color-primary` | `#0e7c6b`（现品牌青绿） | `#17b597`（提亮档） | 主按钮/链接/选中态——**唯一大面积彩色的来源** |
| `--color-bg / surface / surface-2` | `#fafafa / #ffffff / #f4f4f5` | `#0e1014 / #15171c / #1b1e24` | zinc 系中性底 |
| `--color-line` | `#e4e4e7` | `#272b33` | 1px 边框（平面卡片无阴影原则延续） |
| `--color-text / muted / faint` | `#18181b / #71717a / #a1a1aa` | `#e8eaee / #a0a7b3 / #737b88` | zinc 文字阶 |
| 状态色 ok/warn/danger | 沿用现值体系 | 沿用现深色值 | 只承载语义，不做装饰 |

暗色值放在 `.dark { ... }` 块内覆盖（与现有深色 token 数值一致，直接搬）。
字号/间距沿用 P0 阶梯语义（`--text-*` 映射 12/13/14.5/17/20/28）。

## D3 · `.dark` 类与现有三态主题对接

`theme.ts` 的 `applyPref` 与 `index.html` 防闪脚本：设置 `data-theme` 的**同时**
对 `document.documentElement.classList.toggle("dark", resolved === "dark")`。
Tailwind `dark:` 变体、现有 CSS 变量两套体系同时生效，行为零变化。

## D4 · 新布局：72px 图标 rail

```
┌──┬──────────────────────────────┐
│▣ │ 页面标题          ◐ ○(头像) │ ← 顶栏 52px：标题 + 主题钮 + 头像
│◎ ├──────────────────────────────┤
│✚ │                              │
│▦ │   内容区 max-w-1080 居中      │
│◈ │                              │
│◍ │                              │
│… │                              │
└──┴──────────────────────────────┘
```

- rail：`w-[72px] border-r`，5 项导航（今日 CircleDot / 新建 Plus / 仪表盘
  LayoutDashboard / 训练 GraduationCap / 我的 CircleUser）；
  图标 20px 居中，`hover` 出 tooltip（纯 CSS `group-hover` 实现，标签在图标右侧
  浮层），active 项：图标主色 + **左缘 2px 青绿指示条**；
- 顶部 logo 区（32px 品牌方块「练」）点击回首页；
- 底部放主题三态与关于 mini（原侧栏关于区块压缩为一行 tooltip）；
- 顶栏 52px：左=当前页标题（15px 600），右=主题循环钮 + 头像菜单（沿用）。
- **移动端 tabbar 退役**（早已桌面优先）；`collapse-btn`/`shortLabel` 随宽侧栏退役。

## D5 · 迁移批次（每批独立提交、独立可回退）

| 批次 | 内容 | 验收 |
| --- | --- | --- |
| 1 | D1-D4 基建 + App.vue 新骨架 + **Dashboard 样板页全量 Tailwind 化** | rail 布局上线；Dashboard 新视觉；其余页旧样式无回归 |
| 2 | TodayView + TaskCard（训练主流程） | 出题/作答/判分/信号全链新视觉，功能零回归 |
| 3 | TrainingDetailView + WizardView（最复杂两页） | 五个 section + 向导全链新视觉 |
| 4 | Trainings / Share / Login / Me + 删除 style.css | 全站 Tailwind；旧 CSS 退役 |
| 5（收尾） | 组件沉淀整理（Button/Card/Badge 等 cva 组件归位 `src/components/ui/`） | 组件源码目录结构清晰 |

每批完成：`npm run build` + 手工过该批页面的功能清单 + 提交信息带批次号。

## D6 · shadcn 组件策略（拷源码，不装黑盒）

首批只需要 4 个基础件，全部手写进 `web/src/components/ui/`（cva 变体 + cn 合并）：
- `Button.vue`（primary/ghost/text/danger × sm/md，按压 feedback 延续 P2）；
- `Card.vue`（1px 边框无阴影，padding 档 sm/md）；
- `Badge.vue`（P0 降噪规则延续：默认灰、彩仅语义）；
- 后续批次按需加 `Input/Dialog/Tooltip`（Tooltip 优先纯 CSS，交互复杂再引 reka-ui）。

## D7 · 与并行会话的边界

- 本 change 只动 `web/`（+vite.config/index.html/theme.ts）；后端与判分区零接触；
- `api.ts` 只允许**追加**类型（如需），禁止改既有字段——share-gate/member-invite
  会话仍在演进这些端点。
