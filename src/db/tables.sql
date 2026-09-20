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
