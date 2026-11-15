# 20261115 feat Streamlit→Vue 迁移收尾——仪表盘与周复盘页上线，第一版 UI 退役

> 类型：feat｜用户决策：个人版完成"全部换成 Vue"（方案 1），第一版 UI 退役

## 变更摘要

把第一版 Streamlit UI 里 Vue 尚未覆盖的最后两块搬进 Vue，至此 Vue 版功能上完整
取代第一版；`trainer-streamlit-local` 服务已 stop + disable（进程与自启一并退役，
systemd 单元文件保留在 /etc 供回滚）。

1. **进度仪表盘**（page_home → DashboardView）：
   - 后端 `GET /api/dashboard`：`progress_service.compute_home_dashboard()` 跨训练聚合
     （活跃训练数、累计坚持天数、平均基线分、逐训练的今日完成度/当前周/最近活跃），
     按登录用户可见性过滤；
   - 前端 `DashboardView.vue` + 路由 `/dashboard` + 导航「仪表盘」：指标卡 +
     逐训练进度行（点击进入训练详情）。
2. **周复盘**（page_review → TrainingDetailView「周复盘」section）：
   - 后端三端点：`GET /review/weekly`（prepare：本周指标 + LLM 校准建议，模型不可用
     时启发式兜底并显式标注 fallback_used）、`POST /review/apply`（持久化基线/排期/
     资料调整 + baseline_history + review_archives 归档）、`POST /review/skip`
     （仅归档）；
   - 前端「周复盘」section：生成 → 指标与建议展示 → 应用/跳过。

## 影响范围

- 新增 4 个端点 + 1 个 Vue 页面 + 1 个详情页 section；判分/记忆/导入链路不变。
- Streamlit 服务退役（disable），代码资产 `src/ui/` 保留在仓库（回滚可用）。

## 验证

- 新增 `tests/test_dashboard_review.py`（4 条）：仪表盘聚合字段、周复盘 prepare 的
  启发式兜底断言、apply 落 baseline_history + review_archives(user_action=confirmed)、
  skip 归档 skipped。
- 全量 **325 passed + 30 subtests**；前端 `npm run build` 通过。
- 服务 `trainer-api` 已重启；`/api/dashboard` 验证 401（鉴权要求而非 404）。

## 相关文件

`src/api/app.py`、`web/src/{api.ts,router.ts,App.vue,style.css}`、
`web/src/views/{DashboardView.vue,TrainingDetailView.vue}`、`tests/test_dashboard_review.py`
