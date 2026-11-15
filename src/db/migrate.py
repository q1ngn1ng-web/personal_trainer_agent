"""SQLite 迁移：为既定变更补齐字段与约束。

SQLite 无法修改 CHECK 约束，因此新增训练状态值与新的 ``call_purpose`` 需要**重建表**。
本模块的迁移函数可重复执行：已迁移过的库再次调用不会产生任何变更。

对应 OpenSpec change ``goal-clarification-confirm`` 的任务 1.1 / 1.2。
"""
from __future__ import annotations

import logging
import sqlite3

from src.core.plan import item_key_for

logger = logging.getLogger("src.db.migrate")

_TRAININGS_DDL = """
CREATE TABLE trainings_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'draft' CHECK (status IN ('created', 'draft', 'pending_confirm', 'confirmed', 'active', 'paused', 'completed', 'archived', 'failed')),
    goal_json TEXT,
    goal_confirmed_at DATETIME,
    clarification_rounds INTEGER DEFAULT 0,
    keywords TEXT,
    must_cover_count INTEGER DEFAULT 2,
    forbidden TEXT,
    directory TEXT,
    baseline_score REAL DEFAULT 0,
    baseline_level TEXT CHECK (baseline_level IS NULL OR baseline_level IN ('high', 'mid', 'low')),
    targets TEXT,
    review_items TEXT,
    pretrain_checklist TEXT,
    schedule TEXT,
    materials TEXT,
    current_week INTEGER DEFAULT 1,
    last_review_at DATETIME,
    created_at DATETIME NOT NULL,
    last_active_at DATETIME
)
"""

_TRAININGS_COLUMNS = (
    "id, topic, status, keywords, must_cover_count, forbidden, directory, baseline_score, "
    "baseline_level, targets, review_items, pretrain_checklist, schedule, materials, current_week, "
    "last_review_at, created_at, last_active_at"
)

_LLM_CALLS_DDL = """
CREATE TABLE llm_calls_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER,
    call_purpose TEXT NOT NULL,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT,
    output_json TEXT,
    validation_result TEXT,
    retry_count INTEGER DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    failure_reason TEXT,
    fallback_used INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
"""

_LLM_CALLS_COLUMNS = (
    "id, training_id, call_purpose, prompt_name, prompt_version, model, input_text, output_text, "
    "output_json, validation_result, retry_count, latency_ms, tokens_in, tokens_out, failure_reason, "
    "fallback_used, created_at"
)

_SOURCES_DDL = """
CREATE TABLE sources_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('ai_generated', 'user_upload', 'user_paste', 'web_url')),
    title TEXT NOT NULL,
    origin TEXT,
    origin_url TEXT,
    fetched_at DATETIME,
    snapshot_text TEXT,
    org_id INTEGER,
    scope TEXT DEFAULT 'personal' CHECK (scope IN ('org_shared', 'personal')),
    enabled INTEGER DEFAULT 1,
    checksum TEXT,
    parse_status TEXT DEFAULT 'pending' CHECK (parse_status IN ('pending', 'ok', 'failed', 'unsupported')),
    parse_error TEXT,
    imported_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
"""

_SOURCES_COLUMNS = (
    "id, training_id, type, title, origin, origin_url, fetched_at, snapshot_text, org_id, "
    "scope, checksum, parse_status, parse_error, imported_at"
)

_TRAINING_ITEMS_DDL = """
CREATE TABLE training_items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    item_key TEXT,
    item_type TEXT CHECK (item_type IN ('memory', 'comprehension', 'practice', 'prerequisite')),
    difficulty_tier INTEGER,
    difficulty_basis TEXT,
    knowledge_point TEXT,
    source_chunk_ids TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'practiced', 'passed', 'failed')),
    mastered_at DATETIME,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (stage_id) REFERENCES path_stages(id)
)
"""


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        return ""
    return str(row["sql"] or "")


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row["name"]) for row in rows}


def _rebuild_trainings(conn: sqlite3.Connection) -> None:
    """重建 trainings（补目标字段 / 新状态值）。

    只搬运**新旧表都有的列**——老库可能比当前 DDL 少列（真实事故来源），
    缺的列让新表的默认值兜住，而不是让迁移直接失败。
    """
    old_columns = _column_names(conn, "trainings")
    target_columns = [name.strip() for name in _TRAININGS_COLUMNS.split(",")]
    shared = [name for name in target_columns if name in old_columns]
    conn.execute("ALTER TABLE trainings RENAME TO trainings_old")
    conn.execute(_TRAININGS_DDL)
    conn.execute(
        f"INSERT INTO trainings_new ({', '.join(shared)}) "
        f"SELECT {', '.join(shared)} FROM trainings_old"
    )
    conn.execute("DROP TABLE trainings_old")
    conn.execute("ALTER TABLE trainings_new RENAME TO trainings")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trainings_last_active_at ON trainings(last_active_at)"
    )
    logger.info("migrate: rebuilt trainings (goal fields + new statuses)")


def _rebuild_llm_calls(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE llm_calls RENAME TO llm_calls_old")
    conn.execute(_LLM_CALLS_DDL)
    conn.execute(
        f"INSERT INTO llm_calls_new ({_LLM_CALLS_COLUMNS}) SELECT {_LLM_CALLS_COLUMNS} FROM llm_calls_old"
    )
    conn.execute("DROP TABLE llm_calls_old")
    conn.execute("ALTER TABLE llm_calls_new RENAME TO llm_calls")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_purpose ON llm_calls(call_purpose)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_prompt_version ON llm_calls(prompt_name, prompt_version)"
    )
    logger.info("migrate: rebuilt llm_calls (goal_clarification purpose)")


def _rebuild_sources(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE sources RENAME TO sources_old")
    conn.execute(_SOURCES_DDL)
    conn.execute(
        f"INSERT INTO sources_new ({_SOURCES_COLUMNS}) SELECT {_SOURCES_COLUMNS} FROM sources_old"
    )
    conn.execute("DROP TABLE sources_old")
    conn.execute("ALTER TABLE sources_new RENAME TO sources")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_training ON sources(training_id)")
    logger.info("migrate: rebuilt sources (added enabled flag)")


_PRACTICE_ATTEMPTS_DDL = """
CREATE TABLE practice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    plan_id INTEGER,
    round_index INTEGER,
    result TEXT NOT NULL CHECK (result IN ('pass', 'fail')),
    answer_text TEXT,
    score REAL,
    point_results TEXT,
    mistake_reasons TEXT,
    source TEXT DEFAULT 'self' CHECK (source IN ('self', 'quiz', 'llm', 'rule')),
    note TEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
"""

_PRACTICE_ATTEMPTS_COLUMNS = (
    "id, training_id, item_key, plan_id, round_index, result, answer_text, "
    "score, point_results, mistake_reasons, source, note, created_at"
)


def _rebuild_practice_attempts(conn: sqlite3.Connection) -> None:
    """放宽 ``source`` 枚举：新增 ``rule``（客观题确定性判分，change grading-consistency 延伸）。

    只复制新旧表共有的列——老库若缺后期补的列（score/answer_text 等），由
    ``_add_missing_columns`` 先补齐后再走到这里。
    """
    conn.execute("ALTER TABLE practice_attempts RENAME TO practice_attempts_old")
    conn.execute(_PRACTICE_ATTEMPTS_DDL)
    shared = [
        name for name in _PRACTICE_ATTEMPTS_COLUMNS.replace("\n", " ").split(", ")
        if name in _column_names(conn, "practice_attempts_old")
    ]
    conn.execute(
        f"INSERT INTO practice_attempts ({', '.join(shared)}) "
        f"SELECT {', '.join(shared)} FROM practice_attempts_old"
    )
    conn.execute("DROP TABLE practice_attempts_old")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_attempts_item ON practice_attempts(training_id, item_key, id)"
    )
    logger.info("migrate: rebuilt practice_attempts (source enum + rule)")


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> list[str]:
    """给已有表补列（``ALTER TABLE ADD COLUMN`` 是轻量迁移，不用重建表）。

    返回实际新增的列名。SQLite 允许 ADD COLUMN，只要新列不带 CHECK、
    也不依赖别的列做默认值。
    """
    existing = _column_names(conn, table)
    if not existing:
        return []
    added: list[str] = []
    for name, ddl in columns.items():
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        added.append(name)
    return added


#: plan_items 的题目/作答列（系统出题、用户作答、系统判分）
_PLAN_ITEM_QUESTION_COLUMNS: dict[str, str] = {
    "question": "TEXT",
    "reference_answer": "TEXT",
    "answer_text": "TEXT",
    "verdict": "TEXT",
    "graded_by": "TEXT",
    "graded_at": "DATETIME",
    # 客观题分流：题型与选项随题固化（2026-11-15，choice/fill 零 LLM 判分的数据基础）
    "question_type": "TEXT",
    "options": "TEXT",
}


#: 判分相关列（change learner-memory-and-grading 任务 1.1 / 1.3 / 1.4；
#: plan_items.points 见 2026-10-26 日常训练要点接线）
_GRADING_COLUMNS: dict[str, dict[str, str]] = {
    "question_bank": {"question_type": "TEXT DEFAULT 'qa'", "options": "TEXT"},
    "practice_attempts": {
        "score": "REAL",
        "point_results": "TEXT",
        "mistake_reasons": "TEXT",
        "answer_text": "TEXT",
    },
    "assessment_items": {"question_type": "TEXT DEFAULT 'qa'", "score": "REAL"},
    "plan_items": {"points": "TEXT"},
}

#: 账户/组织列（change personal-auth-tests 随附 schema 对齐；
#: trainings.org_id/owner_user_id 由个人账户功能引入，sources.department_id 由部门资料引入）
_ACCOUNT_COLUMNS: dict[str, dict[str, str]] = {
    "trainings": {"org_id": "INTEGER", "owner_user_id": "INTEGER"},
    "sources": {"department_id": "INTEGER"},
}

_QUESTION_POINTS_DDL = """
CREATE TABLE IF NOT EXISTS question_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    point_id TEXT NOT NULL,
    point_text TEXT NOT NULL,
    weight REAL DEFAULT 1,
    is_required INTEGER DEFAULT 0,
    ordinal INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE (training_id, item_key, point_id),
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
"""


def _ensure_question_points(conn: sqlite3.Connection) -> bool:
    """建 ``question_points``（题目要点清单）表。返回是否新建。"""
    if _column_names(conn, "question_points"):
        return False
    conn.execute(_QUESTION_POINTS_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_question_points_item "
        "ON question_points(training_id, item_key, ordinal)"
    )
    return True


_GRADING_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS grading_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    output_json TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
)
"""


def _ensure_grading_cache_table(conn: sqlite3.Connection) -> bool:
    """建 ``grading_cache``（主观判分结果缓存）表。返回是否新建。"""
    if _column_names(conn, "grading_cache"):
        return False
    conn.execute(_GRADING_CACHE_DDL)
    return True


_MEMORY_DDL: dict[str, str] = {
    "mistake_analysis": """
CREATE TABLE IF NOT EXISTS mistake_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    attempt_id INTEGER,
    analysis_text TEXT NOT NULL,
    prompt_name TEXT,
    prompt_version TEXT,
    model TEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
""",
    "app_settings": """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME
)
""",
    "explanations": """
CREATE TABLE IF NOT EXISTS explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    explanation_text TEXT NOT NULL,
    source_refs TEXT,
    prompt_name TEXT,
    prompt_version TEXT,
    model TEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
)
""",
}


def _ensure_memory_tables(conn: sqlite3.Connection) -> list[str]:
    """建记忆模块的两张表（mistake_analysis / app_settings）。返回新建的表名。"""
    created: list[str] = []
    for table, ddl in _MEMORY_DDL.items():
        if _column_names(conn, table):
            continue
        conn.execute(ddl)
        created.append(table)
    if "mistake_analysis" in created:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mistake_analysis_item "
            "ON mistake_analysis(training_id, item_key, id)"
        )
    if "explanations" in created:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_explanations_item "
            "ON explanations(training_id, item_key, id)"
        )
    return created


def _rebuild_training_items(conn: sqlite3.Connection) -> None:
    """给训练项补上稳定题目键 ``item_key`` 与 ``practiced`` 状态。

    ``item_key`` 是题库与计划表引用的目标（见 change ``training-plan-and-daily-view`` 的 design D7）：
    训练项自身的主键在路径重生成时会变，因此必须有跨重生成稳定的键。
    """
    has_mastered = "mastered_at" in _column_names(conn, "training_items")
    mastered_column = "i.mastered_at" if has_mastered else "NULL AS mastered_at"
    rows = conn.execute(
        f"""
        SELECT i.id, i.stage_id, i.ordinal, i.title, i.item_type, i.difficulty_tier,
               i.difficulty_basis, i.knowledge_point, i.source_chunk_ids, i.status,
               {mastered_column}, i.created_at,
               tp.training_id AS training_id
        FROM training_items i
        JOIN path_stages s ON s.id = i.stage_id
        JOIN training_paths tp ON tp.id = s.path_id
        """
    ).fetchall()

    payload = [
        (
            row["id"],
            row["stage_id"],
            row["ordinal"],
            row["title"],
            item_key_for(int(row["training_id"]), row["knowledge_point"], row["title"]),
            row["item_type"],
            row["difficulty_tier"],
            row["difficulty_basis"],
            row["knowledge_point"],
            row["source_chunk_ids"],
            row["status"],
            row["mastered_at"],
            row["created_at"],
        )
        for row in rows
    ]

    conn.execute("ALTER TABLE training_items RENAME TO training_items_old")
    conn.execute(_TRAINING_ITEMS_DDL)
    conn.executemany(
        "INSERT INTO training_items_new (id, stage_id, ordinal, title, item_key, item_type, "
        "difficulty_tier, difficulty_basis, knowledge_point, source_chunk_ids, status, mastered_at, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        payload,
    )
    conn.execute("DROP TABLE training_items_old")
    conn.execute("ALTER TABLE training_items_new RENAME TO training_items")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_items_stage ON training_items(stage_id, ordinal)"
    )
    logger.info("migrate: rebuilt training_items (item_key + practiced status)")


def migrate(conn: sqlite3.Connection) -> list[str]:
    """对既有数据库执行迁移，返回执行过的迁移名列表。"""
    applied: list[str] = []

    columns = _column_names(conn, "trainings")
    trainings_sql = _table_sql(conn, "trainings")
    needs_trainings = bool(columns) and (
        "goal_json" not in columns or "'completed'" not in trainings_sql
    )
    llm_sql = _table_sql(conn, "llm_calls")
    # 去掉 call_purpose 的 CHECK：用途列表是应用层知识，每加一个用途就重建一次表不值得
    needs_llm_calls = bool(llm_sql) and "call_purpose TEXT NOT NULL CHECK" in llm_sql

    source_columns = _column_names(conn, "sources")
    needs_sources = bool(source_columns) and "enabled" not in source_columns

    item_columns = _column_names(conn, "training_items")
    item_sql = _table_sql(conn, "training_items")
    needs_items = bool(item_columns) and (
        "item_key" not in item_columns
        or "mastered_at" not in item_columns
        or "'practiced'" not in item_sql
    )
    plan_columns = _column_names(conn, "plan_items")
    needs_plan_questions = bool(plan_columns) and (
        "question" not in plan_columns or "question_type" not in plan_columns
    )

    grading_columns = {
        table: cols for table, cols in _GRADING_COLUMNS.items() if _column_names(conn, table)
    }
    needs_grading = any(
        set(cols) - _column_names(conn, table) for table, cols in grading_columns.items()
    ) or not _column_names(conn, "question_points")

    needs_memory = any(not _column_names(conn, table) for table in _MEMORY_DDL)

    needs_grading_cache = not _column_names(conn, "grading_cache")

    practice_sql = _table_sql(conn, "practice_attempts")
    needs_practice_source = bool(practice_sql) and "source IN ('self', 'quiz', 'llm')" in practice_sql

    account_columns = {
        table: cols for table, cols in _ACCOUNT_COLUMNS.items() if _column_names(conn, table)
    }
    needs_account = any(
        set(cols) - _column_names(conn, table) for table, cols in account_columns.items()
    )

    if not (
        needs_trainings
        or needs_llm_calls
        or needs_sources
        or needs_items
        or needs_plan_questions
        or needs_grading
        or needs_memory
        or needs_account
        or needs_grading_cache
        or needs_practice_source
    ):
        return applied

    # 两处必须处理：
    # 1) 重建表期间关闭外键——关闭时 ALTER TABLE RENAME 不会改写其他表的 REFERENCES，
    #    子表仍指向 "trainings"，新表改名回来后外键关系自动恢复；否则 DROP 旧表会触发约束失败。
    # 2) 关闭 sqlite3 的隐式事务管理——默认 isolation_level 会在 DDL 前隐式提交，
    #    一旦中途失败会留下半迁移状态。这里改为自动提交并用显式 BEGIN/COMMIT 保证原子性。
    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        # legacy_alter_table=ON 是关键：否则 ALTER TABLE RENAME 仍会改写其他表的
        # REFERENCES 子句，导致子表外键指向 "trainings_old" 这类已删除的表。
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            if needs_trainings:
                _rebuild_trainings(conn)
                applied.append("trainings:goal_fields")
            if needs_llm_calls:
                _rebuild_llm_calls(conn)
                applied.append("llm_calls:goal_clarification")
            if needs_sources:
                _rebuild_sources(conn)
                applied.append("sources:enabled_flag")
            if needs_items:
                _rebuild_training_items(conn)
                applied.append("training_items:item_key+mastered_at")
            if needs_plan_questions:
                added = _add_missing_columns(conn, "plan_items", _PLAN_ITEM_QUESTION_COLUMNS)
                if added:
                    applied.append("plan_items:question_columns")
            if needs_grading:
                for table, cols in grading_columns.items():
                    added = _add_missing_columns(conn, table, cols)
                    if added:
                        applied.append(f"{table}:grading_columns")
                if _ensure_question_points(conn):
                    applied.append("question_points:new_table")
            if needs_memory:
                for table in _ensure_memory_tables(conn):
                    applied.append(f"{table}:new_table")
            if needs_grading_cache:
                if _ensure_grading_cache_table(conn):
                    applied.append("grading_cache:new_table")
            if needs_practice_source:
                _rebuild_practice_attempts(conn)
                applied.append("practice_attempts:source_rule")
            if needs_account:
                for table, cols in account_columns.items():
                    added = _add_missing_columns(conn, table, cols)
                    if added:
                        applied.append(f"{table}:account_columns")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("migrate: rolled back after failure")
            raise
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            logger.warning("migrate: foreign key check reported %d issue(s)", len(violations))
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = previous_isolation

    return applied


__all__ = ["migrate"]
