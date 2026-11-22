# ui-redesign · 前端完全重构——shadcn-vue + Tailwind 体系（黑白灰 + 青绿）

> **状态：已拍板待实施（用户三项决策 2026-11-23，见下）。本文档只做规格，不含实现；
> 实施由后续会话按 tasks 分批执行。**
> 前置：P0-P3 美化批次已全部落地（`c304748`/`c724c8b`/`29fcd8e`/`b30452b`/`db8e770`），
> 本 change 是在其之上**换设计底子**，不是修补。

## Why

P0-P3 把现有手写体系执行到了天花板（token 阶梯、Lucide 图标、微交互、暗色三态），
但**设计语言本身仍是自研**——排版密度、控件细节、交互质感的天花板受限于手艺。
用户评价"还是太丑"，要求能**完全重构**的那种提升。

业界"高级感"的来源是成熟的组件体系：Radix/shadcn 系（Linear/Vercel 同款质感）
把 focus 环、下拉动画、表格密度、暗色过渡这类"临摹不动"的细节全部做到位。
用户拍板引入该体系做全量重写。

## What Changes

* **技术底座**：Tailwind CSS v4（`@tailwindcss/vite` 插件）+ shadcn-vue 模式
  （`class-variance-authority` + `clsx` + `tailwind-merge`；组件**源码拷贝进仓库**，
  非黑盒依赖；无头交互需要时引 reka-ui）。
* **设计基调**：**黑白灰为主 + 青绿只做品牌点缀**（Linear/Vercel 式中性底，
  `--primary` 用现有青绿 `#0e7c6b` 系；其余大面积 zinc 灰阶）。
* **布局重设计**（用户拍板"布局也重做"）：
  - 左侧 **72px 图标 rail**（5 项导航纯图标，hover tooltip 显示标签，
    active 项左缘青绿指示条）取代现有 232px 宽侧栏；
  - 顶栏精简：页面标题 + 主题三态切换 + 头像菜单；
  - 内容区 max-width 1080px 居中；现有 collapse 按钮随宽侧栏一并退役。
* **暗色无缝对接**：Tailwind `dark:` 变体走 `.dark` 类；`theme.ts` 在写
  `<html data-theme>` 的同时切换 `.dark` 类（含 index.html 防闪脚本同步改），
  三态切换行为不变。
* **分批迁移**（新旧共存过渡）：Tailwind **禁用 preflight** 与现有
  `style.css` 共存；每批迁移若干视图到 Tailwind class，全部迁完后退役
  `style.css`（保留热力图等共用样式至其迁移）。

### 用户拍板（2026-11-23）

| 决策点 | 结论 |
| --- | --- |
| 重构方案 | **A：shadcn-vue + Tailwind**（备选 Naive UI / 纯手写重做，弃） |
| 布局骨架 | **布局也重设计**（图标 rail 等，非保留现骨架） |
| 设计基调 | **黑白灰 + 青绿点缀**（非青绿主色不变） |

## 非目标（后置，不进本期）

* 命令面板（Cmd+K 导航/搜索）——等 rail 布局稳定后单独立项；
* 移动端布局（延续"桌面优先，过窄横滚"的既有决策）；
* 后端任何改动（纯前端 change；`api.ts` 仅允许类型补充）；
* 判分区文件（并行会话负责区域，零接触）。

## Impact

* 新增依赖：`tailwindcss`、`@tailwindcss/vite`、`class-variance-authority`、
  `clsx`、`tailwind-merge`（需要时 `reka-ui`）；
* `web/src/` 全部视图与组件分批重写；`style.css` 最终退役；
* `vite.config.ts`、`index.html`（防闪脚本）、`theme.ts` 小改；
* 视觉验收依赖用户浏览器确认（本会话无浏览器自动化工具）。
