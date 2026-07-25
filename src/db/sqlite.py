from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("src.db.sqlite")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = Path(__file__).with_name("tables.sql")


def _db_path(db_path: str | None = None) -> Path:
    load_dotenv()
    return Path(db_path or os.getenv("DB_PATH", "./data/trainer.db")).expanduser()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection."""
    path = _db_path(db_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create all application tables if they do not exist."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        logger.info("Database initialized: %s", _db_path(db_path))
    finally:
        conn.close()
