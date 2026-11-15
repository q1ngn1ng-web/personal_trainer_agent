"""判分细则加固测试（change: grading-rubric-hardening）。

覆盖：证据核验纯函数（归一化）、point_results 构建与快照、schema 强制 evidence、
日常判分端到端落证据与错因（含 list→dict 断链修复的回归证明）、要点编辑服务与 PATCH 契约。
"""
from __future__ import annotations

import json
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
from src.services import answer_service  # noqa: E402
from src.services.grading_service import (  # noqa: E402
    PointSpec,
    build_point_results,
    grade_question,
    normalize_for_evidence,
    verify_evidence,
)


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


class TestVerifyEvidence(unittest.TestCase):
    def test_normalized_substring(self) -> None:
        self.assertTrue(verify_evidence("RDB 是快照，持久化！", "rdb 是快照"))
        self.assertTrue(verify_evidence("一条条执行命令，所以不会抢锁", "所以，不会抢锁。"))

    def test_fabricated_or_empty(self) -> None:
        self.assertFalse(verify_evidence("RDB 是快照", "AOF 是日志"))
        self.assertFalse(verify_evidence("RDB 是快照", ""))
        self.assertFalse(verify_evidence("RDB 是快照", None))

    def test_normalize_strips_all_but_alnum_cjk(self) -> None:
        self.assertEqual(normalize_for_evidence(" A-b，c。D！"), "abcd")


class TestBuildPointResults(unittest.TestCase):
    def _grade(self):
        specs = [
            PointSpec(point_id="p1", text="RDB 是快照", weight=2.0, required=True),
            PointSpec(point_id="p2", text="AOF 是日志", weight=1.0, required=False),
            PointSpec(point_id="p3", text="fork 返回 id", weight=1.0, required=False),
        ]
        return specs, grade_question(
            "qa",
            answer="RDB 是快照",
            points=specs,
            point_verdicts={"p1": "hit", "p2": "wrong", "p3": "missing"},
        )

    def test_snapshot_and_flags(self) -> None:
        specs, grade = self._grade()
        payload = json.loads(
            build_point_results(
                grade,
                text_by_pid={spec.point_id: spec.text for spec in specs},
                evidence_by_pid={"p1": "RDB 是快照", "p2": "不存在的引用"},
                answer_text="RDB 是快照持久化",
            )
        )
        self.assertEqual(
            sorted(payload.keys()),
            ["correctness", "coverage", "detail", "incorrect", "missing", "required_missing"],
        )
        d = {entry["point_id"]: entry for entry in payload["detail"]}
        self.assertEqual(d["p1"]["text"], "RDB 是快照")
        self.assertTrue(d["p1"]["evidence_ok"])  # 真实摘录
        self.assertFalse(d["p2"]["evidence_ok"])  # 编造引用 → 仅标记
        self.assertIsNone(d["p3"]["evidence_ok"])  # missing 不适用
        self.assertEqual(d["p3"]["evidence"], "")

    def test_evidence_never_changes_score(self) -> None:
        _, grade = self._grade()
        with_evidence = json.loads(
            build_point_results(grade, evidence_by_pid={"p1": "编的"}, answer_text="RDB 是快照")
        )
        self.assertEqual(with_evidence["coverage"], grade.coverage)
        self.assertEqual(with_evidence["detail"][0]["verdict"], "hit")  # 判定不因核验失败改


class TestSchemaRequiresEvidence(unittest.TestCase):
    def test_missing_evidence_rejected(self) -> None:
        import jsonschema

        from src.llm.schema import SCHEMA_REGISTRY

        schema = SCHEMA_REGISTRY["quiz_grade"]
        bad = {
            "results": [
                {
                    "item_key": "k",
                    "reason": "r",
                    "point_verdicts": [{"point_id": "p1", "verdict": "hit"}],
                }
            ]
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(bad)


class TestDailyGradingStoresEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "rubric.db")
        init_db()
        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._orig_key = client_module.DEEPSEEK_API_KEY

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        self._client.DEEPSEEK_API_KEY = self._orig_key
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _seed(self) -> int:
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now(),),
        )
        training_id = int(conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        points = json.dumps(
            [
                {"point_id": "p1", "text": "RDB 是快照", "weight": 2, "is_required": True},
                {"point_id": "p2", "text": "AOF 是日志", "weight": 1, "is_required": False},
                {"point_id": "p3", "text": "fork 返回进程 id", "weight": 1, "is_required": False},
            ],
            ensure_ascii=False,
        )
        conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, question, question_type, "
            "reference_answer, points, created_at) "
            "VALUES (?, 'rubric0000001', 1, 'train', date('now'), date('now'), date('now'), "
            "'planned', 10, 'RDB/AOF/fork 各是什么？', 'qa', '见要点', ?, ?)",
            (training_id, points, _now()),
        )
        conn.commit()
        plan_id = int(conn.execute("SELECT MAX(id) FROM plan_items").fetchone()[0])
        conn.close()
        return plan_id

    def test_submit_answer_persists_evidence_and_reasons(self) -> None:
        plan_id = self._seed()
        answer = "RDB 是快照持久化，fork 返回进程 id"

        grade_payload = json.dumps(
            {
                "results": [
                    {
                        "item_key": "rubric0000001",
                        "verdict": "pass",
                        "point_verdicts": [
                            {"point_id": "p1", "verdict": "hit", "evidence": "RDB 是快照"},
                            {"point_id": "p2", "verdict": "wrong", "evidence": "AOF 是日志"},
                            {"point_id": "p3", "verdict": "hit", "evidence": "fork 返回进程 id"},
                        ],
                        "reason": "p2 说反",
                    }
                ]
            },
            ensure_ascii=False,
        )
        self._client.DEEPSEEK_API_KEY = "test-key"
        self._client._call_api = lambda *a, **k: (grade_payload, 10, 20)  # type: ignore[assignment]

        outcome = answer_service.submit_answer(plan_id, answer)
        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "fail")  # p2 wrong 拉低 + 模型整体 pass 无权翻案

        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT point_results, mistake_reasons FROM practice_attempts WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
        conn.close()

        payload = json.loads(row["point_results"])
        self.assertIn("detail", payload)  # dict 格式（修复 list 断链）
        detail = {entry["point_id"]: entry for entry in payload["detail"]}
        self.assertTrue(detail["p1"]["evidence_ok"])
        self.assertFalse(detail["p2"]["evidence_ok"])  # 编造引用被核验标记
        self.assertTrue(detail["p3"]["evidence_ok"])
        self.assertEqual(detail["p1"]["text"], "RDB 是快照")  # point_text 快照

        reasons = json.loads(row["mistake_reasons"])  # 错因随作答落库（断链修复的回归证明）
        self.assertEqual(reasons.get("p2"), "concept_confusion")


class TestUpdatePoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "edit.db")
        init_db()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _seed_plan(self, *, with_question: bool = True) -> int:
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now(),),
        )
        training_id = int(conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, question, points, created_at) "
            "VALUES (?, 'edit000000001', 1, 'train', date('now'), date('now'), date('now'), "
            "'planned', 10, ?, ?, ?)",
            (
                training_id,
                "题干" if with_question else None,
                json.dumps([{"point_id": "p1", "text": "旧要点", "weight": 1, "is_required": False}]),
                _now(),
            ),
        )
        conn.commit()
        plan_id = int(conn.execute("SELECT MAX(id) FROM plan_items").fetchone()[0])
        conn.close()
        return plan_id

    def test_edit_before_grading(self) -> None:
        plan_id = self._seed_plan()
        updated = answer_service.update_points(
            plan_id,
            [
                {"text": "新要点一", "weight": 2, "is_required": True},
                {"text": "新要点二", "weight": 1, "is_required": False},
            ],
        )
        self.assertEqual([p["point_id"] for p in updated], ["p1", "p2"])  # 重编号
        conn = sqlite3.connect(os.environ["DB_PATH"])
        stored = json.loads(
            conn.execute("SELECT points FROM plan_items WHERE id = ?", (plan_id,)).fetchone()[0]
        )
        conn.close()
        self.assertEqual(len(stored), 2)
        self.assertTrue(stored[0]["is_required"])

    def test_locked_after_graded_attempt(self) -> None:
        plan_id = self._seed_plan()
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, plan_id, round_index, result, "
            "source, created_at) VALUES ((SELECT training_id FROM plan_items WHERE id=?), "
            "'edit000000001', ?, 1, 'fail', 'llm', ?)",
            (plan_id, plan_id, _now()),
        )
        conn.commit()
        conn.close()
        with self.assertRaises(answer_service.PointsLockedError):
            answer_service.update_points(plan_id, [{"text": "x", "weight": 1, "is_required": False}])

    def test_validation(self) -> None:
        plan_id = self._seed_plan()
        with self.assertRaises(ValueError):
            answer_service.update_points(plan_id, [])
        with self.assertRaises(ValueError):
            answer_service.update_points(plan_id, [{"text": "  ", "weight": 1, "is_required": False}])
        with self.assertRaises(ValueError):
            answer_service.update_points(plan_id, [{"text": "x", "weight": 9, "is_required": False}])
        no_question = self._seed_plan(with_question=False)
        with self.assertRaises(ValueError):
            answer_service.update_points(no_question, [{"text": "x", "weight": 1, "is_required": False}])


class TestPatchEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "patch.db")
        self._old_auth = os.environ.get("TRAINER_AUTH")
        os.environ["TRAINER_AUTH"] = "0"
        init_db()
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now(),),
        )
        conn.execute(
            "INSERT INTO plan_items (training_id, item_key, round_index, kind, due_date, "
            "anchor_date, original_date, status, planned_minutes, question, points, created_at) "
            "VALUES ((SELECT MAX(id) FROM trainings), 'patch000000001', 1, 'train', date('now'), "
            "date('now'), date('now'), 'planned', 10, '题干', ?, ?)",
            (
                json.dumps([{"point_id": "p1", "text": "旧", "weight": 1, "is_required": False}]),
                _now(),
            ),
        )
        conn.commit()
        self._plan_id = int(conn.execute("SELECT MAX(id) FROM plan_items").fetchone()[0])
        conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        if self._old_auth is None:
            os.environ.pop("TRAINER_AUTH", None)
        else:
            os.environ["TRAINER_AUTH"] = self._old_auth
        self._tmp.cleanup()

    def test_patch_contract(self) -> None:
        from fastapi.testclient import TestClient

        from src.api.app import app

        client = TestClient(app)
        ok = client.patch(
            f"/api/plan-items/{self._plan_id}/points",
            json={"points": [{"text": "新要点", "weight": 2, "is_required": True}]},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["points"][0]["point_id"], "p1")

        bad = client.patch(
            f"/api/plan-items/{self._plan_id}/points",
            json={"points": [{"text": "x", "weight": 99, "is_required": False}]},
        )
        self.assertEqual(bad.status_code, 400)

        missing = client.patch("/api/plan-items/999999/points", json={"points": []})
        self.assertEqual(missing.status_code, 404)

        # 判分后锁定 → 409
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, plan_id, round_index, result, "
            "source, created_at) VALUES ((SELECT training_id FROM plan_items WHERE id=?), "
            "'patch000000001', ?, 1, 'fail', 'llm', ?)",
            (self._plan_id, self._plan_id, _now()),
        )
        conn.commit()
        conn.close()
        locked = client.patch(
            f"/api/plan-items/{self._plan_id}/points",
            json={"points": [{"text": "改不动", "weight": 1, "is_required": False}]},
        )
        self.assertEqual(locked.status_code, 409)


if __name__ == "__main__":
    unittest.main()
