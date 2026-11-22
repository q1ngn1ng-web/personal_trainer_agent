# 2026-11-22 · 向导进度可恢复 + 未生成完训练的可操作提示

> 类型：fix ｜ 用户报：①仪表盘点进训练，完整计划一片空白；②创建训练中刷新后回不到进度，
> "直接不能再继续回到生成训练的那个页面"

## 根因

1. **向导无恢复**：WizardView 的 session/step 全是页面内存态，刷新即丢；后端本有
   `load_session`（clarifyState，"页面刷新后继续澄清"）但前端从不调用——用户只能
   重新开始，而 `start_session` 每次都新建训练 → 孤儿草稿 + "回不去"；
2. **空白真实形态**：用户点进的训练 136 是确认了目标但**从未跑完向导**的存量
   （confirmed、无路径、无计划项）——详情页各 tab 空态文案不能告诉用户"去哪继续"。

## 修复

- **进度持久化**：tid+step 存 localStorage（start→1 / confirm→2 / gotoProbe→3 /
  activate→清除）；WizardView onMounted 恢复：
  draft/pending_confirm → clarifyState 恢复第 1 步会话（节奏/字段编辑全在）；
  confirmed → 恢复到资料来源步（探测可重新生成）；已激活 → 清除标记；
  恢复态显示「放弃这个草稿，重新开始」入口；
- **详情页空计划状态感知**：`status=confirmed && planRounds 空` → 显示
  "目标已确认，但训练还没生成完——回到新建训练继续" + 「继续完成创建」按钮
  （向导会自动恢复该草稿）；其余空态文案保持。

## 验证

- 线上实测：start → pace(2×3) → draft 编辑 → 模拟刷新（clarifyState）→
  pace/level/can_confirm 全部恢复；confirm 后再次刷新 → 确认态恢复 + sources 可用；
- `npm run build` 通过，服务已重启。
