# 20260920 · fix · PDF 知识点粒度与探测题兜底

## 用户反馈

> 这个页面很烂，提取的应该是题目而不是页面，不能说哪一页讲的什么

探测页给出的题目全是「用自己的话说明『第 N 页』讲的是什么」——知识点是页码，题目是模板。

## 根因（两个，都是我的问题）

**根因一：PDF 解析把"页"当成了知识单元。**
原实现按页抽文本，只把每页**第一个**短行当标题，其余内容全并进正文。
于是"Redis 持久化八股文"这种**小标题 + 要点**结构的文档，被压成了 8 个「第 N 页」。

**根因二：模型失败没有留痕。**
`edge_probe` 调用失败时 `complete()` 抛异常，我在服务层直接 `except` 掉了，
**没有写 `llm_calls`**——所以事后查不到任何失败原因。
（手动重跑同一个调用是成功的，说明那次失败是偶发；但因为没有留痕，无法确认。）

## 修复

### 1. PDF 按**字号**识别标题（`doc_parser.parse_pdf`）

- 用 `get_text("dict")` 取每行的最大字号，出现最多的字号作为**正文基准**
- 字号 ≥ 基准 × 1.12、长度 ≤ 30、像标题的短行 → `##` 标题
- **一页可以有多个标题**；整页没标题就并入上一节，**不再造「第 N 页」这种假知识点**

效果（用户那份 PDF）：

| 前 | 后 |
|---|---|
| 8 个知识点：第 1 页 … 第 8 页 | **19 个**：Redis的持久化机制 / RDB 持久化 / RDB 的优缺点 / 写时复制技术 / AOF 重写过程 / 混合持久化 / 持久化的选择 … |

### 2. 顺带修掉切片器的**标题栈层级 bug**（`core/source.split_markdown`）

原实现 `stack = stack[:level-1]` 会让**同级标题互相嵌套**（`## A` 后面跟 `## B`，B 成了 A 的子项）。
改为按 `(level, title)` 维护，弹到第一个层级更浅的标题为止。修完所有 19 个知识点都是平级，不再出现假父节点。

### 3. 兜底问法改掉（`edge_service._fallback_question`）

| 前 | 后 |
|---|---|
| 用自己的话说明「X」讲的是什么。 | 先找片段里**现成的问句**（如「RDB 快照时能修改数据吗？」）；找不到才用「请说出『X』的关键要点」 |

### 4. LLM 失败必须留痕（`llm.client.log_llm_failure`）

`edge_probe` / `edge_probe_grade` / `path_skeleton` 失败时写入 `llm_calls`
（`validation_result=fail` + `failure_reason`），下次再出现异常可以直接查库定位。

## 影响范围

- 测试：**156 passed, 1 skipped**（新增 2 项：一页多标题、无标题页不造假知识点）
- 数据：用新解析器**重跑了用户已有的 `src#2`**（Redis PDF），训练 #42 的知识点从 8 个假页码变成 19 个真主题
- 探测页新增一行说明：资料里共识别出 N 个知识点

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/services/doc_parser.py` | PDF 字号识别标题 |
| `src/core/source.py` | 修标题栈层级 bug |
| `src/services/edge_service.py` | 兜底问法 + 失败留痕 |
| `src/services/path_service.py` | 失败留痕 |
| `src/llm/client.py` | 新增 `log_llm_failure` |
| `src/ui/page_new_training.py` | 显示知识点总数 |
| `tests/test_doc_parser.py` | 新增 2 项回归 |

## 关联 OpenSpec change id

无（用户反馈驱动的修复；`understanding-edge-assessment` 的解析质量部分）
