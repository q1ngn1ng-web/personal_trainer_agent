"""个人版认证与会话最小测试集（change: personal-auth-tests）。

范围按用户决策（2026-10-29）：只覆盖个人版路径——注册/登录/会话生命周期/权限纯函数矩阵/
API 访问控制（401/403 与越权）。组织与作业（org/assignment）不在本测试范围。

背景：auth_service docstring 声称「三条硬约束都有单测」，但 tests/ 此前零覆盖。
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db.sqlite import init_db  # noqa: E402
from src.core import permissions  # noqa: E402
from src.services import auth_service  # noqa: E402


def _viewer_of(result: dict) -> permissions.Viewer:
    return result["viewer"]


class TestRegisterAndLogin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "auth.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_register_creates_user_and_session(self) -> None:
        result = auth_service.register_account("a@example.com", "password8", "用户A")
        viewer = _viewer_of(result)
        self.assertGreater(int(viewer.user_id), 0)
        self.assertEqual(viewer.org_id, 1)  # 默认组织

        import sqlite3

        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT token_hash, revoked_at FROM sessions WHERE user_id = ?", (viewer.user_id,)
        ).fetchone()
        conn.close()
        expected_hash = hashlib.sha256(result["session"]["token"].encode()).hexdigest()
        self.assertEqual(row["token_hash"], expected_hash)  # 令牌只存哈希
        self.assertIsNone(row["revoked_at"])

    def test_register_rejects_bad_input_and_duplicate(self) -> None:
        with self.assertRaises(ValueError):
            auth_service.register_account("not-an-email", "password8", "x")
        with self.assertRaises(ValueError):
            auth_service.register_account("b@example.com", "short", "x")
        auth_service.register_account("b@example.com", "password8", "B")
        with self.assertRaises(ValueError):
            auth_service.register_account("b@example.com", "password9", "B2")

    def test_login_password_and_anti_enumeration(self) -> None:
        auth_service.register_account("c@example.com", "password8", "C")
        ok = auth_service.login_password("c@example.com", "password8")
        self.assertGreater(int(_viewer_of(ok).user_id), 0)

        for email, password in (("c@example.com", "wrong-pass"), ("ghost@example.com", "password8")):
            with self.assertRaises(PermissionError) as ctx:
                auth_service.login_password(email, password)
            # 统一文案：不暴露「用户是否存在」
            self.assertEqual(str(ctx.exception), "邮箱或密码不正确")

    def test_password_hash_format(self) -> None:
        stored = auth_service._hash_password("password8")
        self.assertTrue(stored.startswith("pbkdf2$"))
        self.assertTrue(auth_service._verify_password("password8", stored))
        self.assertFalse(auth_service._verify_password("wrong-pass", stored))


class TestSessionLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "session.db")
        init_db()
        self._result = auth_service.register_account("d@example.com", "password8", "D")
        self._token = self._result["session"]["token"]
        self._user_id = int(_viewer_of(self._result).user_id)

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_viewer_from_session_resolves_and_sliding_renews(self) -> None:
        viewer = auth_service.viewer_from_session(self._token)
        self.assertIsNotNone(viewer)
        self.assertEqual(int(viewer.user_id), self._user_id)

        import sqlite3

        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT expires_at, last_seen_at FROM sessions WHERE user_id = ?", (self._user_id,)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row["last_seen_at"])  # 滑动续期已写 last_seen_at

    def test_revoked_session_is_rejected(self) -> None:
        auth_service.revoke_session(self._token)
        self.assertIsNone(auth_service.viewer_from_session(self._token))

    def test_expired_session_is_rejected(self) -> None:
        import sqlite3

        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "UPDATE sessions SET expires_at = '2000-01-01T00:00:00' WHERE user_id = ?",
            (self._user_id,),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(auth_service.viewer_from_session(self._token))

    def test_logout_revokes(self) -> None:
        # revoke_session 即登出语义；再次解析必须为 None
        auth_service.revoke_session(self._token)
        self.assertIsNone(auth_service.viewer_from_session(self._token))


class TestPermissionsMatrix(unittest.TestCase):
    def test_employee_self_actions_only(self) -> None:
        self.assertTrue(permissions.can("employee", "train_self"))
        self.assertTrue(permissions.can("employee", "submit_signal"))
        self.assertFalse(permissions.can("employee", "publish_assignment"))
        self.assertFalse(permissions.can("employee", "manage_members"))

    def test_superset_chain(self) -> None:
        # DEPT_MANAGER ⊃ EMPLOYEE；ORG_ADMIN ⊃ DEPT_MANAGER
        self.assertTrue(permissions.can("dept_manager", "manage_department"))
        self.assertFalse(permissions.can("dept_manager", "manage_org_sources"))
        self.assertTrue(permissions.can("org_admin", "manage_org_sources"))
        self.assertTrue(permissions.can("org_admin", "publish_assignment"))
        self.assertTrue(permissions.can("org_admin", "train_self"))  # 超集链含自用动作

    def test_personal_mode_passes_all(self) -> None:
        # viewer=None（个人版免登录/关闭鉴权）直接放行
        permissions.assert_can(None, "publish_assignment")
        self.assertTrue(permissions.can_view_training(None, {"org_id": 99, "owner_user_id": 7}))

    def test_view_training_rules(self) -> None:
        viewer = permissions.Viewer(user_id=2, org_id=1, role=permissions.Role.EMPLOYEE, department_ids=frozenset({5}))
        self.assertTrue(permissions.can_view_training(viewer, {"org_id": 1, "owner_user_id": 2}))
        self.assertFalse(permissions.can_view_training(viewer, {"org_id": 1, "owner_user_id": 3}))
        self.assertFalse(permissions.can_view_training(viewer, {"org_id": 2, "owner_user_id": 2}))
        self.assertTrue(permissions.can_view_training(viewer, {"org_id": 1, "owner_user_id": None}))  # 组织级训练

    def test_view_source_scopes(self) -> None:
        # 三档可见性（change content-visibility）：private / specific / public
        viewer = permissions.Viewer(user_id=2, org_id=1, role=permissions.Role.EMPLOYEE, department_ids=frozenset({5}))
        self.assertTrue(permissions.can_view_source(viewer, {"scope": "private", "owner_user_id": 2}))
        self.assertFalse(permissions.can_view_source(viewer, {"scope": "private", "owner_user_id": 3}))
        self.assertTrue(permissions.can_view_source(viewer, {"scope": "public", "org_id": 1}))
        self.assertFalse(permissions.can_view_source(viewer, {"scope": "public", "org_id": 2}))
        self.assertTrue(
            permissions.can_view_source(viewer, {"scope": "specific", "owner_user_id": 3}, [2])
        )
        self.assertFalse(
            permissions.can_view_source(viewer, {"scope": "specific", "owner_user_id": 3}, [9])
        )


class TestApiAccessControl(unittest.TestCase):
    """API 层契约：未登录 401、注册发 Cookie、越权 403。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        self._old_auth = os.environ.get("TRAINER_AUTH")
        os.environ["TRAINER_AUTH"] = "1"
        init_db()

        # 断网化 LLM：向导 start 会调澄清模型，无 key + fallback 保证离线确定性
        from src.llm import client as client_module

        self._client_module = client_module
        self._orig_call_api = client_module._call_api

        def _boom(messages, *args, **kwargs):
            raise client_module.LLMError("offline test")

        client_module._call_api = _boom  # type: ignore[assignment]
        self._orig_key = client_module.DEEPSEEK_API_KEY
        client_module.DEEPSEEK_API_KEY = "test-key"

    def tearDown(self) -> None:
        self._client_module._call_api = self._orig_call_api
        self._client_module.DEEPSEEK_API_KEY = self._orig_key
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        if self._old_auth is None:
            os.environ.pop("TRAINER_AUTH", None)
        else:
            os.environ["TRAINER_AUTH"] = self._old_auth
        self._tmp.cleanup()

    def test_401_without_cookie_and_register_sets_cookie(self) -> None:
        from fastapi.testclient import TestClient

        from src.api.app import app

        client = TestClient(app)
        self.assertEqual(client.get("/api/today").status_code, 401)

        reg = client.post(
            "/api/auth/register",
            json={"email": "e@example.com", "password": "password8", "display_name": "E"},
        )
        self.assertEqual(reg.status_code, 200)
        self.assertIn("tc_session", client.cookies)
        self.assertEqual(client.get("/api/me").status_code, 200)

        bad = client.post(
            "/api/auth/login", json={"email": "e@example.com", "password": "wrong-pass"}
        )
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"], "邮箱或密码不正确")

    def test_owner_isolation_between_users(self) -> None:
        from fastapi.testclient import TestClient

        from src.api.app import app

        alice = TestClient(app)
        alice.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "password8", "display_name": "A"},
        )
        start = alice.post("/api/wizard/start", json={"topic": "学习 Redis 持久化"})
        self.assertEqual(start.status_code, 200)
        training_id = int(start.json()["training_id"])

        mallory = TestClient(app)
        mallory.post(
            "/api/auth/register",
            json={"email": "mallory@example.com", "password": "password8", "display_name": "M"},
        )
        resp = mallory.get(f"/api/trainings/{training_id}/path")
        self.assertEqual(resp.status_code, 403)
        resp = mallory.get(f"/api/trainings/{training_id}/sources")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
