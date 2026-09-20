# src/db/

> 本目录是个人训练师 Agent 的**持久化层**。仅依赖 `sqlite3` 标准库 + `python-dotenv`，对外提供 dataclass 模型和 CRUD 查询函数，业务层（`src/services/`、`src/ui/`、`src/cli/`）均通过它访问 SQLite 数据库 `data/trainer.db`。

涉及文件：`sqlite.py`（连接管理 + 初始化）、`models.py`（数据模型）、`queries.py`（查询函数）、`tables.sql`（建表 DDL，放同目录以便 `executescript` 装载）、`__init__.py`（空包标识）。

---

## 1. 职责（Responsibility）

| 文件 | 职责 |
|---|---|
| `sqlite.py` | 解析数据库路径、打开 SQLite 连接、应用全局 PRAGMA、执行建表脚本。 |
| `models.py` | 用 `@dataclass` 描述业务实体，提供 `RowModel` 基类自动处理 `sqlite3.Row → 模型对象` 的转换与 JSON 字段解码。 |
| `queries.py` | 所有 CRUD / 聚合 SQL 的封装；统一事务边界、JSON 编解码、字段白名单校验。 |

**非职责**：本目录不负责：
- 业务规则编排（由 `src/services/` 承担）
- LLM 调用本身（仅把调用结果写入 `llm_calls` 表）
- Schema 迁移（DDL 仅 `CREATE TABLE IF NOT EXISTS`，无 `ALTER` / 版本号）

---

## 2. 模型 / 查询 / 连接（Models / Queries / Connections）

### 2.1 连接（`sqlite.py`）

```
_PROJECT_ROOT = Path(__file__).resolve().parents[2]   # 项目根
_SCHEMA_PATH  = Path(__file__).with_name("tables.sql") # 同目录 tables.sql
```

- `_db_path(db_path)`：读取 `DB_PATH` 环境变量（默认 `./data/trainer.db`），`expanduser()` 处理 `~`。
- `get_connection(db_path=None)`：
  - 解析路径后若不是绝对路径则相对 `_PROJECT_ROOT` 解析；
  - `path.parent.mkdir(parents=True, exist_ok=True)` 自动建 `data/`；
  - `sqlite3.connect(str(path))` 打开连接；
  - `row_factory = sqlite3.Row` 让结果按列名访问；
  - `PRAGMA foreign_keys = ON` 强制外键约束（schemas 有 FK，必须开启）；
  - `PRAGMA journal_mode = WAL` 启用 WAL 日志，提升并发读性能。
- `init_db(db_path=None)`：用 `executescript(_SCHEMA_PATH.read_text(...))` 一次性执行 `tables.sql`，事务提交后关闭。

### 2.2 模型（`models.py`）

**`RowModel` 基类**（抽象出"行 → 模型"通用逻辑）：

- `json_fields: ClassVar[frozenset[str]]`：子模型声明哪些列是 JSON 字符串。
- `from_row(row: sqlite3.Row) -> Self`：
  - `dict(row)` 取出列名-值；
  - 对 `json_fields` 中的列调用 `_loads()` 反序列化（失败时记 warning 并保留原字符串）；
  - 用 `__dataclass_fields__` 做白名单过滤，丢弃未声明的列；
  - `cls(**filtered)` 构造实例。
- `to_dict()`：`asdict(self)` 序列化为普通 `dict`（不递归处理嵌套 JSON 字段）。

**`Element(str, Enum)`**：十要素词汇表（与 `docs/` 中培训十要素对齐），用于在训练状态字段中标识语义：

```
TRAINING_GOAL / BASELINE / STAGED_TARGETS / MATERIALS / REVIEW_ITEMS /
SCHEDULE / RECALL_PRACTICE / THREE_REFLECTIONS / REWARD / WEEKLY_REVIEW
```

**6 个 dataclass 实体**（列名与 `tables.sql` 一一对应，默认值也一致）：

| 模型 | 主要字段（JSON 列加⭐） | json_fields |
|---|---|---|
| `Training` | `id, topic, status, must_cover_count, baseline_score, baseline_level, current_week, last_review_at, created_at, last_active_at` + ⭐`keywords, forbidden, targets, review_items, pretrain_checklist, schedule, materials` | 7 个 |
| `DailyLog` | `id, training_id, log_date, total_tasks, completed_count, recall_questions_total/correct, recall_success_rate, reflection_submitted_at, created_at` + ⭐`three_reflections` | 1 个 |
| `BaselineHistory` | `id, training_id, baseline_score, recorded_at` + ⭐`dimension_scores` | 1 个 |
| `LLMCall` | `id, training_id?, call_purpose, prompt_name, prompt_version, model, input_text, output_text, validation_result, retry_count, latency_ms, tokens_in/out, failure_reason, fallback_used, created_at` + ⭐`output_json` | 1 个 |
| `ReviewArchive` | `id, training_id, week_start, user_action, created_at` + ⭐`metrics, llm_suggestions` | 2 个 |
| `DailyLogTask` | `id, daily_log_id, task_type, task_ref, completed, completed_at, is_required` | 0 个 |

`DailyLogTask` 是 schema 中存在但当前 `queries.py` **未提供** CRUD 的表（潜在扩展点）。

### 2.2.1 本轮新增的表与列（ADR-0021，2026-09-20）

| 对象 | 说明 |
|---|---|
| `plan_items` | 训练计划：`(到期日, 训练, 题目, 轮次)` 一条计划项。`UNIQUE(training_id, item_key, round_index)`；`kind ∈ {train, assessment}`；`status ∈ {planned, practiced, skipped}` |
| `question_bank` | 测验题库：练过的题入池，`cooldown_until` = 练过日 + 14 天（冷却期内的题不得被抽中，ADR-0016） |
| `training_items.item_key` | **稳定题目键**（`sha1(training_id + 知识点 + 规范化标题)[:12]`）。`plan_items` 与 `question_bank` 引用它，而不是会随路径重生成变化的 `id` |
| `training_items.status` 新增 `practiced` | "练过"（勾选写入）；`passed` 收窄为"达标"，只由达标判定写入 |
| `practice_attempts`（2026-09-21） | 逐次作答记录：`(training_id, item_key, plan_id, round_index, result, source)`。准确率、连续达标、客观通道都以它为准 |
| `training_items.mastered_at` | 达标时间（由 `attempt_service.mark_mastered_if_ready` 写入） |
| `assessments`（2026-09-21） | 测验批次：`trigger ∈ {scheduled, manual, stage_end}`、`status`、`score`、`passed` |
| `assessment_items` | 测验题目与判分：`item_key` 回指题库，`is_variant` 标记是否变式题，`verdict ∈ {pass, fail}` |

迁移由 `migrate._rebuild_training_items` 负责：重建表 + 回填 `item_key`，走迁移三件套
（`isolation_level=None` + `foreign_keys=OFF` + `legacy_alter_table=ON` + 显式事务），迁移后自检 `foreign_key_check`。

### 2.3 查询（`queries.py`）

**私有工具函数 / 常量**：

- `_now() -> str`：`datetime.now(timezone.utc).isoformat()`，所有时间戳写入都用它。
- `_json(value)`：`None` / `str` 原样返回，否则 `json.dumps(..., ensure_ascii=False)`（保留中文）。
- `_connection(conn)` 上下文管理器：
  - 若调用方未传 `conn`，则**自己开**一个（`owned=True`），退出时关闭；
  - 正常路径 `commit()`，异常路径 `rollback()` 后向上抛；
  - 调用方可传入同一个 `conn` 实现多语句事务。
- `_TRAINING_STATUSES = {"created","active","paused","archived","failed"}`：写入前枚举校验。
- `_TRAINING_FIELDS`：训练表允许写入的列白名单。
- `_JSON_TRAINING_FIELDS`：训练表中需要 JSON 编码的列子集。

**公开 API（按实体分组）**：

| 函数 | 表 | 操作 | 关键行为 |
|---|---|---|---|
| `create_training(**fields)` | `trainings` | INSERT | 必填 `topic`；自动填 `created_at`；列白名单；JSON 编码；返回含 id 的模型 |
| `get_training(id)` | `trainings` | SELECT by id | 无则 `None` |
| `list_trainings(status?, order_by_last_active=True)` | `trainings` | SELECT | 默认按 `last_active_at DESC, created_at DESC` |
| `update_training(id, **fields)` | `trainings` | UPDATE | 空 fields 直接返回现状；列白名单；`status` 枚举校验；JSON 编码 |
| `set_training_status(id, status)` | `trainings` | UPDATE | 在 `update_training` 基础上同步刷 `last_active_at=_now()` |
| `get_or_create_daily_log(training_id, log_date)` | `daily_logs` | INSERT OR IGNORE + SELECT | 利用 `(training_id, log_date)` 唯一约束幂等创建 |
| `update_daily_log_progress(log_id, completed, total, recall_correct, recall_total)` | `daily_logs` | UPDATE | 自动算 `recall_success_rate = correct/total`（无 total 时为 `None`） |
| `submit_three_reflections(log_id, reflections_json)` | `daily_logs` | UPDATE | 写 `three_reflections` + `reflection_submitted_at` |
| `get_daily_logs_in_range(training_id, start, end)` | `daily_logs` | SELECT | 含端点 `BETWEEN`，按 `log_date` 升序 |
| `add_baseline_history(training_id, score, dimension_scores_json)` | `baseline_history` | INSERT | 时间戳由 `_now()` 写入 |
| `record_llm_call(**fields)` | `llm_calls` | INSERT | 必填 8 项；可选默认 `retry_count=0, fallback_used=0`；`output_json` 自动编码；返回插入的 `id` |
| `get_calls_by_purpose(call_purpose)` | `llm_calls` | SELECT | 按 `created_at DESC, id DESC` |
| `get_calls_by_prompt_version(name, version)` | `llm_calls` | SELECT | 同上 |
| `get_success_rate_by_prompt_version()` | `llm_calls` | 聚合 | `AVG(CASE WHEN validation_result='pass' THEN 1 ELSE 0)`，返回 `{prompt_name: {version: rate}}` |
| `get_avg_latency_by_model()` | `llm_calls` | 聚合 | `{model: avg_latency_ms}` |
| `create_review_archive(training_id, week_start, metrics, llm_suggestions, user_action)` | `review_archives` | INSERT | `week_start` 支持 `date` 或 `str` |
| `get_reviews_by_training(training_id)` | `review_archives` | SELECT | 按 `week_start DESC, id DESC` |

---

## 3. 持久化流程（Persistence Flow）

### 3.1 启动 / 初始化
```
src/main.py: init_db()
  → get_connection()  // 解析 DB_PATH、确保 data/、开连接 + PRAGMAs
  → executescript(tables.sql)  // 全部 CREATE TABLE / CREATE INDEX IF NOT EXISTS
  → commit(); close()
```

### 3.2 单次写操作（以 `create_training` 为例）
```
caller → create_training(topic="X", ...)
  ├─ 字段白名单过滤、JSON 编码（keywords/targets/...）
  ├─ with _connection(conn):
  │     ├─ 若 caller 没传 conn：get_connection()（拥有所有权）
  │     ├─ INSERT INTO trainings (...) VALUES (...)
  │     ├─ SELECT * FROM trainings WHERE id = lastrowid
  │     ├─ 退出 with → commit() （异常则 rollback）
  │     └─ 若 owned：close()
  └─ Training.from_row(row) → 反序列化 JSON 字段 → 返回
```

### 3.3 单次读操作（以 `get_training` 为例）
```
caller → get_training(id=5)
  ├─ with _connection(conn):
  │     ├─ SELECT * FROM trainings WHERE id = ?
  │     └─ 退出 with → commit() + close()
  └─ Training.from_row(row) if row else None
```

### 3.4 多步事务（调用方模式）
当业务层需要"读-改-写"原子化时，可传入自己的 `conn`：
```python
conn = get_connection()
try:
    t = get_training(1, conn=conn)
    update_training(1, conn=conn, status="active")
    get_or_create_daily_log(1, date.today(), conn=conn)
finally:
    conn.close()
```
因为 `_connection()` 检测到非空 `conn` 时只 `commit` / `rollback`，不关闭。

### 3.5 JSON 字段编码边界
- **写入**：`queries._json()` 把 dict/list 转 JSON 字符串，`None`/`str` 原样保留（允许 SQL `NULL`）。
- **读取**：`RowModel.from_row()` 调 `_loads()` 反序列化；解码失败仅记 warning，**不会抛错**，保留原字符串便于排查。

---

## 4. Schema 关系（Schema Relationships）

> DDL 在 `tables.sql`（与本目录同级）。以下 ER 用文本描述。

```
                  trainings  (1)
                ┌──────┼──────┬─────────────┐
                │      │      │             │
        daily_logs   baseline_  llm_calls   review_archives
        (N)        history (N)  (N)         (N)
            │
            └── daily_log_tasks (N)   ← 注意：queries.py 暂未封装此表
```

**外键（`PRAGMA foreign_keys=ON` 必须开启才生效）**：
- `daily_logs.training_id → trainings.id`
- `baseline_history.training_id → trainings.id`
- `llm_calls.training_id → trainings.id`（可空：与训练无关的调用也能记录）
- `review_archives.training_id → trainings.id`
- `daily_log_tasks.daily_log_id → daily_logs.id`

**CHECK 约束**（schema 层做枚举校验）：
- `trainings.status ∈ {created, active, paused, archived, failed}` —— 与 `queries._TRAINING_STATUSES` 完全一致（双层校验：schema + Python）。
- `trainings.baseline_level ∈ {high, mid, low}` 或 NULL。
- `llm_calls.call_purpose ∈ {topic_validation, keyword_generation, baseline_q, baseline_scoring, weekly_calibration, md_generation, pretrain_checklist}` —— 7 类用途，恰好对应 `src/services/` 里 7 个调用 LLM 的服务模块。
- `review_archives.user_action ∈ {confirmed, skipped}`。
- `daily_log_tasks.task_type ∈ {review, new, recall}`。

**唯一约束**：
- `daily_logs UNIQUE (training_id, log_date)` —— 这正是 `get_or_create_daily_log` 用 `INSERT OR IGNORE` 幂等创建的基础。

**索引**（覆盖最热查询路径）：
| 索引 | 服务于 |
|---|---|
| `idx_trainings_last_active_at (last_active_at)` | `list_trainings(order_by_last_active=True)` |
| `idx_daily_logs_training_date (training_id, log_date)` | `get_daily_logs_in_range`、`get_or_create_daily_log` |
| `idx_baseline_history_training (training_id, recorded_at)` | 将来按训练查历史基线 |
| `idx_llm_calls_purpose (call_purpose)` | `get_calls_by_purpose` |
| `idx_llm_calls_prompt_version (prompt_name, prompt_version)` | `get_calls_by_prompt_version`、`get_success_rate_by_prompt_version` |
| `idx_review_archives_training_week (training_id, week_start)` | `get_reviews_by_training` |

**JSON 列与 Python 模型对照**：
所有标 "TEXT" 的 JSON 列在 Python 侧都是 `Any` 类型，由 `RowModel.json_fields` 显式登记，编/解码对称。

---

## 5. 集成点（Integration Points）

### 5.1 上游依赖
- `python-dotenv`：在 `sqlite._db_path()` 内 `load_dotenv()`，读取 `DB_PATH`、项目里其它 `.env` 变量（API key 等）。
- `sqlite3`（标准库）：唯一 DB 驱动。
- `pathlib`：定位 `_PROJECT_ROOT` 与 `_SCHEMA_PATH`。

### 5.2 下游消费者（按层）

**入口层**
- `src/main.py`（Streamlit 入口）→ `init_db()`
- `src/cli/__main__.py` → `init_db()`
- `tests/test_units.py` → `init_db / get_connection / create_training / get_training / _now`

**脚本 / 工具**
- `scripts/seed_test_data.py`、`scripts/e2e_full_flow.py`、`scripts/check_llm_logs.py`、`scripts/harness_smoke.py` —— 测试 / 演示 / 巡检路径

**UI 层（`src/ui/`）**
- `page_training.py`、`page_daily.py`、`page_review.py` —— 仅 `import src.db.queries`，不直接碰连接

**业务服务层（`src/services/`）**

| 服务 | 使用 API |
|---|---|
| `trainer_service` | 训练 CRUD（创建 / 列表 / 更新状态） |
| `review_service` | 周复盘归档 + `Training` 模型 |
| `calibration_service` | `record_llm_call` + `Training` |
| `scoring_service` / `baseline_service` / `keyword_service` / `topic_validation` | `record_llm_call`（每个服务一种 `call_purpose`） |
| `daily_log_service` | 日志 CRUD + `submit_three_reflections` + 直接 `get_connection()` |
| `progress_service` | `get_daily_logs_in_range`、`get_training`、`list_trainings`、直接 `get_connection()` |
| `metrics_calculator` | `get_daily_logs_in_range` + 直接 `get_connection()`（多步骤事务 / 自定义 SQL） |
| `recall_service` / `schedule_service` | `get_training` |

**注意旧实现**：`src/storage.py`（如存在）是早期版本，含自己的 `_init_db()`，**已被本目录取代**——上层不应再依赖它。

### 5.3 LLM 可观测性集成
- 每个调用 LLM 的 service 在收到响应后必须 `record_llm_call(...)`，否则 `scripts/check_llm_logs.py` 看不到对应记录，`get_success_rate_by_prompt_version` / `get_avg_latency_by_model` 也就统计不到。
- `call_purpose` 取值必须落在 schema 的 CHECK 集合内；`prompt_name` / `prompt_version` 与 `src/services/prompts/`（若有）中的提示词模板版本对齐，便于按版本回溯成功率。

### 5.4 外部边界
- **不依赖任何 ORM**（无 SQLAlchemy），保持零依赖、易调试。
- **不存储凭据**，仅凭 `DB_PATH` 定位文件。
- **数据库文件本身不在代码仓库**（`.gitignore` 排除 `data/trainer.db`），所有 schema 与迁移意图都通过 `tables.sql` 这份 DDL 表达。
