# `src/core` 代码地图

## 范围与总体定位

本文仅覆盖 `src/core/*.py` 中的四个模块：

- `element.py`：训练要素、训练状态与基线等级等共享枚举。
- `baseline.py`：基线分数、等级换算与历史记录选择。
- `training.py`：一次训练的核心状态模型及时间相关判断。
- `content_dim.py`：训练内容维度与按比例分配算法。
- `plan.py`：训练排期与题库口径（固定 5 轮、冷却期、稳定题目键、本地日期）。
- `mastery.py`：客观表现与达标判定（连续通过、准确率、客观档位、难度增量）。

该目录当前是轻量领域层：以枚举、数据类和纯函数表达业务概念与规则，不直接进行数据库访问、文件读写、网络调用或界面渲染。

## 模块职责与关键符号

### `element.py`：共享领域词汇

#### `Element`

表示训练体系的“十要素”。每个枚举成员携带三项元数据：

- `file_prefix`：带顺序编号的文件前缀。
- `chinese_name`：要素简称。
- `description`：要素完整说明。

关键方法：

- `Element.from_prefix(prefix)`：按 `file_prefix` 反向查找要素；找不到时抛出 `ValueError`。
- `Element.ten()`：按枚举声明顺序返回全部十个要素。

十个要素依次为对象档案、基线诊断、训练目标、资料库、复习日历、主动回忆、环境心流、奖励机制、三省吾身、边界与止。

#### `TrainingStatus`

训练生命周期状态枚举：

- `CREATED`
- `ACTIVE`
- `PAUSED`
- `ARCHIVED`
- `FAILED`

该枚举只定义状态集合，不负责校验状态迁移是否合法。

#### `BaselineLevel`

基线等级枚举：`HIGH`、`MID`、`LOW`。它既用于表示绝对基线分数档位，也被 `score_delta_to_level()` 复用为分数变化方向的离散结果。

### `baseline.py`：基线评估规则

#### `BaselineScore`

基线评估数据类，字段包括：

- `score`：总分。
- `dimension_scores`：各维度分数，键为字符串。
- `partial_topics`：仅部分掌握的主题。
- `level`：`BaselineLevel`。
- `recorded_at`：记录时间。

派生属性：

- `score_5_scale`：将 `score` 四舍五入到一位小数；名称表达五分制语义，但实现不执行 `0～5` 截断。

#### `compute_level(score)`

把绝对分数映射为等级：

- `score >= 4.0` → `HIGH`
- `2.5 <= score < 4.0` → `MID`
- `score < 2.5` → `LOW`

#### `score_delta_to_level(delta)`

把分数变化量映射为方向等级：

- `delta >= 0.5` → `HIGH`
- `delta <= -0.5` → `LOW`
- 其余 → `MID`

这里的 `HIGH/MID/LOW` 分别承担明显上升、变化不明显、明显下降的语义。

#### `merge_baseline_history(history)`

从 `BaselineScore` 列表中按 `recorded_at` 选择最新记录。空列表会抛出 `ValueError`。函数名中的“merge”实际是“选取最新值”，不会合并维度分数或主题列表。

### `training.py`：训练状态模型

#### `Training`

训练实体的数据类，可按字段分为以下几组：

| 类别 | 字段 | 含义 |
|---|---|---|
| 标识与生命周期 | `id`、`topic`、`status` | 训练标识、主题与当前状态 |
| 内容约束 | `keywords`、`must_cover_count`、`forbidden` | 关键词、最低覆盖数与禁用项 |
| 工作区定位 | `directory` | 训练目录的 `Path` 表示 |
| 基线 | `baseline_score`、`baseline_level` | 当前训练保存的基线总分和档位 |
| 训练配置与产物 | `targets`、`review_items`、`pretrain_checklist`、`schedule`、`materials` | 目标、复习项、训练前清单、日程和资料 |
| 进度 | `current_week`、`last_review_at` | 当前周与最近复习时间 |
| 审计时间 | `created_at`、`last_active_at` | 创建时间与最近活跃时间 |

关键行为：

- `is_active`：判断 `status` 是否为 `TrainingStatus.ACTIVE`。
- `days_since_creation`：以当前系统时间减去 `created_at`，返回完整天数。
- `needs_weekly_review(now=None)`：以传入的 `now` 或当前系统时间为参照；从 `last_review_at` 开始计算，若从未复习则从 `created_at` 开始计算；满 7 个完整天数时返回 `True`。
- `Training.empty(topic)`：命名构造器，为新主题创建 `CREATED` 状态的初始训练对象。

列表和字典字段均通过 `default_factory` 创建，避免多个实例共享可变默认值。

### `content_dim.py`：内容维度与数量分配

#### `ContentDimension`

训练内容分为三个维度：

- `CONCEPT`：概念。
- `READ`：读代码。
- `WRITE`：写代码。

每个枚举成员携带英文标识、中文名称和展示图标三项元数据。

#### `DEFAULT_DAILY_RATIO`

默认每日比例：

- 概念：30%
- 读代码：40%
- 写代码：30%

#### `distribute_by_ratio(total, ratio)`

按比例把整数总量分配给各内容维度：

1. 当 `total <= 0` 时，为比例表中的每个维度返回 `0`。
2. 对 `total * weight` 取整，得到每个维度的基础数量。
3. 计算尚未分配的余数。
4. 按各维度的小数部分从大到小排序。
5. 将余数依次补给小数部分最大的维度。

这是“最大余数法”的实现。在默认比例以及“非负、总和为 1”的常规输入下，结果之和等于 `total`。函数本身不校验比例：若权重总和不为 1、存在负权重，或待补余数超过维度数，则文档中“总和始终等于 total”的保证可能不成立；相同小数余量按输入字典的键顺序保持稳定。

## 领域模型关系

```text
Element
  └─ 定义训练体系的十要素及其文件命名元数据

TrainingStatus ───────────────┐
                              ├─> Training
BaselineLevel ────────────────┘       ├─ 保存训练状态、配置、进度和基线摘要
       └─────────────────────────────>└─ 提供活跃/复习时间判断
       └─> BaselineScore
       └─> compute_level / score_delta_to_level

ContentDimension
  ├─> DEFAULT_DAILY_RATIO
  └─> distribute_by_ratio
```

主要模型边界：

- `Training` 是训练过程的中心状态容器。
- `BaselineScore` 是一次带时间戳的基线评估快照。
- `Element`、`TrainingStatus`、`BaselineLevel`、`ContentDimension` 提供跨模块一致的有限值集合。
- `Training.baseline_score` / `Training.baseline_level` 与 `BaselineScore` 之间没有自动同步逻辑；调用方需要显式复制或持久化评估结果。

## 设计模式与实现风格

- **枚举值对象**：用 `Enum` 固化十要素、状态、等级和内容维度，避免散落的魔法字符串。
- **数据类领域模型**：`Training` 和 `BaselineScore` 使用 `dataclass` 表达结构化状态，减少样板代码。
- **命名构造器 / 工厂方法**：`Training.empty()` 集中表达“新训练”的初始状态。
- **纯函数规则**：等级换算、历史记录选择和比例分配均以无副作用函数实现，便于独立测试。
- **派生属性**：`is_active`、`days_since_creation`、`score_5_scale` 从已有状态计算视图值，不额外存储重复数据。
- **共享领域语言**：`BaselineLevel` 和 `TrainingStatus` 由 `element.py` 统一定义，再由其他模块引用。
- **稳定排序语义**：最大余数法依赖 Python 稳定排序，在余量相同时保留比例字典的插入顺序。

## 数据流与控制流

### 1. 新建训练

```text
主题字符串
  → Training.empty(topic)
  → status = CREATED
  → 生成带默认配置、默认进度和当前时间戳的 Training
```

后续状态变更、目录建立、目标填充和持久化均不在核心模型内完成。

### 2. 生成并更新基线摘要

```text
原始总分
  → compute_level(score)
  → BaselineLevel
  → 调用方组装 BaselineScore

BaselineScore 历史列表
  → merge_baseline_history(history)
  → recorded_at 最新的快照
  → 调用方将 score / level 同步到 Training（如有需要）
```

若上游模型给出的是分数变化量，则走独立分支：

```text
分数变化量
  → score_delta_to_level(delta)
  → 方向等级
```

绝对分数等级与变化方向共用同一枚举，但二者业务含义不同，调用方需按上下文解释。

### 3. 周复习判断

```text
Training
  → 选择 last_review_at；为空则选择 created_at
  → 与 now（或系统当前时间）相减
  → 完整天数 >= 7
  → 是否需要周复习
```

通过可选 `now` 参数可注入固定时间，便于确定性测试。

### 4. 每日内容分配

```text
总任务数 + 维度比例
  → 各维度乘积取整
  → 计算未分配余数
  → 按小数余量降序补齐
  → 各维度整数任务数
```

## 集成点与边界

### 核心模块内部依赖

- `baseline.py` 从 `element.py` 导入 `BaselineLevel`。
- `training.py` 从 `element.py` 导入 `BaselineLevel` 和 `TrainingStatus`。
- `content_dim.py` 无其他核心模块依赖。
- 当前没有模块直接依赖 `Training` 或 `BaselineScore` 来完成持久化或编排。

### Python 标准库集成

- `datetime`：基线快照时间、训练创建/活跃/复习时间以及周复习判断。
- `pathlib.Path`：仅作为训练目录的数据类型；核心层不访问文件系统。
- `dataclasses`：领域数据结构及安全的可变默认值。
- `enum`：有限领域值集合。
- `logging`：各模块创建了模块级 `logger`，但当前核心代码没有实际日志调用。

### 外部系统边界

这四个模块未直接集成数据库、LLM、Streamlit、配置系统或外部 API。以下职责留给上层调用方：

- 输入分数、比例、时间和状态的合法性校验。
- `Training` 与 `BaselineScore` 的序列化、反序列化和持久化。
- 枚举值与数据库字段、JSON 或界面选项之间的转换。
- 训练状态迁移编排。
- 基线历史与 `Training` 当前基线摘要的同步。
- 根据 `Element.file_prefix` 执行实际文件或目录操作。

---

### `plan.py`：训练排期与题库口径（ADR-0021，2026-09-20 新增）

纯函数，不依赖数据库与 LLM。它是"哪一天练什么"的规则层——排期、冷却期、日期口径都在这里定义。

| 符号 | 作用 |
|---|---|
| `ROUND_OFFSETS = (1, 3, 7, 15, 30)` | 整条路径固定 5 轮，锚点是训练创建日 |
| `round_due_dates(anchor)` | `{轮次: 到期日}` |
| `quiz_due_dates(anchor, until)` | 每 14 天一次测验（与 5 轮同锚点） |
| `cooldown_until(practiced_on)` | 题库冷却期 = 练过日 + 14 天（ADR-0016：测验排除刚练过的原题） |
| `item_key_for(training_id, 知识点, 标题)` | **稳定题目键**（sha1 前 12 位）。计划表与题库引用它，而不是会随路径重生成变化的 `training_items.id` |
| `local_today()` / `parse_local_date()` | 统一"今天"的口径（默认 `Asia/Shanghai`，可用 `TRAINER_TZ` 覆盖） |
| `select_today_slots(slots, today)` | 当日取数：`due_date <= 今天` 且未完成，**每个题目只取最早未完成的那一轮**（"累计到下一天"的实现口径） |
| `total_minutes(tasks)` | 当日预计总时长（用于超限提示） |

---

### `mastery.py`：客观表现与达标判定（2026-09-21 新增）

纯函数。回答两个问题："这道题练到什么程度了"与"四失反馈里的客观一侧该是什么"。

| 符号 | 作用 |
|---|---|
| `MASTERY_STREAK = 2` | 连续通过 2 次即达标（change `training-execution-feedback` 任务 5.1） |
| `MIN_ATTEMPTS_FOR_OBJECTIVE = 3` | 作答少于 3 次时客观口径为 `unknown`，只允许轻微调整（ADR-0015 决策 2） |
| `ACCURACY_LOW = 0.6` / `ACCURACY_HIGH = 0.9` | 冲突裁决的准确率阈值（ADR-0015） |
| `consecutive_passes(results)` | 从最近一次往前数的连续通过次数 |
| `accuracy(results)` | 准确率；**没有数据返回 `None`**，不用 0 冒充 |
| `evaluate(results)` | → `MasteryState(attempts, passes, accuracy, streak, mastered)` |
| `objective_state(results)` | `low` / `mid` / `high` / `unknown`（数据不足） |
| `difficulty_delta(objective, signal_type)` | 难度该升/降/不动，由规则决定（ADR-0010 + ADR-0015） |
