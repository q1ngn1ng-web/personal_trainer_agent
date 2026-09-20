# 20260920 · feat · 今日任务卡：三省可选 + 留言

## 变更摘要

按用户实际使用反馈改造今日任务卡：三省不再强制，新增「给教练留言」，奖励条件只与任务完成度挂钩。

## 用户反馈

> 三省就不要了吧，就是可以不填的，但是需要留言，ui 要友好，不能都让用户去填写。

## 改动内容

| 位置 | 改动 |
|---|---|
| `src/services/daily_log_service.py` | `submit_reflections` 增加 `note` 参数，留言随三省一起写入 `three_reflections` JSON（无需迁移） |
| `src/ui/page_daily.py` | 「4. 三省」改为「5. 给教练留言」（留言常驻 + 三省收进折叠区）；完成度提到第 4 位；奖励条件去掉"必须提交三省" |

## UI 调整前后

| 前 | 后 |
|---|---|
| 1 复习项 / 2 新学项 / 3 主动回忆题 / 4 三省（三个必填大框）/ 5 完成度 / 6 奖励 | 1 复习项 / 2 新学项 / 3 主动回忆题 / **4 完成度** / **5 给教练留言（留言 + 折叠的三省）** / 6 奖励 |

奖励条件：原先要求「任务完成 **且** 提交三省」，现在只要求任务完成——**不填也能领**。

## 影响范围

- 测试：95 passed, 1 skipped（本次改动未新增测试，daily 页暂无 UI 回归测试）
- 与规格的关系：`training-execution-feedback`（未 apply）的规格里已经把三省改为可选；
  本次是**提前实现**了该 change 的一部分 UI 行为
- 被推迟的其他反馈已记入 `workspace/BACKLOG.md`

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/ui/page_daily.py` | 修改 |
| `src/services/daily_log_service.py` | 修改（新增 `note` 参数） |
| `workspace/BACKLOG.md` | 新增（记录用户提出的暂缓项） |

## 关联 OpenSpec change id

无直接关联（提前实现 `training-execution-feedback` 中的 UI 行为）
