# training-views-rework · 设计

## 关键决策

### D1 · 「进度可视化」做成状态徽章而非进度条

解析/切片是**同步**的（`parse_source` 在上传请求内完成，无后台任务），不存在
「解析到 43%」的中间态。用户真正需要的是回答「这份资料到哪一步了/还能不能出题」：
每份资料显示 `上传 ✓ → 解析 ✓ → 切片 N 条` 的终态徽章（待解析/已就绪·N 切片/
无切片/解析失败+原因/不支持）。`ok 但 0 切片`（空正文文档）单独标警示——它是
探测 400 的静默成因之一。

### D2 · 门控做在前端进入层，后端 400 保留为兜底

就绪判定 `sourcesReady = 存在(enabled && ok && chunk_count>0)` 纯前端可算
（数据来自加字段后的 sources 端点）。向导第 2 步「下一步」与第 3 步「开始探测出题」
双层禁用 + 一句诊断（`readinessHint` 列出每份未就绪资料的原因）；第 3 步进入时
重拉 sources 防旧状态。「跳过探测」保留（路径有朴素兜底）但附「无资料时路径为空」
警示。后端 `/wizard/{id}/probe` 的 ValueError→400 原样保留，防直连 API 绕过。

### D3 · 场次视图的聚合分数：读时聚合、每题最近一次判分

- **口径**：场（round_index）内每个计划项取 `last_score`（practice_attempts 中该
  item_key×round_index 最近一次 source∈{llm,quiz,rule} 且 score 非空的得分），
  场聚合分 = 已判分题的均分 ×100 取整；无判分则不显示分数徽章（不显示 0 分误导）。
- **落点**：后端在 plan-items 端点内批查合并（两笔 SQL），**不动 `_task_payload`**
  （避免 /api/today 无谓变慢）；前端按 round_index 分组后现算均分。与恒稳控制器的
  `_session_accuracy`（pass 率口径）互不干扰——展示分数用 score，控制器用 result。
- 零新表：事实源仍是 practice_attempts / learner_knowledge（与 session_summary 同律）。

### D4 · 对调而非新建路由

「训练路径/完整计划」仍是 `/trainings/:id` 的两个 tab，只对调内容：路径 tab＝场次
视图（默认），计划 tab＝阶段全貌+题库总览。「去练习」跨 tab 定位链路：
`practiceItem(itemKey)` → section=path + openPlanId=最早 planned 轮次 →
watch(openPlanId) 展开所属场 → TaskCard `:auto-open`（0ab8a80 行为恢复）自动
展开题目并 scrollIntoView。practiced 项 auto-open 不强展（TaskCard 既有语义），
点击行渲染折叠卡可手动展开看历史。

### D5 · 接线恢复三处归为「修」而非「新功能」

- `questionList`：题库总览块模板一直在，接 `api.questionsOverview`（后端既有）懒加载；
- 归档：`api.archiveTraining`/`POST /archive` 一直在，补 `isArchived/canArchive/
  archiveTraining` script 侧（canArchive 限 owner 且 active/completed）；
- `item_key`：path 端点补字段 + `practiceItem` 对 undefined 弹 toast 防再次静默。

### D6 · 已知取舍

- 掌握度列在无记录的行不渲染（不画 0% 假条），列位会有错落——数据补齐后自然对齐；
- legacy_v21 训练显示「第 N 轮」，会话制显示「第 N 次训练」——共用同一分组逻辑；
- 侧栏浮层按用户拍板保留、加 `group-hover:delay-[600ms]`（进 600ms 出现、移开即隐），
  备选的"纯图标去浮层/加宽常显文字"未采用。

## 冲突避让（实施时遵守）

- 热区文件 `src/api/app.py` 与并行会话共存：只动 training_sources / training_plan_items /
  training_path 三处，不碰 wizard 探测端点与其他区域；
- `web/src/api_wizard.ts` 在飞改动（ClarifySession.title）与本 change 无交集，未触碰；
- 全量回归对照已知基线失败（`test_units.py::TestRendererEmpty`，并行模板重构）。
