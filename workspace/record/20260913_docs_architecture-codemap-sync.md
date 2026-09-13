# 20260913 · docs · 修正架构文档与代码一致性

## 变更摘要

修复"文档描述的文件已经不存在"这一类遗留问题。

**根因**：2026-07-25 的 commit `80ade48`（23:17:29）一次性写入全套 codemap + 架构文档，
**4 分钟后**的 commit `9649cca`（23:21:48）删除了 `src/` 根目录 6 个早期 demo 文件
（`config.py` / `logger.py` / `models.py` / `storage.py` / `diagnoser.py` / `generator.py`），
但没有任何一份文档跟进更新。此后 `src/codemap.md` 被根 `codemap.md` 当作"src/ 根目录地图"
链接出去，读者点进去看到的是 6 个不存在的文件。

### 1. `src/codemap.md` — 全文重写

原文（194 行）与实际代码的冲突：

| 原文表述 | 实际代码 |
|---|---|
| "`src/` 根目录下共有 8 个 Python 文件" | 只有 2 个：`__init__.py`、`main.py` |
| 逐节详解 `config.py` / `logger.py` / `models.py` / `storage.py` / `diagnoser.py` / `generator.py` | 6 个文件全部已删除 |
| `main.py` 74 行；无 `_goto` / `_render_sidebar` | 150 行，含常驻侧边栏与 `_goto` 路由 |
| "已知边界风险"分析 `storage.Storage._init_db()` 的双源 schema | 该文件已不存在，风险不成立 |

重写要点：

- 文件清单改为真实的两份骨架文件，并说明根目录"只承担应用入口"这一职责边界。
- **补上 `src/templates/`**——该目录原先没有独立 codemap，也没有被根目录地图覆盖，属于文档盲区；
  现列出 10 份模板的实际文件名及其与 `src/core/element.py` 枚举的对应关系。
- `main.py` 的符号说明按当前代码重写：`sys.path` 注入、模块级 `init_db()` 副作用、
  `_register_pages()` 延迟导入、`_goto()` 清空全部 `query_params`、`_render_sidebar()` 上限 8 条训练。
- 顶部保留一段"历史提示"，记录那 6 个文件的删除时间与替代模块，避免后人重复困惑。
- "已知边界风险"从"基于已删除代码的推断"换成 5 条当前事实，其中第 4 条为**本次新发现**：
  `src/templates/` 实际文件名、`src/core/element.py` 的 `Element` 枚举、
  `src/llm/prompts.py::MD_GENERATION_PROMPT` 里列举的文件名，三方对"05 / 06 / 08"三个要素
  的措辞互不相同（如"主动回忆题" / "主动回忆" / "材料清单"）。当前不影响运行，但改名时会踩坑。

### 2. `workspace/record/architecture.md` — 修正硬错误

该文件是 `trainer-mvp-v1` 提案期的架构快照，内容与 `docs/architecture.md` 大面积重叠但更旧。
本次**不重写**，只做两件事：顶部加"历史快照 / 已被 docs/architecture.md 取代"的注记；
修正 6 处与当前代码直接冲突的表述（正文均带"**已修正**"标记）：

1. 架构图 `DbModels` 标注"Pydantic 模型" → 实际是 `@dataclass` + 自定义 `RowModel`。
2. 模块边界表列出 `src/config.py` / `src/logger.py` → 两文件已删除，条目移除。
3. `src/cli/` 描述为"`init-db`、`seed` 等命令" → 实际只注册了 `init-db`。
4. `call_purpose` 枚举写作 `baseline_question` / `keyword_extract` / `recall_question` /
   `calibration_judge` → 实际是 `topic_validation` / `keyword_generation` / `baseline_q` /
   `baseline_scoring` / `weekly_calibration` / `md_generation` / `pretrain_checklist`（共 7 个）。
5. `llm_calls` 字段写作 `input` / `output` → 实际列名是 `input_text` / `output_text`。
6. 演进方向称"DB schema 已预留 `is_active` 字段" → 表中无此字段，状态由
   `trainings.status`（`created` / `active` / `paused` / `archived` / `failed`）承载。

另修正两处附带错误：`src/main.py` 写作"Streamlit 多 Page 路由"（实际是 `?page=` 查询参数路由）、
`trainings` 描述里的"当前间隔天数"（实际字段为 `current_week`）；
并把架构图 `services` 子图从 9 个节点补全为实际的 14 个 service 模块。

## 影响范围

- 新人 onboarding 路径：根 `codemap.md` → `src/codemap.md` 不再指向不存在的文件；
  `workspace/record/architecture.md` 不再被误当作现行架构文档。
- 无任何代码逻辑改动，纯文档。已验证重写后文档中引用的全部路径与 10 个模板文件名均真实存在。

## 相关文件路径

| 文件 | 动作 |
|---|---|
| `src/codemap.md` | 重写（194 行 → 描述真实文件） |
| `workspace/record/architecture.md` | 修正 6 + 2 处过时表述 + 顶部加历史快照注记 |

## 关联 OpenSpec change id

无（纯文档修正，未触动任何 spec / change / 提案）。
