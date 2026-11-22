# ui-redesign · 任务清单

> 五个批次，每批独立提交（提交信息带批次号）、构建通过、手工过功能清单。
> **本 change 只登记规格，实施由后续会话执行**（用户 2026-11-23 指示）。
> 边界：只动 `web/`（含 vite.config.ts / index.html / theme.ts）；后端与判分区零接触；
> `api.ts` 只许追加类型不许改字段（share-gate/member-invite 会话在演进）。

## 批次 1 · 基建 + 骨架 + 样板页

- [ ] 1.1 依赖与接入：`tailwindcss @tailwindcss/vite class-variance-authority clsx tailwind-merge`；
      vite 插件、`styles/tailwind.css`（**禁 preflight** 的拆分 import + `@custom-variant dark`）、
      `lib/utils.ts` 的 `cn()`、main.ts 引入顺序（tailwind 在 style.css 前）
  - 验收：build 通过；旧页面视觉零变化（无 preflight 冲突）
- [ ] 1.2 token（design D2）：`@theme` zinc 灰阶 + 青绿 primary + `.dark` 覆盖块
      （数值直接搬现有深色 token）
- [ ] 1.3 `.dark` 对接：theme.ts 与 index.html 防闪脚本同步维护 `data-theme` 与 `.dark` 类
  - 验收：三态切换 + 深色下 Tailwind 类与旧 CSS 变量同时生效
- [ ] 1.4 基础组件：`ui/Button.vue`、`ui/Card.vue`、`ui/Badge.vue`（cva + cn，P0/P2 规则延续）
- [ ] 1.5 App.vue 新骨架：72px 图标 rail（hover tooltip、active 指示条、logo 回首页）+
      52px 顶栏（标题/主题钮/头像）；退役宽侧栏、collapse-btn、tabbar、shortLabel
  - 验收：五项导航可用；深色正常；关于信息以 mini 形式在 rail 底部
- [ ] 1.6 Dashboard 样板页全量 Tailwind 化（指标卡/热力图/训练行迁新 class，
      热力档位改 Tailwind 任意值或保留局部 CSS）
  - 验收：Dashboard 新视觉 + 功能零回归（数据/跳转/归档删除均可用）；
      其余页面无变化

## 批次 2 · 训练主流程

- [ ] 2.1 TodayView + TaskCard 迁移（出题/单选/作答/判分面板/四失信号/解析）
  - 验收：训练全链功能清单手过一遍（含提前练徽章、重新作答按钮）

## 批次 3 · 复杂双页

- [ ] 3.1 TrainingDetailView 五个 section 迁移（含 section-switch sticky、分享对话框、周复盘）
- [ ] 3.2 WizardView 四步向导迁移（chat 气泡、draft-box、wstep 步条）
  - 验收：创建一个新训练走完向导全流程

## 批次 4 · 收尾页 + 旧样式退役

- [ ] 4.1 Trainings / Share / Login / Me 四页迁移
- [ ] 4.2 删除 `style.css` import 与文件本体（确认无残留引用；热力等样式已迁）
  - 验收：全站 Tailwind；grep 无旧 class 引用

## 批次 5 · 组件整理（可与 4 合并）

- [ ] 5.1 组件归位 `src/components/ui/`，变体命名复核（primary/ghost/text/danger × sm/md）
- [ ] 5.2 `openspec validate` 通过；record 记录每批提交号；evidence：亮/暗双主题下
      每页截图（或用户手验清单勾选）

## 明确不做（本期）

命令面板（Cmd+K）｜移动端布局（延续桌面优先+横滚）｜后端/判分区任何改动｜
Naive UI 等整包组件库
