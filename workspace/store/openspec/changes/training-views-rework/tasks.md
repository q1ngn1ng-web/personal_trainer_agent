# training-views-rework · 任务清单（已实施）

## 1. 资料就绪可视化 + 探测门控

- [x] 1.1 `GET /api/trainings/{id}/sources` 每条增 `chunk_count`（source_chunks 子查询）与 `parse_error`
- [x] 1.2 `web/src/lib/sourceStatus.ts`：状态映射 + `sourcesReady`/`readinessHint` 共享
- [x] 1.3 向导第 2 步资料列表状态徽章（含失败原因、「无切片」警示）
- [x] 1.4 门控：第 2 步「下一步」/第 3 步「开始探测出题」未就绪禁用 + 一句诊断 + 回资料来源；第 3 步进入前重拉复核；后端 400 保留
- [x] 1.5 详情页资料来源 tab 复用同一映射
  - 验收：`test_plan_path_views.py::TestSourcesStatusFields`（端点钉子）✓；线上 curl `chunk_count:19` ✓

## 2. 训练路径＝场次视图 / 完整计划＝阶段全貌 对调

- [x] 2.1 `GET /api/trainings/{id}/plan-items` 增 `last_score`（(item_key×round) 最近判分）/`mastery`/`difficulty_tier`，端点内批查合并、不动 `_task_payload`
- [x] 2.2 训练路径 tab：按 round_index 分组场次卡（序号/计划日/题数/覆盖知识点/状态/聚合分数），展开行含掌握度条+最近得分+通过态，点行内联展开 TaskCard
- [x] 2.3 完整计划 tab：承接整体进度+阶段卡+题库总览（懒加载 questionsOverview）+归档接线恢复
  - 验收：Playwright 实测两 tab 渲染、训练 50 聚合口径 0/25/53 分 ✓；console 零报错 ✓

## 3. 接线缺口修复

- [x] 3.1 path 端点阶段条目补 `item_key`（此前从未下发→「去练习」静默落空）
- [x] 3.2 `openPlanId` 绑定 TaskCard `:auto-open`（恢复 0ab8a80 的展开+滚动定位）；watch 自动展开所属场次；`practiceItem` 对缺键 toast 防静默
- [x] 3.3 `questionList` 接通（修「点完整计划整页空白」的 TypeError）；删除/恢复 isArchived 等残留接线（api.archiveTraining 已存在）
- [x] 3.4 TaskCard 出题失败兜底块+重试
  - 验收：未练项「去练习」→ 切 tab、卡片渲染、textarea+提交出现、出题 POST 200 ✓（修复前 cards:0）；`test_plan_path_views.py::TestPathItemsCarryItemKey` ✓

## 4. 侧栏与头像

- [x] 4.1 三处 group-hover 浮层 `delay-0 group-hover:delay-[600ms]`（拍板：保留浮层、延迟出现）
- [x] 4.2 头像下拉：开时挂 document click/Escape 关单，卸载清理

## 5. 回归与收尾

- [x] 5.1 全量 pytest：412 passed + 30 subtests（唯一失败为已知基线 test_units TemplateNotFound，并行会话在飞）
- [x] 5.2 前端 build + 重启 + curl 验活；record `20261123_feat_training-views.md`
