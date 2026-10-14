# 执行说明：learner-memory-and-grading

> 给接手的会话（或未来的自己）：本文件是唯一入口，按顺序读完即可开工。
> 创建日期：2026-10-15

## 0. 一句话目标

给 Trainer Agent 补上三件事：**跨 30 天的学习者记忆**、**可解释且按题型分流的判分**、**按需生成并引用资料的解析**。

## 1. 必读文件（按这个顺序）

1. 本文件
2. `proposal.md` —— 为什么做、做什么、五条关键取舍
3. `design.md` —— 判分模型、记忆三层、数据模型变更
4. `tasks.md` —— 任务清单，**执行时以它为准**，做完一项勾一项
5. 项目根 `AGENTS.md` —— 工程规矩（uv 运行、OpenSpec 闭环、收尾三件事）

## 2. 硬约束（违反即返工）

1. **不要引入记忆框架**（mem0 / Zep / LangChain Memory / MemGPT）——见 proposal 取舍表。
2. **不要用向量检索或自然语言摘要做事实层**——错题类查询必须精确。
3. **服务保持无状态**：不许把"30 天记忆"实现成常驻内存的会话。
4. **客观题（选择/填空）判分不许调用大模型**——这是本期最核心的收益点，要用 `llm_calls` 表断言。
5. **要点清单随题固化**，不许在判分时临时生成。
6. **不许编造数字**：没有实测的指标写成【待测】，并说明卡在哪一步。
7. 所有 Python 命令走 `uv run`；密钥不进仓库。

## 3. 执行顺序（按阶段推进，每阶段跑完测试再进下一段）

### 阶段 0：基线确认（10 分钟）

```bash
cd /home/ubuntu/py_code/personal_trainer_agent
uv run pytest -q                     # 记录当前是否全绿，作为基线
openspec validate learner-memory-and-grading --store store
```

产出：一句话回报"基线测试是否全绿、有多少条用例"。

### 阶段 1：数据层（离线性最强，先做）

- tasks 1.1—1.4：`question_type`、`options`、`question_points` 表、`practice_attempts.score` / `point_results`、`assessment_items.question_type`

验收：`uv run python -c "..."` 或迁移脚本执行后，能查到新字段与新表；**旧数据不丢**（老题 `question_type` 默认 `qa`）。

### 阶段 2：判分

- tasks 2.1—2.5：`grading_service.py`、客观题确定性判分、要点评分（覆盖率 × 正确性）、必答一票否决、达标判定改造

验收（本条最关键）：

```bash
# 判一道选择题后，确认没有新增 llm_calls 记录
```

以及：三点答两点 = 2/3；答满但说反一条 < 答对两条；缺必答项直接不通过。

### 阶段 3：出题

- tasks 3.1—3.3：按题型出题 + 产出要点清单 + 干扰项取自同一资料片段 + 落库 `source_chunk_ids`

验收：抽样检查干扰项均能在来源切片中找到依据。

### 阶段 4：记忆

- tasks 4.1—4.4：`memory_service.py`、薄弱点画像（纯 SQL）、替换上下文组装、产出 token 对比

验收：生成画像过程**零 LLM 调用**；产出一份"渲染后 token vs 原始作答 token"的数据。

### 阶段 5：整场评分

- tasks 5.1—5.2：聚合写入 `assessments.score` / `passed`，产出综合反馈

验收：一次 20 题的测验能查到总分，反馈能指出具体薄弱知识点。

### 阶段 6：按需解析

- tasks 6.1—6.2：解析按需生成 + 引用资料片段 + 记录学习信号

验收：解析含可回指的来源片段；能按题目统计查看次数。

### 阶段 7：自适应出题

- tasks 7.1：下一场题型配比按上一场薄弱项调整

验收：构造"选择题失误多"的场景，下一场选择题占比上升；本场已完成题目不受影响。

### 阶段 8：验证与收尾

- tasks 8.1—8.5

```bash
uv run pytest -q
openspec validate learner-memory-and-grading --store store
```

然后按 AGENTS.md 收尾三件事：**跑测试 → 回填 `workspace/evidence/` → 写 `workspace/record/`**，最后 git 提交。

## 4. 完成后必须同步的两处（否则简历会重复出错）

1. `/home/ubuntu/for-work/求职主张-证据账本.json` —— 把对应主张的状态从"待确认"改为"已确认"，并补证据路径；
2. `/home/ubuntu/for-work/场景定稿-Trainer记忆与判分.md` —— 按"启用条件"表逐条放行简历条目。

## 5. 回报格式（做完请按此格式回复）

```
已完成：阶段 X 的 tasks a.b—a.c
证据：<文件绝对路径 / 命令>
实测数字：<如 token 对比、判分一致性>
未完成 / 卡住：<任务号 + 原因>
下一步建议：<任务号>
```

## 6. 已知的坑（前人踩过，别重复）

- `assessments.score` / `passed` 字段早就存在但一直是空的，别以为是新加的；
- `question_bank.item_type` 是**训练项类型**（memory/comprehension/practice），和题型不是一回事，别复用；
- `practice_attempts` 的注释写着"客观表现的唯一数据源"，新增字段时不要改变它的语义；
- `TRAIN_QUESTION_PROMPT` 现在只出开放式问答，改造成多题型时要同步更新对应的 JSON Schema；
- 项目里 `apply_patch` 对含三引号的长文本补丁可能解析失败，必要时拆成小补丁。
