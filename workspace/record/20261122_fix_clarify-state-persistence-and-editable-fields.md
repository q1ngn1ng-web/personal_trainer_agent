# 2026-11-22 · 澄清草案状态保持 + 字段可编辑（用户报"没改的内容也在变"）

> 类型：fix + feat ｜ 用户原话：「我第一次是2周3次，没动这里，我发送回答之后，这里又重置成了3周4次」
> 「目标等级应该可编辑……验收标准 AI 第一次生成的，不满意可以再次修改」「把整个这里都弄个对话」

## 根因（状态保持缺失，真 bug）

`continue_session` 重建草案时只锁 `content`——用户设过的**节奏/等级/验收标准**每轮
被 LLM 新草案冲掉（违反 ADR-0004「用户显式值 > LLM 输出」的铁律，且这正是
`_user_locked_fields` 该干的事）。节奏丢掉后前端 `syncPaceControls` 把推荐值
（3 周 × 4 次）当默认写回去——用户看到的就是"没动却变了"。

**修复**：`_user_locked_fields(state)`——user_input/user_reply 来源的字段
（content/level/acceptance/horizon_days/session_count）在 continue_session 全程
locked；inferred 来源仍留给 LLM 迭代（不把 AI 的手绑死，测试分三条钉死）。

## 新增：草案字段可编辑（POST /api/wizard/{id}/draft）

- `update_draft_fields(training_id, values)`：content（≥4 字）/level（四档枚举）/
  acceptance（validate_acceptance，自由文本或结构化都收）——校验通过以 user_input
  落快照、重算 missing_fields/can_confirm；非法整批 400；
- WizardView 草案区改为**可编辑表单**：学习内容 input、目标等级 select（与节奏
  卡片同款交互）、验收标准 textarea（AI 先生成一版 `formatAcceptance` 格式化展示，
  不满意直接改）+ 保存按钮（只提交有改动的字段）；
- 顺带修 `_build_session` 的 user_reply 覆盖：来源已是 user_input 的字段不再被
  对话补充降级为 user_reply（卡片编辑与对话补充互不覆盖）。

## 排查记录（测试侧三个坑，与产品无关）

stub 的 LLM 输出两次被 goal_clarification schema 拒绝（acceptance 缺 statement、
顶层缺 field_sources——**schema 要求 field_sources 在顶层**）→ 走 fallback 空草案
造成假失败；测试文件漏 import json。均为测试基建问题。

## 验证

- `test_goal_flow.py` 12 passed（新增 4 条：节奏跨轮保持、编辑字段拒绝 LLM 覆盖、
  推断字段仍由 AI 迭代、update_draft_fields 校验）；
- 线上实测（q1ng）：设 2 周 × 3 次 → 发回答 → **仍是 2×3**（修复前重置为 3×4）；
  编辑 level=熟练 + 验收 → missing 清空、can_confirm=True；再回答 → 全部保持；
- `npm run build` 通过，服务已重启。
