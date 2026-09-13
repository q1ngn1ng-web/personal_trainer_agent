# src/

> 范围说明：本 codemap 覆盖 **`src/` 根目录直属文件** 与 **`src/templates/`**（后者没有独立子地图）。
> 子目录 `cli/`、`core/`、`db/`、`llm/`、`services/`、`ui/` 各有独立 codemap，见 [根 codemap](../codemap.md) 的子地图索引。

## 范围与文件清单

`src/` 根目录只有 2 个 Python 文件，都是**骨架**，不含业务逻辑：

| 文件 | 行数 | 角色 |
|------|------|------|
| `__init__.py` | 0 | 空包标记，不导出任何公共 API |
| `main.py` | 150 | Streamlit 进程入口：查询参数路由 + 常驻侧边栏 + 启动时建表 |

> **历史提示（重要）**：2026-07-25 的 commit `9649cca` 删除了根目录 6 个早期 demo 文件 —
> `config.py` / `logger.py` / `models.py` / `storage.py` / `diagnoser.py` / `generator.py`。
> 它们的能力已分别由 `src/db/`（持久化）、`src/core/`（领域原语）、`src/llm/`（LLM 适配）、
> `src/services/`（编排 + 渲染 + 落盘）取代，新代码对它们零引用。
> 本 codemap 曾在此删除动作之前写成，因而长期描述这 6 个**已不存在的文件**；本次已重写为与代码一致。

---

## Responsibility（职责）

`src/` 根目录只承担**应用入口**这一件事：把 HTTP 查询参数翻译成页面渲染调用。
配置、持久化、LLM 调用、业务编排、UI 渲染全部在子目录里，根目录不参与。

- **进程入口与路由** — `main.py` 是 Streamlit 的唯一入口，负责建表、渲染常驻侧边栏、按 `?page=` 分派渲染器。
- **不做的事** — 根目录没有配置常量模块（路径常量散落在 `src/db/sqlite.py`、`src/services/file_writer.py` 等使用点），
  没有领域模型（在 `src/core/` + `src/db/models.py`），没有日志门面（统一用标准 `logging`）。

---

## 关键文件与符号

### `main.py`

- **模块级 `sys.path` 注入**：把项目根插入 `sys.path[0]`。这是必要的 workaround —
  Streamlit 子进程不保证继承 `uv run` 注入的 `PYTHONPATH`，不注入会让 `from src.X import Y` 失败。
- **模块级副作用**：导入即调用 `init_db()`（来自 `src.db.sqlite`），保证 schema 就绪。
  即"只要进程起来了，表就存在"，CLI 的 `init-db` 因此只是手动补建手段。
- **模块级字典 `PAGES: dict[str, callable]`**：初始为空，由 `_register_pages()` 惰性填充。
- **`_register_pages()`**：**延迟导入** 5 个 UI 渲染器（`page_home` / `page_new_training` /
  `page_training` / `page_daily` / `page_review`），避免冷启动全量加载。已填充则直接返回。
- **`_goto(page, training_id=None)`**：sidebar 跳转的统一出口 —
  先清空 `st.query_params` 全部键，再写入 `page`（与可选 `training_id`），最后 `st.rerun()`。
  清空是必要的：残留的旧 `training_id` 会让新页面加载到错误训练。
- **`_render_sidebar()`**：常驻侧边栏，所有页面共享。内容为主导航（首页 / 新建）+ 训练列表
  （由 `src.db.queries.list_trainings()` 拉取，最多展示 `_SIDEBAR_MAX_TRAININGS = 8` 条），
  当前训练高亮为 `●`，超出部分显示"…还有 N 个"。
- **`main()`**：`st.set_page_config(...)` → `_register_pages()` → `_render_sidebar()` →
  读 `st.query_params["page"]`（缺省 `"home"`）→ `PAGES[page]()`；
  未知 `page` 写回 `home` 并 `st.warning`。

启动方式：`uv run streamlit run src/main.py`。

### `src/templates/`

10 份 Jinja2 模板（`.md.j2`），由 `src/services/renderer.py` 的 `render_training_files(context)`
渲染成每个训练目录下的 10 份 Markdown。模板层**不做 IO**，只接收 context 字典；落盘由
`src/services/file_writer.py` 负责（原子写：`.tmp` → `os.replace`）。

实际文件名（注意与 `src/core/element.py` 的枚举名**不完全一致**，详见下方"已知边界风险"）：

| 模板文件 | 对应 `Element` 成员 |
|----------|---------------------|
| `00_对象档案.md.j2` | `OBJECT` |
| `01_基线诊断.md.j2` | `BASELINE` |
| `02_训练目标.md.j2` | `GOAL` |
| `03_资料库.md.j2` | `MATERIAL` |
| `04_复习日历.md.j2` | `SCHEDULE` |
| `05_主动回忆题.md.j2` | `METHOD`（枚举名为"05_主动回忆"） |
| `06_环境配置.md.j2` | `ENVIRONMENT`（枚举名为"06_环境心流"） |
| `07_奖励机制.md.j2` | `REWARD` |
| `08_每日反省.md.j2` | `REFLECTION`（枚举名为"08_三省吾身"） |
| `09_边界与止.md.j2` | `BOUNDARY` |

---

## 设计模式

- **延迟注册（Lazy Registry）** — `main.py._register_pages()` 用模块级 dict + 首次访问填充，
  把"路由表"与"渲染器导入"解耦，启动只加载当前页面。

---

## 数据与控制流

### 冷启动 → 路由

```
uv run streamlit run src/main.py
   └─ import src.main
        ├─ sys.path 注入项目根
        ├─ import src.db.sqlite → init_db()（建表，幂等）
        ├─ st.set_page_config(...)
        ├─ _register_pages()        # 延迟 import 5 个 page_* 模块
        ├─ _render_sidebar()        # list_trainings() → 训练列表按钮
        ├─ st.query_params["page"]  # 缺省 "home"
        └─ PAGES[page]()            # 调用对应 render()
```

### 页面间跳转

```
sidebar 按钮 / 页面内按钮
   └─ _goto(page, training_id)
        ├─ 清空 st.query_params 全部键
        ├─ 写入 page（+ 可选 training_id）
        └─ st.rerun() → 回到上述查询参数分派
```

唯一的跨页面状态载体是 URL 查询参数；`st.session_state` 只在单个页面内部使用
（例如 `page_daily` 记录回忆题判分结果），没有跨进程的会话存储。

---

## Integration（与其它模块/子目录的边界）

> 本节只描述 **src/ 根目录 + templates/** 如何与其它模块对话，不描述其它模块的内部实现。

| 起点 | 出方向 | 入方向 | 说明 |
|------|--------|--------|------|
| `main.py` | `from src.db.sqlite import init_db` | — | 启动时建表；这是根目录与 DB 子目录**唯一**的硬绑定 |
| `main.py` | `from src.ui.page_* import render` | — | 延迟导入 5 个页面；根目录只认 `render()` 这一个接口 |
| `main.py` | `from src.db.queries import list_trainings` | — | 侧边栏拉训练列表（读操作） |
| `src/templates/*.md.j2` | — | `src/services/renderer.py` 经 `TEMPLATES_DIR` 读取 | 模板不含 IO；根 `src/` 不直接引用模板 |

### 已知边界风险（基于当前代码事实）

1. **`sys.path` 注入是运行时补丁** — Streamlit 子进程的环境继承不可靠，`main.py` 顶部手动
   插入项目根。这是有效的修法，但属于环境耦合：若将来改用 `st.navigation` 或打包分发，
   这里需要重新评估。
2. **`init_db()` 在模块导入时执行** — 导入 `src.main` 即建表，属于导入副作用。
   好处是"起了就有表"，代价是导入不再纯净，测试时难以隔离。
3. **UI 层直连 DB** — 架构文档声明"UI 不直访 DB"，实际 `page_daily` / `page_training` /
   `page_review` 都 `from src.db.queries import ...` 做读操作。当前是"约束 + 读操作破例"，
   写操作仍全部收口在 `services/`。
4. **模板名与领域枚举名不一致** — `src/templates/` 的实际文件名、`src/core/element.py`
   的 `Element` 枚举、`src/llm/prompts.py` 的 `MD_GENERATION_PROMPT` 中列举的文件名，
   三者对"05 / 06 / 08"三个要素的措辞各不相同（如"主动回忆题" vs "主动回忆" vs "材料清单"）。
   当前不影响运行（渲染走模板文件、枚举只用于展示），但改名时容易踩坑。
5. **空 `__init__.py`** — `src/__init__.py` 为 0 字节，不导出公共 API；所有子模块一律用完整
   路径导入（`from src.db.sqlite import init_db`）。
