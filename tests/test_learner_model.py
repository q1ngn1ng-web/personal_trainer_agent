"""分层学习者记忆测试（change: layered-learner-memory）。

核心守卫：①掌握度递推与衰减的纯函数数学；②活跃误解=最近一次判分的投影；
③**增量更新与全量重放必然收敛**（单一事实源性质）；④record_attempt 集成（派生层不阻塞事实）；
⑤读时衰减与 weak 标记；⑥只读 API 契约。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.learner import (  # noqa: E402
    MASTERY_K,
    decay_mastery,
    misconceptions_from_detail,
    update_mastery,
)
from src.db.sqlite import init_db  # noqa: E402
from src.services import attempt_service, learner_service  # noqa: E402


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _point_results(verdicts: dict[str, tuple[str, bool]], texts: dict[str, str]) -> str:
    """构造 grading-rubric-hardening 之后的 dict 格式 point_results。"""
    detail = [
        {
            "point_id": pid,
            "text": texts[pid],
            "verdict": verdict,
            "weight": 1.0,
            "required": required,
            "evidence": "",
            "evidence_ok": None,
        }
        for pid, (verdict, required) in verdicts.items()
    ]
    return json.dumps(
        {"coverage": 0.5, "correctness": 1.0, "missing": [], "incorrect": [], "required_missing": [], "detail": detail},
        ensure_ascii=False,
    )


class TestPureFunctions(unittest.TestCase):
    def test_mastery_recursion(self) -> None:
        first = update_mastery(None, 1.0)
        self.assertAlmostEqual(first, 0.5 + MASTERY_K * 0.5)  # 0.675
        second = update_mastery(first, 1.0)
        self.assertAlmostEqual(second, 0.78875, places=4)
        failed = update_mastery(second, 0.0)
        self.assertAlmostEqual(failed, 0.5127, places=3)  # 一次 fail 立刻回落
        self.assertAlmostEqual(update_mastery(0.99, 1.0), 0.9935, places=6)

    def test_decay_half_life(self) -> None:
        self.assertAlmostEqual(decay_mastery(0.8, 30.0), 0.4, places=6)
        self.assertAlmostEqual(decay_mastery(0.8, 0.0), 0.8)
        self.assertAlmostEqual(decay_mastery(0.8, -5.0), 0.8)  # 负天数按 0
        self.assertAlmostEqual(decay_mastery(1.0, 60.0), 0.25, places=6)

    def test_misconceptions_projection(self) -> None:
        pr = {
            "detail": [
                {"point_id": "p1", "text": "RDB 是快照", "verdict": "wrong", "required": True},
                {"point_id": "p2", "text": "必答要点", "verdict": "missing", "required": True},
                {"point_id": "p3", "text": "普通缺失", "verdict": "missing", "required": False},
                {"point_id": "p4", "text": "答对的", "verdict": "hit", "required": True},
            ]
        }
        entries = misconceptions_from_detail(pr)
        self.assertEqual(
            [(e["point_id"], e["reason"]) for e in entries],
            [("p1", "concept_confusion"), ("p2", "key_omission")],  # 普通缺失与答对不进清单
        )
        self.assertEqual(misconceptions_from_detail(None), [])
        self.assertEqual(misconceptions_from_detail({"detail": []}), [])


class TestRecordAttemptIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "learner.db")
        init_db()
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now_iso(),),
        )
        conn.commit()
        self._training_id = int(conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        conn.execute(
            "INSERT INTO question_bank (training_id, item_key, knowledge_point, question_text, "
            "answer_text, banked_at, status) VALUES (?, 'learn00000001', 'RDB 持久化', "
            "'RDB 是什么？', '快照', ?, 'active')",
            (self._training_id, _now_iso()),
        )
        conn.commit()
        conn.close()
        self._texts = {"p1": "RDB 是快照", "p2": "fork 返回进程 id"}

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _row(self, item_key: str = "learn00000001") -> sqlite3.Row:
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM learner_knowledge WHERE training_id = ? AND item_key = ?",
            (self._training_id, item_key),
        ).fetchone()
        conn.close()
        return row

    def test_graded_attempt_updates_model_and_misconceptions(self) -> None:
        attempt_service.record_attempt(
            self._training_id,
            "learn00000001",
            "fail",
            score=0.4,
            point_results=_point_results(
                {"p1": ("wrong", True), "p2": ("missing", False)}, self._texts
            ),
            source="llm",
        )
        row = self._row()
        self.assertAlmostEqual(row["mastery"], 0.5 + MASTERY_K * (0.4 - 0.5), places=4)
        self.assertEqual(row["knowledge_point"], "RDB 持久化")  # 从题库解析
        self.assertEqual(row["attempts_count"], 1)
        self.assertEqual(row["passes_count"], 0)
        entries = json.loads(row["misconceptions"])
        self.assertEqual([e["point_id"] for e in entries], ["p1"])  # p2 非必答缺失不进清单
        self.assertEqual(entries[0]["reason"], "concept_confusion")

        attempt_service.record_attempt(
            self._training_id, "learn00000001", "pass", score=1.0, source="llm"
        )
        row = self._row()
        self.assertAlmostEqual(row["mastery"], update_mastery(update_mastery(0.5, 0.4), 1.0), places=6)
        self.assertEqual(row["passes_count"], 1)

    def test_quiz_attempt_without_detail_keeps_misconceptions(self) -> None:
        attempt_service.record_attempt(
            self._training_id,
            "learn00000001",
            "fail",
            point_results=_point_results({"p1": ("wrong", True)}, self._texts),
            source="llm",
        )
        attempt_service.record_attempt(
            self._training_id, "learn00000001", "fail", source="quiz", note="测验 #1"
        )
        row = self._row()
        self.assertEqual(row["attempts_count"], 2)
        self.assertAlmostEqual(row["mastery"], update_mastery(update_mastery(0.5, 0.0), 0.0), places=4)
        self.assertEqual(len(json.loads(row["misconceptions"])), 1)  # 无明细→清单保持

    def test_rebuild_converges_with_incremental(self) -> None:
        """单一事实源守卫：全量重放 == 增量更新。"""
        attempt_service.record_attempt(
            self._training_id,
            "learn00000001",
            "fail",
            score=0.3,
            point_results=_point_results({"p1": ("wrong", True), "p2": ("hit", False)}, self._texts),
            source="llm",
        )
        attempt_service.record_attempt(
            self._training_id,
            "learn00000001",
            "fail",
            score=0.5,
            point_results=_point_results({"p1": ("missing", True)}, self._texts),
            source="llm",
        )
        attempt_service.record_attempt(
            self._training_id, "learn00000001", "pass", score=0.9, source="quiz"
        )
        before = dict(self._row())

        result = learner_service.rebuild(self._training_id)
        self.assertEqual(result["replayed_attempts"], 3)
        after = self._row()
        for column in ("mastery", "misconceptions", "attempts_count", "passes_count"):
            self.assertEqual(
                before[column],
                after[column],
                f"增量与重放在 {column} 上必须收敛",
            )


class TestGetLearnerModel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "decay.db")
        init_db()
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now_iso(),),
        )
        conn.commit()
        self._training_id = int(conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        conn.execute(
            "INSERT INTO learner_knowledge (training_id, item_key, knowledge_point, mastery, "
            "misconceptions, attempts_count, passes_count, last_seen_at, updated_at) "
            "VALUES (?, 'old0000000001', '旧知识点', 0.8, ?, 5, 5, ?, ?), "
            "(?, 'new0000000001', '新知识点', 0.9, '[]', 3, 2, ?, ?)",
            (
                self._training_id,
                json.dumps([{"point_id": "p1", "text": "RDB 是快照", "reason": "concept_confusion"}]),
                (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds"),
                _now_iso(),
                self._training_id,
                datetime.now().isoformat(timespec="seconds"),
                _now_iso(),
            ),
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_decay_weak_sort_and_labels(self) -> None:
        rows = learner_service.get_learner_model(self._training_id)
        self.assertEqual(rows[0]["item_key"], "old0000000001")  # decayed 升序，最弱在前
        self.assertAlmostEqual(rows[0]["decayed_mastery"], 0.8 * 0.5 ** (40 / 30), places=3)
        self.assertTrue(rows[0]["weak"])
        self.assertFalse(rows[1]["weak"])
        self.assertEqual(rows[0]["misconceptions"][0]["reason_label"], "概念混淆")  # 中文标签


class TestEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        self._old_auth = os.environ.get("TRAINER_AUTH")
        os.environ["TRAINER_AUTH"] = "0"
        init_db()
        conn = sqlite3.connect(os.environ["DB_PATH"])
        conn.execute(
            "INSERT INTO trainings (topic, status, created_at) VALUES ('Redis', 'active', ?)",
            (_now_iso(),),
        )
        conn.commit()
        self._training_id = int(conn.execute("SELECT MAX(id) FROM trainings").fetchone()[0])
        conn.execute(
            "INSERT INTO practice_attempts (training_id, item_key, round_index, result, source, "
            "score, point_results, created_at) VALUES (?, 'api0000000001', 1, 'fail', 'llm', 0.4, ?, ?)",
            (
                self._training_id,
                _point_results({"p1": ("wrong", True)}, {"p1": "RDB 是快照"}),
                _now_iso(),
            ),
        )
        conn.commit()
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

    def test_get_and_rebuild(self) -> None:
        from fastapi.testclient import TestClient

        from src.api.app import app

        client = TestClient(app)
        rebuilt = client.post(f"/api/trainings/{self._training_id}/learner-model/rebuild")
        self.assertEqual(rebuilt.status_code, 200)
        resp = client.get(f"/api/trainings/{self._training_id}/learner-model")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["weak_count"], 1)
        item = payload["items"][0]
        self.assertEqual(item["knowledge_point"], "api0000000001")  # 无题库→退回 item_key
        self.assertEqual(item["misconceptions"][0]["reason_label"], "概念混淆")

        rebuilt = client.post(f"/api/trainings/{self._training_id}/learner-model/rebuild")
        self.assertEqual(rebuilt.status_code, 200)
        self.assertEqual(rebuilt.json()["replayed_attempts"], 1)
        after = client.get(f"/api/trainings/{self._training_id}/learner-model")
        self.assertEqual(after.json()["items"][0]["mastery"], item["mastery"])  # 幂等收敛

        missing = client.get("/api/trainings/999999/learner-model")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
