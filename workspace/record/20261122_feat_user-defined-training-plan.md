# 2026-11-22 · 用户自定义训练计划（user-defined-training-plan）

> 类型：feat ｜ 对应 change：`user-defined-training-plan`（tasks 全勾）｜ 按 tasks 顺序实施（0.x 决策已拍板）
> **实质修订 ADR-0021** → 新 ADR-0025（`workspace/decisions/ADR-0025-用户自定义节奏与会话配比排期.md`）

## 变更摘要

固定五轮（+1/3/7/15/30 天，每轮全量）被**会话配比排期**取代（存量 `legacy_v21` 零迁移）：

- **A 投入参数进澄清步**：goal schema 增 `horizon_days`(1-56)/`session_count`(2-6)，
  WizardView 节奏卡片（周 × 次，预填默认 2 周 × 3 次 + 按等级推荐【待校准】），
  user_input 落快照并进 missing_fields（缺失不可确认）；无 UI 流程在建议阶段自动补默认；
- **B 会话配比模型**（`src/core/session_composition.py` 纯函数，零 LLM）：
  并集 100% 硬约束（每项至少 1 次）；单次占比随 N 递减、重叠递增
  （N=2：70%+70%−40%=100%）；重叠池由**正确率恒稳控制器**动态分配
  （目标带 80%±10%：>90% 镜像外推 / 70-90% 维持 20:20 / 60-70% 25:15 / <60% 30:10
  【外推档待校准】）；桶内入选按五星排序（错题 5★ > 回归 3★ > 不稳定 2★ > 稳定 1★）；
  **相同输入必得相同分配**（测试钉死）；
- **C 排期与完成门**：会话日 horizon 内均匀摊开；`generate_plan` 按
  `trainings.schedule_mode` 分发（legacy_v21 五轮 / session_ratio 会话制）；
  周期小测（每 14 天）与终测（trigger='final'，覆盖全部必修、绕过冷却）并存；
  终测通过 → completed；不通过 → `append_session_cycle` 追加一轮同规格周期
  （已稳定项进已知巩固池），**horizon 用尽显式提示不静默**（QuizResult.cycle_appended
  供前端提示"继续或归档"）；允许提前练（提前作答照常判分，不改其余会话排期）；
- **D 滚动重组**：某会话刚全部练完（complete_tasks 钩子）→ 恒稳控制器按最近会话
  正确率重组后续未开始会话（`recompose_future_sessions`，只换清单不挪日期，
  pre_covered 保证已发生覆盖不回退）。

## 口径与实现要点

- **存量隔离**：`schedule_mode` 列（迁移轻量 ALTER，默认 legacy_v21）+
  assessments.trigger CHECK 迁移重建（新增 'final'）；legacy 训练误调终测按普通
  测验走补练轮（测试钉死）；
- **提示词第 6/7 条修订 + 口径 8**：禁的是 **LLM 对话追问**（收集职责移交 UI 控件），
  新增 content/level/acceptance 自洽检查口径；版本 v1.0.0 → v1.1.0；
  **提交纪律**：并行会话在 prompts.py 有未提交改动（BASELINE/开头行）——用
  `git stash push/pop` 隔离，本提交只含 6/7 条 + 口径 8 + 版本号；
- **收编关系**：adaptive-practice-composition 的回炉/提前练被本模型原生吸收
  （adaptive-learning-loop 提案已加撤销注记，剩余范围：定向补材/触发总线/奖励）；
  performance-driven-scheduling 的阶梯被配比控制器吸收（FSRS 路径改挂控制器）；
- 主规格修订：`specs/goal-clarification`「澄清阶段只处理目的」Requirement 改为
  "LLM 只处理目的；投入参数由 UI 控件收集"；0021 ADR 标注被 ADR-0025 部分取代。

## 验证

- `tests/test_session_plan.py` 13 用例：控制器并集/确定性/各正确率档/五星排序、
  pace 端点往返与非法值 400、会话制排期并集 12/12 + UNIQUE 幂等、终测覆盖全部
  必修 + 通过完成 + 不通过追加周期（4-6 次会话 + 终测再次把关）、提前练不改排期、
  legacy 隔离两用例；
- 全量 **383 passed + 30 subtests**（基线 369 + 13 新 + 1 契约更新；唯一失败
  `test_units renderer` 为并行会话基线上已有的在飞失败，与本改动无关）；
  `npm run build` 通过；服务已重启（8501）。
- 【待校准】项：占比阶梯表、>90% 镜像外推档、五星映射——标在
  `session_composition.py`，跑真实数据后回填。
