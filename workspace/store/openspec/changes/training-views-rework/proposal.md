# training-views-rework · 训练视图重构：资料就绪门控 + 训练路径/完整计划对调

> **状态：已实施**（commit `4ff6092` + `8f377fa`，2026-11-23）。
> 用户反馈原话（2026-11-23）：「没有可用的资料切片，无法出题。是不是因为这里资料没有
> 上传完毕？……需要在资料来源弄一个可视化进度，显示资料到哪一步了」「点完整计划之后
> 显示为空，完整计划里应该放的是现在训练路径的内容，这里你放反了。而训练路径这里，
> 放的应该是所有训练的内容，比如第一次训练，下面包含题目和分类、题目掌握度等等……
> 可以显示每次训练的聚合分数」。

## Why

1. **资料状态不可见 + 探测硬依赖无门控**：出题/探测强依赖「启用 且 parse_status=ok
   且有切片」的来源，但前端把 `parse_status` 英文原样透传，无切片数、无失败原因、
   无进度；用户在无就绪资料时点「开始探测出题」只得到一句 400 报错，无从排查。
2. **训练路径/完整计划内容放反**（用户拍板）：完整计划应是阶段与知识点全貌
   （原「训练路径」tab 的内容）；训练路径应是**按训练场次组织**的全部训练——
   第 N 次训练下含题目/分类/掌握度，并显示由该场各题得分算出的**聚合分数**；
   每次训练贯穿各阶段知识点。
3. **四类接线缺口**（ui-redesign 迁移与历史遗留）：
   - plan section 模板引用未定义 `questionList` → 渲染抛 TypeError → **点完整计划整页空白**；
   - path 端点阶段条目缺 `item_key` → 「去练习」定位静默落空；
   - `openPlanId` 未绑定 TaskCard `auto-open` → 即使定位成功也不展开（`0ab8a80` 行为回归）；
   - 出题 API 失败时 TaskCard 无兜底，题面只剩一排按钮（「去练习一片空白」的另一支）；
   - 另有 `isArchived/canArchive/archiveTraining` script 侧接线丢失（api.ts 与后端
     `/archive` 端点均在）。
4. **侧栏浮层误触**：rail 图标悬停浮层零延迟，鼠标扫过即弹；头像下拉点外不关。

## What Changes

* **后端**（全部读时聚合，零新表）：
  `GET /trainings/{id}/sources` 每条增 `chunk_count`/`parse_error`；
  `GET /trainings/{id}/plan-items` 每条增 `last_score`（该题×该轮最近一次判分得分，
  source∈llm/quiz/rule）/ `mastery` / `difficulty_tier`；
  `GET /trainings/{id}/path` 阶段条目补 `item_key`（接线修复）。
* **前端**：
  - 新增 `web/src/lib/sourceStatus.ts` 共享映射（待解析/已就绪·N 切片/无切片/
    解析失败+原因/格式不支持）与 `sourcesReady` 判定；
  - 向导第 2 步资料列表状态徽章 + 「下一步」未就绪禁用并给一句诊断；
    第 3 步进入前重拉复核，未就绪禁用「开始探测出题」+「回资料来源」+ 跳过警示；
  - 训练路径 tab（默认）＝场次视图：按 round_index 分组的「第 N 次训练/第 N 轮」卡片
    （计划日/题目数/覆盖知识点数/状态/聚合分数＝场内各题 last_score 均分×100），
    展开行含状态/知识点/分类/难度/掌握度条/最近得分/通过态，点行内联展开 TaskCard 作答；
  - 完整计划 tab＝阶段全貌（整体进度+阶段卡）+ 题库总览接通（懒加载）+ 归档接线恢复；
    「去练习」→ 切训练路径、自动展开定位目标题（auto-open + scrollIntoView）；
  - TaskCard 出题失败兜底（失败块+重试）；App.vue 浮层悬停 600ms 延迟（拍板）、
    头像下拉外点/Esc 关闭。
* **测试**：`tests/test_plan_path_views.py` 3 个端点级钉子（接线缺口教训：payload
  字段必须在端点响应上断言）。

### 联动说明（按最小关联原则申报）

- 详情页「资料来源」tab 与向导共用 sourceStatus 映射——同一信息两处展示；
- `_task_payload` 保持未动（新增字段在 plan-items 端点内合并），`/api/today` 行为不变；
- 归档/题库总览按「接线恢复」处理而非新功能：`api.archiveTraining` 与后端
  `POST /trainings/{id}/archive` 均已存在，本次只补 script 侧状态与懒加载；
- 探测端点（`/wizard/{id}/probe`）的 400 兜底保留不动，门控做在前端进入层。

## Impact

- specs：新增能力 `training-views`（资料就绪可视化与门控 / 场次视图与聚合分数 /
  阶段全貌与跳转作答 / 出题失败兜底）——主规格无现成对应能力，纯 ADDED delta；
- 涉及文件：`src/api/app.py`、`web/src/{api.ts, App.vue, lib/sourceStatus.ts(新),
  views/{WizardView,TrainingDetailView}.vue, components/TaskCard.vue}`、
  `tests/test_plan_path_views.py(新)`；
- 兼容性：全部字段为增量，前端旧字段未动；存量训练（legacy_v21 五轮）显示为
  「第 N 轮」，会话制训练显示为「第 N 次训练」。
