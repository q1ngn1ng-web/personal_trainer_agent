# performance-driven-scheduling · 任务清单（backlog，未排期）

- [ ] 0.1 写新 ADR（继 0022）：阶梯前进/重置模型取代 0021 固定锚定；practice-only 与补练语义定稿；0021 标注被取代
- [ ] 0.2 迁移决策：训练级 schedule_mode 区分存量（旧口径）与新训练；确认不加 step 列（从 attempts 推导）
- [ ] 1.1 core/plan 阶梯纯函数：next_due(step, passed, completed_date)、step_from_attempts
- [ ] 1.2 plan_service：轮完成事件重算该 item 后续轮次 due_date（original_date 保留轨迹；幂等可重放）
- [ ] 1.3 初始错峰：首轮到期按阶段顺序 + 每日预算摊开（回归 daily-budget 初衷）
- [ ] 1.4 达标转可选：training_items passed 后剩余轮次移出今日默认清单（手动入口保留）
- [ ] 1.5 fail → step=0 + 次日到期；测验补练通过 → step 视为到顶
- [ ] 1.6 今日/详情 payload 与前端：阶梯位置、下次到期原因、可选巩固入口
- [ ] 1.7 测试：pass 前进 / fail 重置 / practice-only 不动 / 达标可选 / 初始错峰 / 重算幂等 / 测验节奏不互扰
- [ ] 1.8 修订 specs/training-plan 固定 5 轮 Requirement；更新 adaptive-practice-composition 的收编边界
