# 20260920 · feat · 删除训练（不可恢复）+ PDF 知识点命名修正

## 变更摘要

按用户要求加上删除训练（之前只有 `archived` 状态、没有入口）。顺带修了两个真实使用中暴露的问题。

## 1. 删除训练

| 位置 | 改动 |
|---|---|
| `src/db/queries.py` | 新增 `delete_training(id)`：按外键依赖顺序级联清理 13 张关联表，再删训练行 |
| `src/ui/page_home.py` | 新增「🗑 删除训练（不可恢复）」展开区：**必须手动输入训练 ID 才能执行** |
| `tests/test_delete_training.py` | 新增 5 项：级联彻底性、**不误删其他训练**、删不存在的返回 False、删后外键检查为 0 |

设计取舍：

- **不做"归档"而做真删除**——用户明确要清理重复训练，归档解决不了"列表里一堆一样的"这个问题
- **二次确认用输入 ID 而不是点两下**：删除不可恢复，输入 ID 能挡住误点
- 级联顺序按依赖从孙子到子：`daily_log_tasks → daily_logs`、`training_items → path_stages → training_paths`、`source_chunks → sources`，其余按 `training_id` 直删

## 2. PDF 知识点命名修正

**现象**：用户上传的 `Redis 持久化八股文.pdf`（1.2MB）解析正常（0.14 秒 / 4983 字 / 14 切片），
但**切片标题全是「第 1 页」「第 2 页」**——而下游把标题当知识点名，于是"理解边缘"里会出现一堆"第 N 页"。

**修正**：每页标题改取「第一个像标题的短行」（长度 4–24、结尾无标点、至少含 2 个汉字或字母），
找不到才退回「第 N 页」。效果：

| 前 | 后 |
|---|---|
| 第 1 页 / 第 2 页 / 第 3 页 … | **Redis 持久化（第 1 页）** / 第 2 页 / **增量快照（第 5 页）** / **数据安全（第 8 页）** |

## 3. 状态枚举缺项（顺带修掉的真 bug）

`src/core/element.py` 的 `TrainingStatus` 只有 `created/active/paused/archived/failed`，
**缺 `draft` / `pending_confirm` / `confirmed`**。首页靠 `_coerce_status` 的 except 兜底成"已创建"，
所以没崩，但会把"待确认目标""待选资料"的训练显示成"🆕 已创建"。
已补齐枚举并在首页加上对应徽章。

## 影响范围

- 测试：**154 passed, 1 skipped**（本次新增 5 项）
- 首页新增删除入口；PDF 知识点命名改善
- 数据未变动（只加代码，没有对生产库执行删除）

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/db/queries.py` | 新增 `delete_training` |
| `src/ui/page_home.py` | 新增删除面板 + 状态徽章 |
| `src/core/element.py` | 补齐 `TrainingStatus` 枚举 |
| `src/services/doc_parser.py` | PDF 标题启发式 |
| `tests/test_delete_training.py` | 新增 |

## 关联 OpenSpec change id

无（用户直接要求的补功能；`workspace/BACKLOG.md` 的 P0 第 1 条已完成）
