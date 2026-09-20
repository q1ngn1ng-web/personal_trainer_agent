CREATE TABLE IF NOT EXISTS trainings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'draft' CHECK (status IN ('created', 'draft', 'pending_confirm', 'confirmed', 'active', 'paused', 'archived', 'failed')),
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
);

CREATE TABLE IF NOT EXISTS daily_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    total_tasks INTEGER DEFAULT 0,
    completed_count INTEGER DEFAULT 0,
    recall_questions_total INTEGER DEFAULT 0,
    recall_questions_correct INTEGER DEFAULT 0,
    recall_success_rate REAL,
    three_reflections TEXT,
    reflection_submitted_at DATETIME,
    created_at DATETIME NOT NULL,
    UNIQUE (training_id, log_date),
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE TABLE IF NOT EXISTS baseline_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    baseline_score REAL NOT NULL,
    dimension_scores TEXT,
    recorded_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE TABLE IF NOT EXISTS llm_calls (
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
);

CREATE TABLE IF NOT EXISTS review_archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    metrics TEXT,
    llm_suggestions TEXT,
    user_action TEXT CHECK (user_action IN ('confirmed', 'skipped')),
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE TABLE IF NOT EXISTS daily_log_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_log_id INTEGER NOT NULL,
    task_type TEXT CHECK (task_type IN ('review', 'new', 'recall')),
    task_ref TEXT,
    completed INTEGER DEFAULT 0,
    completed_at DATETIME,
    is_required INTEGER DEFAULT 1,
    FOREIGN KEY (daily_log_id) REFERENCES daily_logs(id)
);

CREATE TABLE IF NOT EXISTS sources (
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
);

CREATE TABLE IF NOT EXISTS source_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    heading_path TEXT,
    text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

-- 全文索引：用 trigram 分词，中文才能按子串命中（unicode61 会把整句当成一个词）
CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts USING fts5(
    text,
    heading_path,
    content='source_chunks',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS source_chunks_ai AFTER INSERT ON source_chunks BEGIN
    INSERT INTO source_chunks_fts(rowid, text, heading_path)
    VALUES (new.id, new.text, new.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS source_chunks_ad AFTER DELETE ON source_chunks BEGIN
    INSERT INTO source_chunks_fts(source_chunks_fts, rowid, text, heading_path)
    VALUES ('delete', old.id, old.text, old.heading_path);
END;

CREATE TRIGGER IF NOT EXISTS source_chunks_au AFTER UPDATE ON source_chunks BEGIN
    INSERT INTO source_chunks_fts(source_chunks_fts, rowid, text, heading_path)
    VALUES ('delete', old.id, old.text, old.heading_path);
    INSERT INTO source_chunks_fts(rowid, text, heading_path)
    VALUES (new.id, new.text, new.heading_path);
END;

CREATE TABLE IF NOT EXISTS edge_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    knowledge_point TEXT NOT NULL,
    heading_path TEXT,
    difficulty INTEGER NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT,
    answer TEXT,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('pass', 'fail', 'unknown')),
    state TEXT CHECK (state IS NULL OR state IN ('mastered', 'edge', 'unreached')),
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE INDEX IF NOT EXISTS idx_trainings_last_active_at ON trainings(last_active_at);
CREATE INDEX IF NOT EXISTS idx_daily_logs_training_date ON daily_logs(training_id, log_date);
CREATE INDEX IF NOT EXISTS idx_baseline_history_training ON baseline_history(training_id, recorded_at);
CREATE INDEX IF NOT EXISTS yidx_llm_calls_purpose ON llm_calls(call_purpose);
CREATE INDEX IF NOT EXISTS idx_llm_calls_prompt_version ON llm_calls(prompt_name, prompt_version);
CREATE INDEX IF NOT EXISTS idx_review_archives_training_week ON review_archives(training_id, week_start);
CREATE INDEX IF NOT EXISTS idx_sources_training ON sources(training_id);
CREATE INDEX IF NOT EXISTS idx_source_chunks_source ON source_chunks(source_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_edge_assessments_training ON edge_assessments(training_id, knowledge_point);

CREATE TABLE IF NOT EXISTS training_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed', 'superseded')),
    mode TEXT DEFAULT 'mastery' CHECK (mode IN ('coverage', 'mastery')),
    horizon_weeks INTEGER,
    weekly_frequency INTEGER,
    daily_budget_minutes INTEGER,
    budget_minutes INTEGER,
    planned_minutes INTEGER,
    created_at DATETIME NOT NULL,
    confirmed_at DATETIME,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE TABLE IF NOT EXISTS path_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    goal TEXT,
    estimated_minutes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'locked' CHECK (status IN ('locked', 'active', 'completed')),
    FOREIGN KEY (path_id) REFERENCES training_paths(id)
);

CREATE TABLE IF NOT EXISTS training_items (
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
    created_at DATETIME NOT NULL,
    FOREIGN KEY (stage_id) REFERENCES path_stages(id)
);

CREATE INDEX IF NOT EXISTS idx_training_paths_training ON training_paths(training_id, version);
CREATE INDEX IF NOT EXISTS idx_path_stages_path ON path_stages(path_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_training_items_stage ON training_items(stage_id, ordinal);

-- 训练计划：以「到期日 × 训练 × 题目 × 轮次」为一条计划项（ADR-0021）
-- item_key 是稳定题目键，不用训练项的自增主键——路径重生成会换 id（见 design D7）
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    round_index INTEGER NOT NULL,
    kind TEXT DEFAULT 'train' CHECK (kind IN ('train', 'assessment')),
    due_date TEXT NOT NULL,
    anchor_date TEXT NOT NULL,
    original_date TEXT NOT NULL,
    status TEXT DEFAULT 'planned' CHECK (status IN ('planned', 'practiced', 'skipped')),
    planned_minutes INTEGER DEFAULT 0,
    practiced_at DATETIME,
    reason TEXT,
    created_at DATETIME NOT NULL,
    UNIQUE (training_id, item_key, round_index),
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE INDEX IF NOT EXISTS idx_plan_items_due ON plan_items(training_id, due_date);
CREATE INDEX IF NOT EXISTS idx_plan_items_status ON plan_items(status, due_date);

-- 测验题库：练过的题在这里登记，冷却期过后才可被抽题（ADR-0016）
CREATE TABLE IF NOT EXISTS question_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    source_chunk_ids TEXT,
    knowledge_point TEXT,
    item_type TEXT,
    difficulty_tier INTEGER,
    question_text TEXT,
    answer_text TEXT,
    practiced_count INTEGER DEFAULT 0,
    last_practiced_at DATETIME,
    banked_at DATETIME NOT NULL,
    cooldown_until TEXT,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    UNIQUE (training_id, item_key),
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE INDEX IF NOT EXISTS idx_question_bank_drawable ON question_bank(training_id, cooldown_until);

CREATE TABLE IF NOT EXISTS learning_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_id INTEGER,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('too_easy', 'too_hard', 'too_much', 'too_narrow')),
    raw_text TEXT,
    confidence REAL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE TABLE IF NOT EXISTS adjustment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    training_id INTEGER NOT NULL,
    item_id INTEGER,
    signal_type TEXT,
    action TEXT,
    reason TEXT,
    detail TEXT,
    blocked INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (training_id) REFERENCES trainings(id)
);

CREATE INDEX IF NOT EXISTS idx_learning_signals_training ON learning_signals(training_id, created_at);
CREATE INDEX IF NOT EXISTS idx_adjustment_log_training ON adjustment_log(training_id, created_at);
