# src/

> 范围说明：本 codemap **只覆盖 `src/` 根目录直属 Python 文件**，子目录（`cli/`、`core/`、`db/`、`llm/`、`services/`、`ui/`、`templates/`）不在本文件描述范围。

## 范围与文件清单

`src/` 根目录下共有 8 个 Python 文件 + 1 个空包标记：

| 文件 | 行数 | 角色 |
|------|------|------|
| `__init__.py` | 0 | 空包标记（Python 包初始化） |
| `config.py` | 41 | 路径常量、`.env` 加载、System Prompt 热加载 |
| `main.py` | 74 | Streamlit 应用入口 + 基于 `?page=` 的查询参数路由 |
| `models.py` | 47 | 全部 Pydantic 数据模型（用户画像 / 诊断题 / 基线 / 会话） |
| `logger.py` | 54 | 基于 Rich 的结构化日志 `AgentLogger` |
| `storage.py` | 158 | SQLite 持久化 `Storage`（sessions / baselines 两张表） |
| `diagnoser.py` | 111 | `Diagnoser`：基于关键词的题库 + 基于规则的评分器 |
| `generator.py` | 256 | `Generator`：根据画像 + 基线生成 5 个训练 Markdown |

---

## Responsibility（职责）

`src/` 根目录文件承担**应用骨架 + 核心领域原语**两件事，**不**包含 UI 渲染、DB 驱动、LLM 客户端、CLI、Service 编排（这些都在子目录里）。

- **应用入口与路由** — `main.py` 是 Streamlit 的进程入口，负责数据库初始化和按 URL 参数分派页面渲染器。
- **环境与路径配置** — `config.py` 集中所有路径常量（`WORKSPACE_DIR`、`DB_PATH`、`LOGS_DIR` 等）和 LLM 环境变量（`DEEPSEEK_API_BASE/KEY/MODEL`），并提供 `load_system_prompt()` 的运行时热加载。
- **数据契约** — `models.py` 用 Pydantic 定义**全应用共享**的 4 个领域模型，作为子目录模块间传递数据的统一语言。
- **持久化** — `storage.py` 把"训练会话 + 基线结果"落到 `data/trainer.db`，并支持按主题查询最近会话与全量列举。
- **诊断能力** — `diagnoser.py` 为给定主题产出 3 道前置诊断题，并把用户回答评成"低/中/高"三档基线。
- **文件包生成** — `generator.py` 根据画像 + 基线把"十要素闭环 v3"中的前 5 个训练文件（00–04）落盘到 `workspace/training_<theme>/`。
- **可观测性** — `logger.py` 提供 ReAct 风格的 thought/action/observation 流式日志，文件落盘 + 控制台 Rich Panel 双输出。

---

## 关键文件与符号

### `config.py`
- 常量：`PROJECT_ROOT`、`PROMPTS_DIR`、`LOGS_DIR`、`WORKSPACE_DIR`、`TEMPLATES_DIR`、`DATA_DIR`、`DB_PATH`。
- LLM 配置（环境变量）：`LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL`（命名沿用 `DEEPSEEK_*`，注释里允许替换为 grok / ollama）。
- ReAct 调参常量：`MAX_REACT_STEPS=10`、`MAX_RETRIES=3`、`TIMEOUT_SECONDS=30`。
- 函数：`load_system_prompt() -> str` — 首次调用时若 `prompts/system_prompt.txt` 不存在则写入默认中文提示并返回，否则读取并返回最新内容（实现"运行时热加载"，但当前没有文件监听机制，依赖调用方重新触发）。
- 副作用：模块导入时即调用 `mkdir(parents=True, exist_ok=True)` 创建 4 个目录。

### `main.py`
- 模块级副作用：导入即调用 `init_db()`（来自 `src.db.sqlite`），保证 schema 就绪。
- 模块级字典：`PAGES: dict[str, callable]`，初始为空。
- `_register_pages()`：**延迟导入** 5 个 UI 渲染器（`page_home` / `page_new_training` / `page_training` / `page_daily` / `page_review`），避免冷启动全量加载。
- `main()`：调用 `st.set_page_config`、填充 `PAGES`、读 `st.query_params["page"]`（缺省 `"home"`），分发到对应 `render()`；未知 `page` 写回 `home` 并 warning。
- 启动：`uv run streamlit run src/main.py`。

### `models.py`
- `UserProfile`：必填字段含 Literal 限制（`background`、`target_level`），`daily_time` / `total_weeks` 强制 `gt=0`。
- `DiagnosisQuestion`：含 `question`、`reference_answer`（注释明确"内部判断用，不直接展示给用户"）、`category`（默认 `"基础"`）。
- `BaselineResult`：`level` ∈ `{低, 中, 高}`；`score` 限定 `0..3`；`pre_training_needed` 与 `diagnosis_notes` 默认空。
- `TrainingSession`：聚合根，持有 `session_id`、`workspace_path`、`status ∈ {active, paused, completed}`、两个 `datetime` 时间戳。
- 注：使用 Pydantic v1 风格（`Field(...)`、无 `model_config`），未见到 v2 的 `model_config = ConfigDict(...)`。

### `logger.py`
- 依赖 `rich.console.Console` 和 `rich.panel.Panel`，`console` 是模块级单例。
- 类 `AgentLogger(session_id="default")`：构造时绑定 `self.log_file = LOGS_DIR / f"agent_{session_id}.log"`，并维护内存 `self.steps: list[dict]`（仅 thought/action/observation 会追加）。
- 6 个公开方法：`thought` / `action` / `observation` / `info` / `error` / `success`，每个都先调私有 `_write(level, content)` 追加时间戳到日志文件，再用 `console.print(Panel(...))` 输出到终端。
- 日志行格式：`[<YYYY-MM-DD HH:MM:SS>] [<LEVEL>] <content>`，追加模式（`"a"`）写入 UTF-8 文件。

### `storage.py`
- 类 `Storage(db_path: Path = DB_PATH)`：构造时自动调用 `_init_db()`。
- `_get_conn()`：每次新开 `sqlite3.connect` 并设置 `row_factory=sqlite3.Row`，**未使用连接池**。
- `_init_db()`：用 `CREATE TABLE IF NOT EXISTS` 建 2 张表：
  - `sessions`（12 列，PK=`session_id`，外键引用方为 `baselines`）
  - `baselines`（含 `id INTEGER PK AUTOINCREMENT`，`session_id` 作 FK）
- `save_session(profile, baseline, workspace_path) -> str`：生成 8 位 UUID 作 `session_id`，同时插入 `sessions` 和 `baselines`（answers 与 pre_training 用 `"|"` 拼接存为 TEXT）。
- `get_latest_session(theme=None)`：按 `theme` 过滤或不过滤，取 `ORDER BY created_at DESC LIMIT 1`，把 Row 字段手工映射到 `TrainingSession`（含 `datetime.fromisoformat`）。
- `list_sessions()`：遍历全表并映射为 `List[TrainingSession]`，无分页。

### `diagnoser.py`
- 类 `Diagnoser`，纯 Python（**不调用 LLM**），两个公开方法。
- `generate_questions(theme: str) -> List[DiagnosisQuestion]`：
  - 先 `theme.lower()`，用 `any(k in theme_lower for k in [...])` 三段匹配：
    - Python / 编程 / 自动化 / 脚本 → 3 道硬编码题（list vs tuple、偶数 for 循环、requests 用途）。
    - 英语 / 雅思 / 托福 / english → 3 道硬编码题（自我介绍、present perfect vs simple past、阅读速度）。
    - 其他 → 3 道**主题内插**的通用兜底题。
  - 返回始终是长度为 3 的列表。
- `evaluate(questions, answers, profile) -> BaselineResult`：
  - 评分规则：`a.strip().lower()`，长度 < 8 或命中白名单（`不知道 / 不会 / 没学过 / 不清楚 / no idea`）→ 0 分且把 `q.category` 加入 `pre_training`；否则 +1。
  - 分档：3 分 = 高，2 分 = 中，0–1 分 = 低。
  - `notes` 拼成 `"用户背景：{background}，目标：{target_level}。诊断得分 {score}/3。"`。
  - 注释里明确"v0.1 使用规则评分（后续可替换为 LLM 评分）"。

### `generator.py`
- 类 `Generator`，纯 Python，1 个公开方法 + 5 个私有生成器。
- `generate(profile, baseline) -> Path`：
  - `safe_theme`：把主题里非 `[A-Za-z0-9_-]` 的字符替换为 `_`，目录名形如 `training_<safe_theme>`，落在 `WORKSPACE_DIR` 下。
  - 构造 `files` 字典，只装 5 个键（`00_对象档案.md` ~ `04_复习日历.md`），其余 5 个（05–09）**全部以注释形式占位**，未实现。
  - 逐文件 `write_text(content, encoding="utf-8")`，返回 `workspace` 的 `Path`。
- 5 个 `_gen_NN_xxx` 方法：每个返回一段**中文 Markdown**，里面大量使用 `{p.theme}` / `{b.level}` 等 f-string 插值；部分段落引用《学记》《大学》《荀子·劝学》。
- `_gen_02_goals` 根据 `b.level` 三档动态生成"小成/中成/大成"目标描述；周数边界用 `max(3, total_weeks//3)` 等启发式。
- `_gen_03_resources` 同样按关键词分支：Python/编程/自动化 给具体书单；其他主题用 `{theme}` 内插通用占位。
- `_gen_04_calendar` 生成第 1 周日历（7 行 Markdown 表），首日/末日/中间日分别用不同任务描述。
- **已知缺陷**：`generate()` 只产出 5/10 文件；`_gen_04_calendar` 返回的 f-string 内容相对 00–03 明显偏短（结尾在 `## 间隔重复算法（简化版）` 标题后即收口，未实现具体表格），是当前文件的实现缺口。

---

## 设计模式

- **延迟注册（Lazy Registry）** — `main.py._register_pages()` 用模块级 dict + 首次访问填充，把"路由表"和"渲染器导入"解耦，启动成本低。
- **聚合根（Aggregate Root）** — `models.TrainingSession` 把一次训练的画像/基线/路径/状态聚成一个对象；`storage.save_session` 在一个事务里同时写入 `sessions` 和 `baselines` 两表，保持一致性。
- **策略表（Strategy by Keyword）** — `Diagnoser.generate_questions` 和 `Generator._gen_03_resources` 都用 `theme_lower` + `any(k in s for k in [...])` 的"关键词路由"代替真正的分类器或 LLM 判断，简单但脆弱（同一主题命中多个分支时取先匹配者）。
- **模板方法（Template Method，隐式）** — `Generator` 暴露 1 个 `generate()` 入口 + N 个 `_gen_NN_xxx` 钩子，子类化或替换 `_gen_*` 即可定制输出。
- **结构化日志门面（Structured Logging Facade）** — `AgentLogger` 把"thought/action/observation"三段式封装为统一 API（参考 ReAct 论文），上层调用者只需关心语义，不用管时间戳/落盘/Panel。
- **Pydantic 作为数据契约** — 用 `Literal` 约束枚举、`Field(gt=0)` 约束数值，把"输入校验"前移到模型层，下游模块可信任 `models.*` 实例。

---

## 数据与控制流

### 启动 → 路由（冷启动）
```
streamlit run src/main.py
   └─ import src.main
        ├─ import src.db.sqlite          # 触发 init_db()（建表）
        ├─ set_page_config(...)
        ├─ _register_pages()             # 延迟 import 5 个 page_* 模块
        ├─ st.query_params["page"]       # 缺省 "home"
        └─ PAGES[page]()                  # 调用对应 render()
```

### 新建训练 → 持久化（最常见的完整链路）
```
UI (page_new_training, 在 src/ui/)
   ├─ 收集 → UserProfile (src.models)
   ├─ Diagnoser.generate_questions(theme)         # src.diagnoser
   │     └─ 返回 List[DiagnosisQuestion]
   ├─ Diagnoser.evaluate(questions, answers, profile)
   │     └─ 返回 BaselineResult
   ├─ Generator.generate(profile, baseline)       # src.generator
   │     ├─ 创建 workspace/training_<theme>/
   │     └─ 写 00_对象档案.md ... 04_复习日历.md
   └─ Storage.save_session(profile, baseline, workspace_path)
         ├─ uuid4()[:8] → session_id
         └─ 事务内 INSERT sessions + INSERT baselines
```

### LLM / Prompt 热加载
```
load_system_prompt()              # src.config
   ├─ 检查 prompts/system_prompt.txt 是否存在
   ├─ 不存在 → 写默认中文 prompt 并返回
   └─ 存在 → 读文件返回最新内容
```
> 注：当前**没有文件 watcher**，所谓"热加载"等价于"每次调用都重读"，调用方需要主动重新触发才能拿到修改。

### 日志流
```
AgentLogger.thought(text)
   ├─ _write("THOUGHT", text) → 追加到 logs/agent_<session>.log
   ├─ steps.append({...})     → 内存步骤列表
   └─ console.print(Panel(...)) → Rich 终端面板
```
action / observation / info / error / success 走同一条管道，只是 level 与样式不同。

### 数据落点
| 类别 | 路径 | 写入方 |
|------|------|--------|
| 训练文件包 | `workspace/training_<theme>/00_对象档案.md` ... `04_复习日历.md` | `Generator` |
| SQLite 数据库 | `data/trainer.db`（表 `sessions`、`baselines`） | `Storage` + `src.db.sqlite.init_db` |
| Agent 日志 | `logs/agent_<session_id>.log` | `AgentLogger._write` |
| System Prompt | `prompts/system_prompt.txt` | `config.load_system_prompt`（首次写入默认） |

---

## Integration（与其它模块/子目录的边界）

> 本节只描述 **src/ 根目录文件**如何与其它模块对话，不描述其它模块的内部实现。

| 起点（src/ 根文件） | 出方向 | 入方向 | 说明 |
|--------------------|--------|--------|------|
| `main.py` | `from src.db.sqlite import init_db` | — | 启动时建表，是 src/ 根与 DB 子目录的唯一硬绑定。 |
| `main.py` | `from src.ui.page_* import render` | — | 延迟导入 5 个 UI 页面；**src/ 根不依赖 UI 的具体实现**，只调 `render()`。 |
| `config.py` | `os.getenv("DEEPSEEK_*")` | — | 提供 LLM 配置常量，但本身**不**调用 LLM；真正调用 LLM 的代码在子目录（如 `src/llm/`）。 |
| `config.py` | `Path(__file__).parent.parent.resolve()` → `PROJECT_ROOT` | — | 所有路径常量都从 `PROJECT_ROOT` 派生，下游模块用 `from config import WORKSPACE_DIR` 等即可。 |
| `models.py` | — | `storage.py`、`diagnoser.py`、`generator.py` 全部 import | 是 src/ 根内部的"数据契约中枢"，4 个模型被三个核心类共用。 |
| `storage.py` | `sqlite3.connect(DB_PATH)` | — | 直接用 stdlib `sqlite3`，**不**走 `src/db/` 子目录的封装；与 `init_db()` 在 schema 上需要保持一致（两处都建表，存在双源定义风险）。 |
| `storage.py` | `INSERT baselines (..., "|".join(answers), "|".join(pre_training))` | — | 用 `"|"` 序列化 list 字段，反序列化未在 root 层做（依赖调用方或 UI 层处理）。 |
| `diagnoser.py` | 返回 `BaselineResult` | `Generator` 用 `b.level`、`b.score`、`b.pre_training_needed` 决定 Markdown 内容 | 评分规则与生成器强耦合（"低/中/高"三档字符串必须一致）。 |
| `generator.py` | 写文件到 `WORKSPACE_DIR` | `Storage.save_session(..., workspace_path=str(workspace))` 把同一路径写进 `sessions.workspace_path` | 文件包与 DB 通过 `workspace_path` 字符串关联。 |
| `generator.py` | — | `src/templates/*.j2`（Jinja2 模板，存在但**未被任何 root 文件使用**） | root 层的 Generator 仍用 Python f-string 手写 Markdown，templates 目录目前是预留资产。 |
| `logger.py` | `from config import LOGS_DIR` | — | 唯一一处跨文件依赖；`AgentLogger` 预期被 `src/cli/` 等子目录复用（CLI/Agent 子目录可能调用 `.thought/.action/.observation`）。 |
| `models.py` / `storage.py` | — | `src/services/`、`src/core/`（推断） | 根层模型很可能也是子目录服务层的入参/出参类型。 |

### 已知边界风险（基于代码事实）
1. **Schema 双源**：`main.py` 调 `src.db.sqlite.init_db()`，`storage.Storage._init_db()` 也建表，两处的 DDL 必须手动保持一致，否则字段漂移。
2. **存储与生成器耦合于枚举字符串**：`BaselineResult.level` 用中文"低/中/高"，`Generator` 与 `Diagnoser` 都硬编码同一组字符串；任何改名都会引发静默 bug。
3. **10 文件承诺未兑现**：`Generator.generate` 注释里承诺"完整 10 文件"，实际只生成 5 个（05–09 全部以 `#` 注释占位）。
4. **空 `__init__.py`**：`src/__init__.py` 当前 0 字节，未导出任何公共 API；所有子模块都通过完整路径（`from src.db.sqlite import init_db`）访问。