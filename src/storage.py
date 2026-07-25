# storage.py
"""SQLite 长期记忆"""
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from config import DB_PATH
from models import UserProfile, BaselineResult, TrainingSession


class Storage:
    """负责所有持久化操作"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化表结构"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    theme TEXT NOT NULL,
                    background TEXT NOT NULL,
                    target_level TEXT NOT NULL,
                    daily_time INTEGER NOT NULL,
                    total_weeks INTEGER NOT NULL,
                    application TEXT NOT NULL,
                    baseline_level TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    answers TEXT NOT NULL,
                    pre_training TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            conn.commit()

    def save_session(
        self,
        profile: UserProfile,
        baseline: BaselineResult,
        workspace_path: str
    ) -> str:
        """保存一次训练会话，返回 session_id"""
        session_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO sessions (
                    session_id, theme, background, target_level, daily_time,
                    total_weeks, application, baseline_level, workspace_path,
                    created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                profile.theme,
                profile.background,
                profile.target_level,
                profile.daily_time,
                profile.total_weeks,
                profile.application,
                baseline.level,
                workspace_path,
                now,
                now,
                "active"
            ))
            conn.execute("""
                INSERT INTO baselines (
                    session_id, level, score, answers, pre_training, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                baseline.level,
                baseline.score,
                "|".join(baseline.answers),
                "|".join(baseline.pre_training_needed),
                baseline.diagnosis_notes,
                now
            ))
            conn.commit()
        return session_id

    def get_latest_session(self, theme: Optional[str] = None) -> Optional[TrainingSession]:
        """获取最近一次会话（可按主题过滤）"""
        with self._get_conn() as conn:
            if theme:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE theme = ? ORDER BY created_at DESC LIMIT 1",
                    (theme,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sessions ORDER BY created_at DESC LIMIT 1"
                ).fetchone()

            if not row:
                return None

            return TrainingSession(
                session_id=row["session_id"],
                theme=row["theme"],
                background=row["background"],
                target_level=row["target_level"],
                daily_time=row["daily_time"],
                total_weeks=row["total_weeks"],
                application=row["application"],
                baseline_level=row["baseline_level"],
                workspace_path=row["workspace_path"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                status=row["status"]
            )

    def list_sessions(self) -> List[TrainingSession]:
        """列出所有会话"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                result.append(TrainingSession(
                    session_id=row["session_id"],
                    theme=row["theme"],
                    background=row["background"],
                    target_level=row["target_level"],
                    daily_time=row["daily_time"],
                    total_weeks=row["total_weeks"],
                    application=row["application"],
                    baseline_level=row["baseline_level"],
                    workspace_path=row["workspace_path"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    status=row["status"]
                ))
            return result