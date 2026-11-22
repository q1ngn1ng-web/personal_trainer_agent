# ui-redesign Specification

## ADDED Requirements

### Requirement: 设计基调为黑白灰 + 青绿点缀

重构后的界面 SHALL 以 zinc 系中性灰阶为大面积底色（背景/表面/边框/文字），
青绿（现有品牌色）SHALL 仅出现在主操作按钮、链接、选中态与指示条等品牌点位；
状态色（绿/橙/红）SHALL 仅承载通过/警告/错误语义。任何页面 MUST NOT 出现
青绿与状态色之外的彩色装饰。

#### Scenario: 主页打开的配色

- **WHEN** 用户打开任一页面
- **THEN** 大面积呈中性灰阶，唯一的显性彩色是青绿主按钮/当前项指示
- **THEN** 眯眼测试下最先跳出来的是主操作或关键数字

### Requirement: 图标 rail 布局

应用 SHALL 采用 72px 图标 rail 导航（纯图标 + hover tooltip 标签 + active
左缘青绿指示条）+ 52px 精简顶栏（页面标题 + 主题切换 + 头像）+ 内容区
max-width 1080px 居中。宽侧栏、折叠按钮与移动端 tabbar SHALL 退役。

#### Scenario: 导航交互

- **WHEN** 用户悬停 rail 图标
- **THEN** 图标右侧浮现标签 tooltip
- **WHEN** 用户点击导航项
- **THEN** 该项图标转青绿且左缘出现 2px 指示条，内容区切换

### Requirement: 暗色三态行为保持

重构 MUST 保持现有主题三态（跟随系统/浅色/深色）行为不变：Tailwind `dark:`
变体经 `.dark` 类生效，`theme.ts` 与防闪脚本同时维护 `data-theme` 与 `.dark`，
localStorage 键与切换交互（顶栏循环钮）不变。

#### Scenario: 深色下全站一致

- **WHEN** 用户切换到深色
- **THEN** rail/顶栏/卡片/控件（含滚动条）全部转入深色，无旧样式白块残留

### Requirement: 新旧共存过渡不破坏旧页

迁移期间 Tailwind MUST 禁用 preflight，与现有 style.css 共存；未迁移页面
MUST 保持当前视觉与功能无回归。每批迁移 MUST 独立提交且构建通过。

#### Scenario: 批次 1 上线当日

- **WHEN** 仅 Dashboard 迁移完成（批次 1）
- **THEN** 其余页面（今日/详情/向导等）视觉与交互和迁移前一致

### Requirement: 组件源码进仓库

界面 MUST 基于 `web/src/components/ui/` 内的本地组件（cva 变体 + cn 合并，
shadcn 拷源码模式）构建；MUST NOT 引入整包 UI 依赖（黑盒组件库）。

#### Scenario: 按钮变体

- **WHEN** 页面使用 Button 组件
- **THEN** 其变体（primary/ghost/text/danger × 尺寸）由本地 cva 定义，
  可直接修改源码调整
