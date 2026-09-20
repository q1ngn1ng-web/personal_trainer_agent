# 20260920 · feat · 学习信号（四失）与动作裁决

## 变更摘要

实现四失反馈：一键标签 → 规则裁决 → 动作与留痕。这是"情绪化感知 → 行动转化"的落地。

## 实现内容

| 层 | 文件 | 内容 |
|---|---|---|
| 数据 | `src/db/tables.sql` | 新增 `learning_signals` 与 `adjustment_log` 两张表 |
| 数据 | `src/db/models.py` | 新增 `LearningSignal` / `AdjustmentLog` |
| 服务 | `src/services/signal_service.py` | 四失映射、冲突裁决、限频、留痕、信号分布 |
| UI | `src/ui/page_daily.py` | 新增「今天的感受」：四个一键标签，点完即给出结果说明 |
| 测试 | `tests/test_signal_service.py` | 12 项：裁决六种分支 + 落库与留痕 |

## 落地的三条硬约束（ADR-0015）

1. **动作由规则层决定**：`decide()` 是纯函数，模型不参与
2. **冲突时以客观为主**：
   - 自评"太简单"但训练项未通过 → **不升难度**，提示"先巩固"
   - 自评"太难"但训练项已通过 → 不降难度，改为**减单次负荷**
   - 客观数据不足 → 只做轻微调整
3. **限频留痕**：同类信号当日累计 2 次才触发结构性调整，每日最多 1 次；**被拦截的也写日志**

## 四失映射

| 信号 | 诊断 | 方向 | 动作 |
|---|---|---|---|
| 太多了 | 贪多嚼不烂 | 收敛 | 减单次负荷 |
| 太窄了 | 所知狭窄 | 拓展 | 补相邻知识点 |
| 太简单了 | 轻视以为易 | 深挖 | 升难度 + 变式 |
| 太难了 | 畏难而止 | 鼓励 | 降难度 + 拆小题 + 提示 |

## 一处必须说明的简化

**客观表现目前用训练项状态（passed / failed）代理**，因为逐次作答记录表还没建。
所以现在从界面点标签，客观状态多为 `unknown`，只会做轻微调整——**冲突裁决的完整能力要等作答记录落地才真正生效**。
已记入 `workspace/BACKLOG.md`。

## 影响范围

- 测试：**149 passed, 1 skipped**（本次新增 12 项）
- 每日任务卡现在的结构：1 复习项 / 2 新学项 / 3 主动回忆题 / 4 完成度 / **5 今天的感受** / 6 留言 / 7 奖励
- 规格：`training-execution-feedback` 完成 **13/33**

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/signal_service.py` | 新增 |
| `tests/test_signal_service.py` | 新增 |
| `src/db/tables.sql`、`src/db/models.py` | 修改 |
| `src/ui/page_daily.py` | 修改 |

## 关联 OpenSpec change id

`training-execution-feedback`（进行中，13/33）
