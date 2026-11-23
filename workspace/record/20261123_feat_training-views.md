# 20261123 · 训练视图重构：资料就绪可视化+探测门控；训练路径/完整计划对调——顺带揪出四类接线缺口

用户反馈（2026-11-23，五点）：
1. 侧边栏鼠标一扫就弹浮层（含右上角头像）；
2. 「没有可用的资料切片，无法出题」——用户怀疑资料没传完，要求资料来源显示进度、先解析完再探测；
3. 点「去练习」一片空白没有题目；
4. 点「完整计划」显示为空；完整计划与训练路径内容放反了——完整计划应放阶段全貌（原训练路径内容），训练路径应放每次训练（第一次训练…含题目/分类/掌握度/聚合分数）；
5. 每次训练贯穿四个阶段的知识点。

提交：`4ff6092`（fix web：侧栏/兜底）、`8f377fa`（feat training-views：对调+门控+钉子）。
openspec：`training-views-rework`（已实施）。

## 诊断（先纠正一个误解）

- **「没传完」不成立**：解析/切片是同步的（`parse_source` 在上传请求内完成）。400 的真实条件是训练**没有「enabled 且 parse_status=ok 且有切片」的来源**——0 份 / failed / unsupported / ok 但 0 切片，而前端把 parse_status 英文原样透传，用户完全看不到资料卡在哪一步。
- **「完整计划空白」的直接元凶**：`TrainingDetailView.vue` 模板引用了 script 里不存在的 `questionList`（`.length` 抛 TypeError，plan section 整段渲染中断）。`isArchived/canArchive/archiving/archiveTraining` 同为丢失的 script 侧接线（api.ts 与后端 `/archive` 端点都在，是 ui-redesign 迁移只搬了模板没搬状态）。
- **「去练习空白/不展开」是三处叠加**：① path 端点阶段条目**从来没有 `item_key` 字段**→ `practiceItem(undefined)` 静默落空；② `openPlanId` 从未绑定 TaskCard 的 `auto-open` prop（`0ab8a80` 的滚动定位行为在迁移中丢失）；③ 出题 API 失败时 TaskCard 无兜底，只剩一排按钮。
- **侧栏**：rail 本无悬停展开逻辑，感知的"自动打开"= 图标右侧 CSS group-hover 浮层；头像是点击式下拉但点外不关。

## 改动

**后端（`src/api/app.py`）**
- `GET /api/trainings/{id}/sources`：每条增 `chunk_count`（source_chunks 子查询计数）+ `parse_error`；
- `GET /api/trainings/{id}/plan-items`：每条增 `last_score`（practice_attempts 按 (item_key×round_index) 最近一次判分得分，source∈llm/quiz/rule 且 score 非空）+ `mastery`（learner_knowledge 批查）+ `difficulty_tier`；读时聚合零新表，合并只在端点内做、不动 `_task_payload`（不影响 /api/today）；
- `GET /api/trainings/{id}/path`：阶段条目补 `item_key`（接线修复）。

**前端**
- `web/src/lib/sourceStatus.ts`（新）：parse_status→中文徽章映射（待解析/已就绪·N 切片/无切片/解析失败+原因/不支持）+ `sourcesReady`/`readinessHint`，向导与详情页共用；
- 向导第 2 步：资料列表改状态徽章+失败原因；「下一步」未就绪禁用并提示；第 3 步进入前重拉复核，未就绪禁用「开始探测出题」+ 回资料来源按钮 + 跳过警示；
- 训练路径 tab（默认）= **场次视图**：planRounds 按 round_index 分组 →「第 N 次训练/第 N 轮」卡（计划日/题目数/覆盖知识点数/状态徽章/**聚合分数**=场内各题 last_score 均分×100 取整）；展开行含状态图标/知识点/分类/难度/**掌握度条**/最近得分/通过态，点行内联展开 TaskCard 作答；默认展开第一个未完成场，openPlanId 变化自动展开所属场；
- 完整计划 tab = 原路径视图（整体进度+阶段卡）+ 题库总览接通（懒加载 `api.questionsOverview`）+ 归档接线恢复；「去练习」→ 切训练路径并自动展开定位（TaskCard auto-open 自带 scrollIntoView）；
- TaskCard：出题失败显示「题目生成失败+重试」兜底块；
- App.vue：三处 group-hover 浮层加 `delay-0 group-hover:delay-[600ms]`（拍板：保留浮层但延迟 600ms）；头像下拉开时挂 document click/Esc 关单、卸载清理。

**测试**：`tests/test_plan_path_views.py` 3 个端点级钉子——sources 字段（含 failed 带 parse_error、ok 零切片两态）、plan-items 指标（0.4→0.9 取 0.9；self 无分不计；mastery 缺为 null；difficulty_tier 在场）、path 条目含 item_key。

## 验证数字

- 全量：**412 passed + 30 subtests**（基线 408+30 上净增 3 个钉子，另有并行会话 +1），唯一失败仍是已知基线 `test_units.py::TestRendererEmpty`（并行模板重构在飞，前后一致）；
- 补跑 path/source 相关 5 文件：54 passed + 3 subtests；
- build 3.6s 无错；重启后 curl：sources 带 `chunk_count:19`；训练 50 plan-items 95 项、13 有判分，聚合口径预演 0/25/53 分；
- Playwright 实测：完整计划 tab 有阶段+整体进度+题库总览；资料 tab「已就绪·19 切片」；**点未练项「去练习」→ 切训练路径、TaskCard 渲染、textarea+提交按钮出现、出题 POST 200**（修复前 cards:0）；console/pageerror 全程 none。

## 教训（接线缺口第三例，见 [[trainer-wiring-gap-lesson]]）

`item_key` 缺失这种 payload 断链，函数级测试全绿也盖不住——阶段条目渲染不需要 item_key，只有「去练习」点击链路才消费它，且失败是**静默的**（undefined → find 落空 → null，无报错无提示）。三个钉子全部按"端点响应断言字段"写。排查信号也值得记：Playwright 拿 innerText 判「要素在不在」会被侧栏「关于」tooltip 的同词文案（"要点清单""判分"）误报，必须配合 DOM 选择器计数与 API 请求监听。

## 纪律备注

- 并行会话在飞改动（docs/architecture.md、src/templates/* 删除、api_wizard.ts、share-gate-confirmations.md）全程未触碰，提交只含自己的 8 个文件；
- 联动申报：①详情页资料 tab 与向导共用 sourceStatus 映射（同一信息两处展示）；②`_task_payload` 保持未动（新增字段在 plan-items 端点合并）；③归档/题库总览按"接线恢复"处理而非新功能（api.ts 与后端端点均已存在）。
