"""schema 守卫测试：init_db 必须产出完整可运行的库（含账户/组织 10 表），全新库可注册登录。

背景：users/sessions/login_tokens/organizations 等 10 张账户组织表此前只存在于生产库，
仓库 tables.sql 缺 DDL，新环境 init-db 后注册登录直接不可用（change: account-schema-in-repo）。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db.sqlite import init_db  # noqa: E402

#: 全部普通表（不含 FTS5 虚表与其影子表、sqlite_sequence）
EXPECTED_TABLES = {
    # 十要素一代
    "trainings", "daily_logs", "baseline_history", "review_archives", "daily_log_tasks",
    # 共享基建
    "llm_calls", "app_settings",
    # 创建链
    "sources", "source_chunks", "edge_assessments", "training_paths", "path_stages", "training_items",
    # 执行链
    "plan_items", "question_bank", "question_points", "practice_attempts", "mistake_analysis",
    # 收尾链
    "explanations", "assessments", "assessment_items", "learning_signals", "adjustment_log",
    # 账户 / 组织 / 作业（account-schema-in-repo 补入库的 10 张）
    "users", "sessions", "login_tokens", "organizations", "departments", "memberships",
    "roster_entries", "assignments", "assignment_targets", "assignment_receipts",
}


class TestDbSchema(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "schema.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _table_names(self) -> set[str]:
        conn = sqlite3.connect(os.environ["DB_PATH"])
        try:
            return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()

    def test_init_db_creates_all_tables(self) -> None:
        missing = EXPECTED_TABLES - self._table_names()
        self.assertEqual(missing, set(), f"init_db 缺表：{sorted(missing)}")

    def test_fresh_db_supports_register_and_login(self) -> None:
        from src.services import auth_service

        result = auth_service.register_account("fresh@example.com", "password8", "新人")
        viewer = result["viewer"]
        self.assertGreater(int(viewer.user_id), 0)

        token = result["session"]["token"]
        resolved = auth_service.viewer_from_session(token)
        self.assertIsNotNone(resolved)
        self.assertEqual(int(resolved.user_id), int(viewer.user_id))

        again = auth_service.login_password("fresh@example.com", "password8")
        self.assertEqual(int(again["viewer"].user_id), int(viewer.user_id))

        with self.assertRaises(PermissionError):
            auth_service.login_password("fresh@example.com", "wrong-pass")


if __name__ == "__main__":
    unittest.main()
