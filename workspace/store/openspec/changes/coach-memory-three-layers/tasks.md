# coach-memory-three-layers · 任务清单（待实施会话执行）

- [ ] 0.1 定稿偏好三键（app_settings，snake_case 沿用 memory_service 先例）：
      `coach_hint_enabled`（默认 "1"）、`daily_minutes_target`（默认 "30"）、
      `question_type_preference`（enum any/choice/fill/qa，默认 "any"）
- [ ] 1.1 连败纯函数：`failure_streak(training_id, item_key)` —— 最近 graded attempt
      （source IN ('llm','quiz')，practice-only 不计）按 id 倒序数前导 fail，pass 清零；
      建议放 `src/core/` 或 answer_service 私有函数（可单测）
- [ ] 1.2 submit_answer 响应加附加字段 `failure_streak`（int）与 `coach_hint`（streak≥3 且
      coach_hint_enabled 时给模板文案，含历次分数列表；否则空串）——**只加键不改键**
- [ ] 1.3 `session_summary.py`：`summarize_day(training_id, date)` 读时聚合当天 graded
      attempts → 题数/通过率/错要点频次/最弱知识点/各题 streak；模板化叙述（LLM 叙述走
      app_settings 开关 `session_llm_narrative` 默认关，预留）
- [ ] 1.4 端点三个（均过训练可见性守卫）：`GET /api/trainings/{id}/session-summary?date=`、
      `GET /api/preferences`、`PUT /api/preferences`（键白名单校验，沿用 queries 白名单风格）
- [ ] 1.5 前端：TaskCard 显示 coach_hint（warn 样式）；训练详情页小结卡；偏好设置入口（可后置）
- [ ] 1.6 测试：streak 规则（practice-only 不计/pass 清零/≥3 触发）、小结聚合与空日、
      端点契约（含未登录 401 / 越权 403）、偏好读写与非法键拒绝
- [ ] 1.7 全量回归（基线见最新 record）+ record/evidence + 归档
