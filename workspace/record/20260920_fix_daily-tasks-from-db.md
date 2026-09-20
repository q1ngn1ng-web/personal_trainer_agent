# 20260920 · fix · 今日任务卡改读数据库训练项 + 可重入探测

## 用户反馈

> 第 3 步现在回去不了，我怎么回去？……现在在训练这里看不到今日训练的内容，来源也有问题

## 根因

**今日任务卡读的是老流程的文件系统。** `extract_today_tasks` 从 `trainings.schedule`（由十份 md 的
`04_复习日历.md` 填充）里取任务；而新流程不生成那十份文件，`schedule` 永远是空的，
于是"今日无新学项 / 暂无回忆题"。

训练项其实**已经在数据库里**（`training_items`），只是没人去读。

## 修复

| 改动 | 内容 |
|---|---|
| `src/services/path_service.py` | 新增 `current_stage()` / `today_tasks()` / `mark_item()`：取当前阶段的待练项，勾选后同步状态 |
| `src/services/schedule_service.py` | `schedule` 为空时**回退到数据库训练项**，并把题型（memory/comprehension/practice）映射成内容维度（concept/read/write） |
| `src/ui/page_daily.py` | 勾选训练项时同步写 `training_items.status`，否则它明天还会再出现 |
| `src/ui/page_path.py` | 新增「🎯 重新定位理解边缘」与「📅 今日任务」入口——**向导走完也能回到第 3 步** |

## 效果

训练 #42 的今日任务卡现在显示 5 个真实训练项：

```
T1 Redis 是什么与核心使用场景        📖 概念   来源：Redis基础与使用场景
T2 五大基本数据结构与底层编码         📝 读代码 来源：String/List/Hash/Set/ZSet
T3 常用命令与时间复杂度              📖 概念   来源：常用命令与时间复杂度
T4 高级数据结构：Bitmap、HyperLogLog …
T5 用 Redis 设计简单业务模型并讲清选型 …
```

## 未解决 / 待确认

- **「来源也有问题」用户未说清具体现象**（是列表少了、状态不对、还是切片不对？）——需要补充
- 达标判定未实现：现在勾选即视为"练过并完成"，不是"连续 2 次达标"

## 影响范围

- 测试：**156 passed, 1 skipped**
- 今日任务卡从"空"变成有内容；路径页多了两个入口

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/path_service.py` | 新增 `current_stage` / `today_tasks` / `mark_item` |
| `src/services/schedule_service.py` | 回退到数据库训练项 |
| `src/ui/page_daily.py` | 勾选同步训练项状态 |
| `src/ui/page_path.py` | 新增两个入口 |

## 关联 OpenSpec change id

无（用户反馈驱动的修复；`training-execution-feedback` 的每日执行部分）
