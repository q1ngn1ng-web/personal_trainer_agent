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
    call_purpose TEXT NOT NULL CHECK (call_purpose IN ('topic_validation', 'keyword_generation', 'baseline_q', 'baseline_scoring', 'weekly_calibration', 'md_generation', 'pretrain_checklist', 'goal_clarification')),
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

CREATE INDEX IF NOT EXISTS idx_trainings_last_active_at ON trainings(last_active_at);
CREATE INDEX IF NOT EXISTS idx_daily_logs_training_date ON daily_logs(training_id, log_date);
CREATE INDEX IF NOT EXISTS idx_baseline_history_training ON baseline_history(training_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_llm_calls_purpose ON llm_calls(call_purpose);
CREATE INDEX IF NOT EXISTS idx_llm_calls_prompt_version ON llm_calls(prompt_name, prompt_version);
CREATE INDEX IF NOT EXISTS idx_review_archives_training_week ON review_archives(training_id, week_start);
