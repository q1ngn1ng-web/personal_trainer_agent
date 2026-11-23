"""客观题题型分流测试（2026-11-15 修复的回归钉子）。

修复前的缺陷：主链（answer_service._grade_answer）没有按题型分流，选择题/填空题
也被送进 LLM 语义判分——违反 ADR-0022 硬约束（客观题 MUST NOT 调用大模型），
且判分结果依赖模型语义猜测（实例见 plan_item #139 的选择题被判出 partial 要点）。

本文件钉住：
1. choice 提交选项 key → grade_choice 确定性判分，**零 LLM 调用**；
2. fill 提交答案 → grade_fill 确定性判分，**零 LLM 调用**；
3. 判分来源落库为 source='rule'、plan_items.graded_by='rule'；
4. /api/trainings/{id}/plan-items 完整计划视图可用（含未到期轮次与题型字段）。
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

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import answer_service, path_service, plan_service  # noqa: E402

ANCHOR = date(2026, 11, 10)


def _choice_payload() -> dict:
    return {
        "question": "Redis 持久化机制中，哪一种通过定期把内存数据生成快照文件保存？",
        "reference_answer": "RDB",
        "difficulty": 2,
        "question_type": "choice",
        "options": [
            {"key": "A", "text": "AOF 追加写命令日志", "is_correct": False},
            {"key": "B", "text": "RDB 定时生成内存快照", "is_correct": True},
            {"key": "C", "text": "混合持久化", "is_correct": False},
        ],
        "points": [{"point_id": "p1", "text": "答出 RDB", "weight": 2, "is_required": True}],
    }


def _fill_payload() -> dict:
    return {
        "question": "Redis 的默认持久化文件名是 ______。",
        "reference_answer": "dump.rdb",
        "difficulty": 1,
        "question_type": "fill",
        # train_question v1.2.0 契约：fill 的 options = 每空答案键
        # （key=空序号、text=标准答案，同空多个可接受写法用 ; 分隔）
        "options": [{"key": "1", "text": "dump.rdb;dump.rdb 文件", "is_correct": True}],
        "points": [{"point_id": "p1", "text": "dump.rdb", "weight": 1, "is_required": True}],
    }


def _fill_no_key_payload() -> dict:
    """题干没有空位线、options 也没有答案键的"伪填空"（训练 144 实测形态）。"""
    return {
        "question": "Redis 的 Hash 类型在元素较少时底层用哪种紧凑结构？（填一种即可）",
        "reference_answer": "ziplist 或 listpack",
        "difficulty": 1,
        "question_type": "fill",
        "points": [{"point_id": "p1", "text": "答出 ziplist/listpack", "weight": 5, "is_required": True}],
    }


def _skeleton(training_id: int) -> path_service.PathSkeleton:
    return path_service.PathSkeleton(
        training_id=training_id,
        horizon_weeks=2,
        weekly_frequency=3,
        daily_budget_minutes=30,
        stages=[
            path_service.PlannedStage(
                title="阶段一",
                goal="打底",
                items=[
                    path_service.PlannedItem(
                        title="持久化机制",
                        item_type="memory",
                        difficulty=2,
                        knowledge_point="RDB",
                        minutes=10,
                    )
                ],
            )
        ],
    )


class _ObjectiveDispatchBase(unittest.TestCase):
    """公共夹具：临时库 + 训练/计划 + 出题载荷 + LLM 断路器。"""

    PAYLOAD_FACTORY = staticmethod(_choice_payload)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "choice.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api

        training = queries.create_training(topic="Redis 持久化", status="active")
        anchor = ANCHOR - timedelta(days=1)
        queries.update_training(training.id, created_at=f"{anchor.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training
        self.task = plan_service.today_tasks(training_id=training.id)[0]

        self._install_train_stub()

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _install_train_stub(self) -> None:
        payload = self.PAYLOAD_FACTORY()

        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(payload, ensure_ascii=False), 10, 20
            raise AssertionError(f"客观题判分不得调用模型（收到的调用：{content[:40]}）")

        self._client._call_api = fake_call_api


class TestChoiceDispatch(_ObjectiveDispatchBase):
    PAYLOAD_FACTORY = staticmethod(_choice_payload)

    def test_correct_key_passes_with_zero_llm(self) -> None:
        answer_service.ensure_question(self.task.plan_id)
        outcome = answer_service.submit_answer(self.task.plan_id, "B")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "pass")
        self.assertEqual(outcome["score"], 1.0)
        self.assertIn("选项正确", outcome["reason"])

        conn = queries.get_connection()
        try:
            attempt = conn.execute(
                "SELECT source, score, point_results FROM practice_attempts "
                "WHERE training_id = ? ORDER BY id DESC LIMIT 1",
                (self.training.id,),
            ).fetchone()
            item = conn.execute(
                "SELECT graded_by, verdict FROM plan_items WHERE id = ?", (self.task.plan_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(attempt["source"], "rule", "客观题判分来源必须落库为 rule")
        self.assertEqual(attempt["score"], 1.0)
        self.assertIsNone(attempt["point_results"], "选择题没有要点语义，不伪造 point_results")
        self.assertEqual(item["graded_by"], "rule")

    def test_wrong_key_fails_with_zero_llm(self) -> None:
        answer_service.ensure_question(self.task.plan_id)
        outcome = answer_service.submit_answer(self.task.plan_id, "A")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "fail")
        self.assertEqual(outcome["score"], 0.0)
        self.assertIn("选项错误", outcome["reason"])

    def test_reanswer_practiced_unjudged_then_judged(self) -> None:
        """「已记录练习，未系统判分」的历史卡（practice-only 产生）：重新作答后被正常判分。"""
        from src.services import answer_service

        answer_service.ensure_question(self.task.plan_id)
        answer_service.mark_practiced_only(self.task.plan_id)
        rounds = plan_service.training_plan_items(self.training.id)
        self.assertEqual(rounds[0].status, "practiced")
        self.assertIsNone(rounds[0].verdict, "只练不判的历史卡没有判定")

        # 重新作答：choice 走确定性判分（零 LLM），补上判定
        second = answer_service.submit_answer(self.task.plan_id, "B")
        self.assertTrue(second["graded"])
        self.assertEqual(second["verdict"], "pass")

        conn = queries.get_connection()
        try:
            attempts = conn.execute(
                "SELECT COUNT(*) FROM practice_attempts WHERE training_id = ? AND item_key = ?",
                (self.training.id, self.task.item_key),
            ).fetchone()[0]
            item = conn.execute(
                "SELECT verdict, graded_by FROM plan_items WHERE id = ?", (self.task.plan_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(attempts, 1, "只练不判不落 attempt；判分的那次落一条")
        self.assertEqual(item["verdict"], "pass")
        self.assertEqual(item["graded_by"], "rule")


class TestFillDispatch(_ObjectiveDispatchBase):
    PAYLOAD_FACTORY = staticmethod(_fill_payload)

    def test_exact_answer_passes_with_zero_llm(self) -> None:
        answer_service.ensure_question(self.task.plan_id)
        outcome = answer_service.submit_answer(self.task.plan_id, "dump.rdb")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "pass")
        self.assertEqual(outcome["score"], 1.0)

    def test_wrong_answer_fails_with_zero_llm(self) -> None:
        answer_service.ensure_question(self.task.plan_id)
        outcome = answer_service.submit_answer(self.task.plan_id, "AOF")

        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "fail")
        self.assertEqual(outcome["score"], 0.0)


class TestFillValidation(_ObjectiveDispatchBase):
    """fill 生成侧校验（2026-11-23 修复）：没有空位线/答案键的伪填空必须降级 qa。

    修前 ensure_question 对 fill 不校验也不固化 options——题干没有空位的"伪填空"
    照存（前端渲染不出空、提交被"请把每个空都填上"挡死），判分时无键可比对必 0 分。
    """

    PAYLOAD_FACTORY = staticmethod(_fill_no_key_payload)

    def test_fill_without_markers_or_key_downgrades_to_qa(self) -> None:
        answer_service.ensure_question(self.task.plan_id)
        conn = queries.get_connection()
        try:
            row = conn.execute(
                "SELECT question_type, options FROM plan_items WHERE id = ?",
                (self.task.plan_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["question_type"], "qa", "无空位线且无答案键 → 降级 qa 语义判分")
        self.assertIsNone(row["options"])


class TestPlanItemsEndpoint(unittest.TestCase):
    """完整计划视图端点：全部轮次 + 题型字段（提前练的数据底座）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "plan.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api

        training = queries.create_training(topic="Redis 持久化", status="active")
        # 锚点推到未来：轮次 1 尚未到期，用于验证「提前练」不受到期门限制
        future_anchor = date.today() + timedelta(days=2)
        queries.update_training(training.id, created_at=f"{future_anchor.isoformat()}T10:00:00+08:00")
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        reg = self.client.post(
            "/api/auth/register",
            json={"email": "owner@example.com", "password": "password8", "display_name": "O"},
        )
        self.assertEqual(reg.status_code, 200)
        # member-invite：注册不再自动进组——显式入默认组织（本测试依赖组织可见性口径）
        from src.services.org_service import add_membership

        add_membership(reg.json()["viewer"]["user_id"], 1, role="member")

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_plan_items_returns_all_rounds_with_type_meta(self) -> None:
        resp = self.client.get(f"/api/trainings/{self.training.id}/plan-items")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 单训练项 → 5 轮训练（测验轮次不计入 kind='train'）
        self.assertEqual(body["count"], 5)
        first = body["items"][0]
        self.assertIn("question_type", first)
        self.assertIn("options", first)
        self.assertEqual(first["status"], "planned", "未到期轮次应在完整计划视图中可见（提前练的数据基础）")

    def test_early_practice_on_future_round(self) -> None:
        from src.llm import client as client_module
        from src.services import answer_service

        def _no_key(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            raise client_module.LLMError("no key in test")

        client_module._call_api = _no_key
        try:
            # 未来轮次不应出现在今日任务里
            self.assertEqual(plan_service.today_tasks(training_id=self.training.id), [])
            rounds = plan_service.training_plan_items(self.training.id)
            plan_id = rounds[0].plan_id

            outcome = answer_service.submit_answer(plan_id, "提前练的作答")
            # 无模型环境：判分不可用是诚实行为；但作答本身必须被受理
            self.assertFalse(outcome["graded"])
            self.assertIsNone(outcome["score"])

            rounds_after = plan_service.training_plan_items(self.training.id)
            self.assertEqual(rounds_after[0].status, "practiced", "提前作答后轮次状态应推进")
        finally:
            client_module._call_api = self._orig_call_api

    def test_regenerate_restores_missing_rounds(self) -> None:
        """路径重生成后新增的训练项缺轮次：regenerate 端点幂等补齐。"""
        conn = queries.get_connection()
        try:
            conn.execute("DELETE FROM plan_items WHERE training_id = ?", (self.training.id,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(len(plan_service.training_plan_items(self.training.id)), 0)

        resp = self.client.post(f"/api/trainings/{self.training.id}/plan/regenerate")
        self.assertEqual(resp.status_code, 200)

        rounds = plan_service.training_plan_items(self.training.id)
        self.assertEqual(len(rounds), 5, "补齐后应恢复 5 轮（OR IGNORE 幂等，不动已有轮次）")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
