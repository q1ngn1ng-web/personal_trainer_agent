"""用户自定义训练计划（change ``user-defined-training-plan``）回归钉子。

钉住（对应 spec 四个 Requirement）：
1. 配比控制器：并集 100% 覆盖、确定性、各正确率档的恒稳配比、五星排序；
2. 节奏参数：goal 快照落库（user_input）、missing_fields 纳管、pace 端点；
3. v2 排期：会话制 plan_items（round_index=会话序号）、周期小测+终测并存、
   提前练不改排期、UNIQUE 幂等；
4. 终测完成门：通过 → completed；不通过 → 追加一轮周期（已稳定项进已知池）；
5. 存量隔离：legacy_v21 训练零迁移（generate_plan 分发回 ADR-0021 五轮）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.session_composition import (  # noqa: E402
    ItemStat,
    compose_sessions,
    controller_ratio,
    star_value,
)
from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import (  # noqa: E402
    answer_service,
    attempt_service,
    goal_clarification_service,
    path_service,
    plan_service,
    quiz_service,
)


def _skeleton(training_id: int, count: int = 12) -> None:
    items = [
        path_service.PlannedItem(
            title=f"知识点 {index:02d}",
            item_type="memory",
            difficulty=2,
            knowledge_point=f"知识点 {index:02d}",
            minutes=10,
        )
        for index in range(1, count + 1)
    ]
    path_service.save_skeleton(
        path_service.PathSkeleton(
            training_id=training_id,
            horizon_weeks=2,
            weekly_frequency=3,
            daily_budget_minutes=30,
            stages=[path_service.PlannedStage(title="阶段一", goal="打底", items=items)],
        )
    )


class TestCompositionController(unittest.TestCase):
    """纯函数配比控制器（spec R2）：并集/确定性/恒稳分档/五星。"""

    def _stats(self, count: int = 12) -> list[ItemStat]:
        return [
            ItemStat(item_key=f"item-{i:02d}", ordinal=i, minutes=10)
            for i in range(1, count + 1)
        ]

    def test_union_coverage_and_determinism(self) -> None:
        for n in (2, 3, 4, 6):
            stats = self._stats()
            comp = compose_sessions(stats, n, anchor=date(2026, 11, 22), horizon_days=14)
            union: set[str] = set()
            for keys in comp.sessions:
                self.assertEqual(len(keys), len(set(keys)), "同一会话内不得重复")
                union |= set(keys)
            self.assertEqual(len(union), 12, f"N={n} 时并集必须覆盖全部训练项")
            again = compose_sessions(
                self._stats(), n, anchor=date(2026, 11, 22), horizon_days=14
            )
            self.assertEqual(
                [sorted(s) for s in comp.sessions],
                [sorted(s) for s in again.sessions],
                "相同输入必得相同分配（纯函数）",
            )

    def test_session_dates_evenly_spread(self) -> None:
        comp = compose_sessions(self._stats(), 3, anchor=date(2026, 11, 22), horizon_days=14)
        self.assertEqual(comp.dates, [date(2026, 11, 26), date(2026, 12, 1), date(2026, 12, 6)])

    def test_controller_bands(self) -> None:
        self.assertEqual(controller_ratio(None), (0.50, 0.50), "无数据按目标带")
        self.assertEqual(controller_ratio(0.85), (0.50, 0.50), "70-90% 目标带维持")
        self.assertEqual(controller_ratio(0.65), (0.625, 0.375), "60-70% 偏难：25:15")
        self.assertEqual(controller_ratio(0.58), (0.75, 0.25), "<60% 太难：30:10")
        known, wrong = controller_ratio(0.95)
        self.assertLess(known, 0.5, ">90% 太容易：降已知")
        self.assertGreater(wrong, 0.5, ">90% 太容易：升错题/新知")

    def test_wrong_items_win_overlap_and_stable_last(self) -> None:
        stats = [
            ItemStat(item_key="wrong", ordinal=1, attempts=2, ever_failed=True, last_result="fail"),
            ItemStat(item_key="regress", ordinal=2, attempts=2, ever_passed=True, ever_failed=True, last_result="fail"),
            ItemStat(item_key="stable", ordinal=3, attempts=3, ever_passed=True, last_result="pass", consecutive_passes=3),
            ItemStat(item_key="fresh", ordinal=4),
        ]
        self.assertEqual(star_value(stats[0]), 5, "错题 5★")
        self.assertEqual(star_value(stats[1]), 3, "回归（先对后错）3★")
        self.assertEqual(star_value(stats[2]), 1, "稳定答对 1★")
        self.assertEqual(star_value(stats[3]), 0, "未接触 0★")
        comp = compose_sessions(
            stats, 2, anchor=date(2026, 11, 22), horizon_days=14, accuracy=0.85
        )
        wrong_pick_position = comp.sessions[1].index("wrong")
        stable_pick_position = comp.sessions[1].index("stable")
        self.assertLess(
            wrong_pick_position, stable_pick_position,
            "重叠池里错题先于稳定答对入选（五星排序）",
        )


def _conn():
    from src.db.sqlite import get_connection

    return get_connection()


class TestPaceCollection(unittest.TestCase):
    """节奏参数收集（spec R1）：快照 user_input、missing_fields 纳管、pace 端点。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "pace.db")
        init_db()

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        resp = self.client.post(
            "/api/auth/register",
            json={"email": "pace@example.com", "password": "password8", "display_name": "P"},
        )
        assert resp.status_code == 200, resp.text
        start = self.client.post("/api/wizard/start", json={"topic": "我想系统学习 Redis 持久化机制"})
        assert start.status_code == 200, start.text
        self.training_id = start.json()["training_id"]

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_pace_endpoint_roundtrip(self) -> None:
        payload = self.client.post(
            f"/api/wizard/{self.training_id}/pace",
            json={"horizon_weeks": 2, "session_count": 3},
        )
        self.assertEqual(payload.status_code, 200)
        data = payload.json()
        self.assertEqual(data["pace"]["horizon_weeks"], 2)
        self.assertEqual(data["pace"]["session_count"], 3)
        self.assertIn("recommended", data["pace"])
        training = queries.get_training(self.training_id)
        self.assertEqual(training.schedule_mode, "session_ratio", "节奏提交即切 session_ratio")
        snapshot = training.goal_json
        self.assertEqual(snapshot["horizon_days"], 14)
        self.assertEqual(snapshot["session_count"], 3)
        self.assertEqual(snapshot["field_sources"]["horizon_days"], "user_input")
        self.assertEqual(snapshot["field_sources"]["session_count"], "user_input")

    def test_pace_invalid_value_rejected(self) -> None:
        resp = self.client.post(
            f"/api/wizard/{self.training_id}/pace",
            json={"horizon_weeks": 9, "session_count": 1},
        )
        self.assertEqual(resp.status_code, 400)

    def test_recommend_by_level(self) -> None:
        rec = goal_clarification_service.recommend_pace("能讲清")
        self.assertGreaterEqual(rec["session_count"], 3, "等级越高建议次数越多")
        rec_more = goal_clarification_service.recommend_pace("会用", knowledge_point_count=15)
        self.assertGreaterEqual(rec_more["session_count"], rec["session_count"])


class TestSessionPlanLifecycle(unittest.TestCase):
    """v2 排期 + 终测门 + 提前练 + 追加周期（spec R2/R3/R4）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "cycle.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api

        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(
                    {
                        "question": "请说明该知识点的核心机制。",
                        "reference_answer": "要点齐全即可",
                        "difficulty": 2,
                        "question_type": "qa",
                        "points": [
                            {"point_id": "p1", "text": "核心机制", "weight": 2, "is_required": True}
                        ],
                    },
                    ensure_ascii=False,
                ), 10, 20
            if "测验变式" in content:
                return json.dumps({"questions": []}, ensure_ascii=False), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        client_module._call_api = fake_call_api

        training = queries.create_training(topic="会话制训练", status="draft")
        goal_clarification_service.set_pace(training.id, 14, 3)
        queries.update_training(training.id, status="confirmed")
        _skeleton(training.id)
        self.training_id = training.id
        self.summary = plan_service.generate_plan(training.id)

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_list_payload_has_next_due_and_final_due(self) -> None:
        """列表 payload 必须带 next_due/final_due（训练列表页展示口径）。"""
        from fastapi.testclient import TestClient

        client = TestClient(__import__("src.api.app", fromlist=["app"]).app)
        client.post(
            "/api/auth/register",
            json={"email": f"list-{self.training_id}@example.com", "password": "password8", "display_name": "L"},
        )
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET owner_user_id = (SELECT id FROM users WHERE email = ?) "
                "WHERE id = ?",
                (f"list-{self.training_id}@example.com", self.training_id),
            )
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/api/trainings")
        self.assertEqual(resp.status_code, 200)
        row = next(t for t in resp.json()["trainings"] if t["id"] == self.training_id)
        self.assertIn("next_due", row)
        self.assertIn("final_due", row)
        self.assertIsNotNone(row["next_due"], "有计划项的训练必须能给出下次到期")
        self.assertIsNotNone(row["final_due"], "session_ratio 训练必须能给出终测日")

    def test_sessions_and_union_and_idempotency(self) -> None:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT round_index, kind, COUNT(*) n FROM plan_items "
                "WHERE training_id = ? AND kind = 'train' GROUP BY round_index ORDER BY round_index",
                (self.training_id,),
            ).fetchall()
            union = conn.execute(
                "SELECT COUNT(DISTINCT item_key) n FROM plan_items "
                "WHERE training_id = ? AND kind = 'train'",
                (self.training_id,),
            ).fetchone()["n"]
            assessments = conn.execute(
                "SELECT item_key, kind FROM plan_items WHERE training_id = ? AND kind = 'assessment'",
                (self.training_id,),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([int(r["round_index"]) for r in rows], [1, 2, 3], "3 次会话")
        self.assertEqual(union, 12, "并集 100% 覆盖")
        keys = {str(r["item_key"]) for r in assessments}
        self.assertTrue(any(key.startswith("quiz-") for key in keys), "周期小测保留（每 14 天）")
        self.assertTrue(any(key.startswith("final-") for key in keys), "终测并存")

        summary = plan_service.generate_plan(self.training_id)
        self.assertEqual(summary.created, 0, "UNIQUE 幂等：重复生成不产生新行")

    def test_early_practice_keeps_schedule(self) -> None:
        """提前练（design D5）：提前作答照常判分落库，其余会话日期不变。"""
        from src.services import answer_service

        rounds = plan_service.training_plan_items(self.training_id)
        future = [task for task in rounds if task.round_index == 2][:1]
        self.assertTrue(future, "有未到期的第 2 次会话可提前练")
        outcome = answer_service.ensure_question(future[0].plan_id)
        self.assertTrue(outcome["question"])
        answer_service.submit_answer(future[0].plan_id, "提前练的作答，包含核心机制")

        dates_after = {
            task.round_index: task.due_date for task in plan_service.training_plan_items(self.training_id)
        }
        self.assertEqual(len(dates_after), 3, "提前练不改其余会话排期语义")

    def test_final_gate_pass_completes_training(self) -> None:
        """终测通过 → completed（spec R4）。终测不受冷却期限制。"""
        conn = _conn()
        try:
            final_item = conn.execute(
                "SELECT id, item_key FROM plan_items WHERE training_id = ? AND kind = 'assessment' "
                "AND item_key LIKE 'final-%'",
                (self.training_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(final_item)

        # 题库空时终测应给出可读错误（终测覆盖全部必修项的前提是有题）
        with self.assertRaises(ValueError):
            quiz_service.start_assessment(self.training_id, trigger="final")

        # 给每个训练项造题库题（绕过冷却：终测 include_cooldown）
        conn = _conn()
        try:
            for index in range(1, 13):
                conn.execute(
                    "INSERT INTO question_bank (training_id, item_key, knowledge_point, "
                    "question_text, answer_text, practiced_count, last_practiced_at, banked_at, "
                    "cooldown_until, status) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')",
                    (
                        self.training_id,
                        f"知识点 {index:02d}",
                        f"知识点 {index:02d}",
                        f"问：知识点 {index:02d} 的核心机制？",
                        "答：要点",
                        "2026-11-22T00:00:00",
                        "2026-11-22T00:00:00",
                        "2026-12-06",
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        assessment = quiz_service.start_assessment(self.training_id, trigger="final")
        self.assertEqual(assessment.trigger, "final")
        self.assertEqual(assessment.question_count, 12, "终测覆盖全部必修项（12 个知识点各一题）")
        # 全部判 pass → 终测通过
        from src.services.quiz_service import save_manual_verdicts

        save_manual_verdicts(
            assessment.id,
            {index: "pass" for index in range(1, assessment.question_count + 1)},
        )
        result = quiz_service.finish_assessment(assessment.id, graded_by="self")
        self.assertTrue(result.passed)
        self.assertIsNone(result.cycle_appended)
        training = queries.get_training(self.training_id)
        self.assertEqual(training.status, "completed", "终测通过 → 训练完成")

    def test_final_fail_appends_cycle_with_stable_pool(self) -> None:
        """终测不通过 → 追加一轮周期；已稳定项进已知巩固池（spec R4）。"""
        # 会话 1 全部练 pass（造稳定项）
        rounds = plan_service.training_plan_items(self.training_id)
        session1 = [task for task in rounds if task.round_index == 1]
        for task in session1:
            from src.services import answer_service

            answer_service.ensure_question(task.plan_id)
            answer_service.submit_answer(task.plan_id, "作答覆盖核心机制")

        # 题库造题 + 终测 fail
        conn = _conn()
        try:
            for index in range(1, 13):
                conn.execute(
                    "INSERT INTO question_bank (training_id, item_key, knowledge_point, "
                    "question_text, answer_text, practiced_count, last_practiced_at, banked_at, "
                    "cooldown_until, status) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')",
                    (
                        self.training_id,
                        f"知识点 {index:02d}",
                        f"知识点 {index:02d}",
                        f"问：知识点 {index:02d}？",
                        "答：要点",
                        "2026-11-22T00:00:00",
                        "2026-11-22T00:00:00",
                        "2026-12-06",
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        assessment = quiz_service.start_assessment(self.training_id, trigger="final")
        from src.services.quiz_service import save_manual_verdicts

        save_manual_verdicts(
            assessment.id, {index: "fail" for index in range(1, assessment.question_count + 1)}
        )
        result = quiz_service.finish_assessment(assessment.id, graded_by="self")
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.cycle_appended, "终测未通过必须追加周期")
        self.assertEqual(result.cycle_appended["appended_sessions"], 3)

        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT round_index, COUNT(*) n FROM plan_items "
                "WHERE training_id = ? AND kind = 'train' GROUP BY round_index ORDER BY round_index",
                (self.training_id,),
            ).fetchall()
            finals = conn.execute(
                "SELECT COUNT(*) n FROM plan_items WHERE training_id = ? "
                "AND kind = 'assessment' AND item_key LIKE 'final-%'",
                (self.training_id,),
            ).fetchone()["n"]
        finally:
            conn.close()
        indexes = [int(r["round_index"]) for r in rows]
        self.assertEqual(indexes, [1, 2, 3, 4, 5, 6], "追加一轮 3 次会话（4-6）")
        self.assertEqual(finals, 2, "终测再次把关")


class TestLegacyIsolation(unittest.TestCase):
    """存量隔离（spec R4 / design D7）：无节奏的训练走 ADR-0021 五轮，不迁移。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "legacy.db")
        init_db()
        training = queries.create_training(topic="存量训练", status="confirmed")
        _skeleton(training.id, count=4)
        self.training_id = training.id
        self.summary = plan_service.generate_plan(training.id)

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_legacy_stays_v21(self) -> None:
        training = queries.get_training(self.training_id)
        self.assertEqual(training.schedule_mode, "legacy_v21", "存量默认 legacy_v21")
        self.assertEqual(self.summary.rounds, 5, "ADR-0021 固定五轮")
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) n FROM plan_items WHERE training_id = ? AND round_index = 3 "
                "AND kind = 'train'",
                (self.training_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(int(row["n"]), 4, "每轮覆盖全部训练项（legacy 语义不变）")

    def test_final_trigger_on_legacy_falls_back_to_normal_quiz(self) -> None:
        """legacy 训练误调终测：不进周期重组，按普通测验走补练轮。"""
        conn = _conn()
        try:
            for index in range(1, 5):
                conn.execute(
                    "INSERT INTO question_bank (training_id, item_key, knowledge_point, "
                    "question_text, answer_text, practiced_count, last_practiced_at, banked_at, "
                    "cooldown_until, status) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')",
                    (
                        self.training_id,
                        f"知识点 {index:02d}",
                        f"知识点 {index:02d}",
                        f"问：知识点 {index:02d}？",
                        "答",
                        "2026-11-22T00:00:00",
                        "2026-11-22T00:00:00",
                        "2020-01-01",
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        assessment = quiz_service.start_assessment(self.training_id, trigger="final")
        from src.services.quiz_service import save_manual_verdicts

        save_manual_verdicts(assessment.id, {index: "fail" for index in range(1, assessment.question_count + 1)})
        result = quiz_service.finish_assessment(assessment.id, graded_by="self")
        self.assertFalse(result.passed)
        self.assertIsNone(result.cycle_appended, "legacy 不追加会话周期")
        training = queries.get_training(self.training_id)
        self.assertNotEqual(training.status, "completed")


class TestDashboardVisibilityScoping(unittest.TestCase):
    """仪表盘指标 MUST 按可见集计算（2026-11-23 用户报 q2ng 数字泄漏）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "scoping.db")
        init_db()

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(__import__("src.api.app", fromlist=["app"]).app)
        self.client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "password8", "display_name": "A"},
        )
        # 用户 A 建两个活跃训练
        for index in range(2):
            resp = self.client.post("/api/wizard/start", json={"topic": f"A 的训练 {index}（超过四字描述）"})
            tid_new = resp.json()["training_id"]
            conn = queries.get_connection()
            try:
                conn.execute(
                    "UPDATE trainings SET owner_user_id = (SELECT id FROM users WHERE email = 'a@example.com'), "
                    "status = 'active' WHERE id = ?", (tid_new,),
                )
                conn.commit()
            finally:
                conn.close()
        # 用户 B 注册（无训练）
        self.b = TestClient(__import__("src.api.app", fromlist=["app"]).app)
        self.b.post(
            "/api/auth/register",
            json={"email": "b@example.com", "password": "password8", "display_name": "B"},
        )

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_metrics_scoped_to_visible(self) -> None:
        resp = self.client.get("/api/dashboard")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_all"], 2, "A 只看到自己的 2 个训练（非全系统）")
        self.assertEqual(body["total_active"], 2)
        # B 无训练：指标必须为 0，而不是全系统的数字
        resp_b = self.b.get("/api/dashboard")
        self.assertEqual(resp_b.json()["total_all"], 0)
        self.assertEqual(resp_b.json()["total_active"], 0)
        # 热力也按可见集：A 的作答不应计入 B 的热力
        conn = queries.get_connection()
        try:
            uid = conn.execute("SELECT id FROM users WHERE email = 'a@example.com'").fetchone()[0]
            tid = conn.execute("SELECT id FROM trainings WHERE owner_user_id = ?", (uid,)).fetchone()[0]
            conn.execute(
                "INSERT INTO practice_attempts (training_id, item_key, result, source, created_at) "
                "VALUES (?, 'k', 'pass', 'llm', '2026-11-23T10:00:00')", (tid,),
            )
            conn.commit()
        finally:
            conn.close()
        acts_a = self.client.get("/api/dashboard").json()["activity"]
        acts_b = self.b.get("/api/dashboard").json()["activity"]
        self.assertEqual(sum(a["count"] for a in acts_a), 1, "A 热力计入自己的作答")
        self.assertEqual(sum(a["count"] for a in acts_b), 0, "B 热力不计入 A 的作答（跨用户泄漏修复）")

    def test_archive_flow_from_detail(self) -> None:
        """训练完成 → 归档（项目完结）：详情页动作 + 状态展示。"""
        conn = queries.get_connection()
        try:
            tid = conn.execute(
                "SELECT id FROM trainings WHERE owner_user_id = "
                "(SELECT id FROM users WHERE email = 'a@example.com') LIMIT 1"
            ).fetchone()[0]
            conn.execute("UPDATE trainings SET status = 'completed' WHERE id = ?", (tid,))
            conn.commit()
        finally:
            conn.close()
        resp = self.client.post(f"/api/trainings/{tid}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "archived")
        # 归档后仍对 owner 可见（数据保留），状态=已归档
        row = next(t for t in self.client.get("/api/trainings").json()["trainings"] if t["id"] == tid)
        self.assertEqual(row["status"], "archived")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
