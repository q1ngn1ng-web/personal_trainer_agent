"""今日流程与训练管理测试（2026-11-15 bug 批次的回归钉子）。

钉住四件事：
1. 早早生成：pregenerate 一次把全部未生成轮次出完题，后续打开零模型调用；
2. 同一训练项一天只推一轮：答完之后今日数量减少、次日顺延仍成立；
   今天已作答的轮次出现在 done 列表（不闪走）；
3. 填空题：题干空位内联填写（按序 join | 提交），确定性判分零 LLM；
4. 训练管理：归档仅限已达标；删除不可恢复（仅个人模式 owner）。
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
        "question": "Redis 的 RDB 通过 ______ 生成快照，AOF 通过 ______ 追加命令。",
        "reference_answer": "RDB|AOF",
        "difficulty": 1,
        "question_type": "fill",
        "points": [{"point_id": "p1", "text": "RDB 与 AOF", "weight": 1, "is_required": True}],
    }


class TestTodayFlow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "today.db")
        init_db()

        from src.llm import client as client_module

        self._client = client_module
        self._orig_call_api = client_module._call_api
        self._llm_calls = 0

        training = queries.create_training(topic="Redis 持久化", status="active")
        queries.update_training(
            training.id,
            created_at=f"{(date.today() - timedelta(days=5)).isoformat()}T10:00:00+08:00",
        )
        path_service.save_skeleton(_skeleton(training.id))
        plan_service.generate_plan(training.id)
        self.training = training

    def tearDown(self) -> None:
        self._client._call_api = self._orig_call_api
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _install_payload_stub(self, payload: dict) -> None:
        def fake_call_api(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            self._llm_calls += 1
            content = messages[1]["content"] if len(messages) > 1 else ""
            if "训练出题助手" in content:
                return json.dumps(payload, ensure_ascii=False), 10, 20
            raise AssertionError(f"未预期的 LLM 调用：{content[:40]}")

        self._client._call_api = fake_call_api

    def _install_no_key(self) -> None:
        from src.llm import client as client_module

        def boom(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            raise client_module.LLMError("no key in test")

        self._client._call_api = boom

    def _first_plan_id(self) -> int:
        rounds = plan_service.training_plan_items(self.training.id)
        return rounds[0].plan_id

    def test_pregenerate_generates_all_rounds_once(self) -> None:
        self._install_payload_stub(_choice_payload())
        result = plan_service.pregenerate_questions(self.training.id)
        self.assertEqual(result["generated"], 5, "5 轮一次全部生成")
        calls_after = self._llm_calls

        # 预生成后再触发：无未生成轮次，零调用（幂等）
        again = plan_service.pregenerate_questions(self.training.id)
        self.assertEqual(again["generated"], 0)
        self.assertEqual(self._llm_calls, calls_after, "幂等：不重复生成")

        # 打开任意一轮：直接出题，零模型调用（早早生成的意义）
        plan_id = self._first_plan_id()
        before = self._llm_calls
        q = answer_service.ensure_question(plan_id)
        self.assertEqual(self._llm_calls, before, "已预生成的题目不得再调模型")
        self.assertEqual(q["question_type"], "choice")

    def test_practiced_today_hides_item_from_today(self) -> None:
        self._install_no_key()
        plan_id = self._first_plan_id()

        # 作答（判分器断路 → 只受理不判分，但状态推进为 practiced）
        outcome = answer_service.submit_answer(plan_id, "提前练的作答")
        self.assertFalse(outcome["graded"])

        # 今天不再推同一训练项（做了就少一个）
        today = plan_service.today_tasks(training_id=self.training.id)
        self.assertEqual(today, [], "已作答的训练项今天不得再次出现")

        # 今天已作答列表包含它（不闪走）
        done = plan_service.done_today_tasks()
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0].plan_id, plan_id)

        # 次日顺延仍成立：把今天推到明天后，后续逾期轮次重新出现
        tomorrow = date.today() + timedelta(days=1)
        later = plan_service.today_tasks(training_id=self.training.id, today=tomorrow)
        self.assertEqual(len(later), 1, "次日起顺延轮次重新可见")

    def test_fill_inline_join_grading(self) -> None:
        self._install_payload_stub(_fill_payload())
        plan_id = self._first_plan_id()
        answer_service.ensure_question(plan_id)

        outcome = answer_service.submit_answer(plan_id, "RDB|AOF")
        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "pass")
        self.assertEqual(outcome["score"], 1.0)

        outcome = answer_service.submit_answer(plan_id, "AOF|RDB")
        self.assertTrue(outcome["graded"])
        self.assertEqual(outcome["verdict"], "fail", "顺序错了必须判不通过")


class TestTrainingManagement(unittest.TestCase):
    """删除与归档端点（个人模式 viewer=None 直接放行的语义沿用）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "mgmt.db")
        init_db()

        self.training = queries.create_training(topic="待管理训练", status="active")
        path_service.save_skeleton(_skeleton(self.training.id))
        plan_service.generate_plan(self.training.id)

        from fastapi.testclient import TestClient

        from src.api.app import app

        self.client = TestClient(app)
        # 服务端中间件要求登录（企业版 profile 默认开启）：注册即登录
        owner_login = self.client.post(
            "/api/auth/register",
            json={"email": "mgmt@example.com", "password": "password8", "display_name": "M"},
        )
        assert owner_login.status_code == 200, owner_login.text
        owner_uid = owner_login.json()["viewer"]["user_id"]
        conn = queries.get_connection()
        try:
            conn.execute(
                "UPDATE trainings SET owner_user_id = ? WHERE id = ?",
                (owner_uid, self.training.id),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def test_archive_requires_completed(self) -> None:
        resp = self.client.post(f"/api/trainings/{self.training.id}/archive")
        self.assertEqual(resp.status_code, 400, "未达标训练不得归档")

        queries.update_training(self.training.id, status="completed")
        resp = self.client.post(f"/api/trainings/{self.training.id}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(queries.get_training(self.training.id).status, "archived")

    def test_delete_training(self) -> None:
        resp = self.client.delete(f"/api/trainings/{self.training.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertIsNone(queries.get_training(self.training.id))

        again = self.client.delete(f"/api/trainings/{self.training.id}")
        self.assertEqual(again.status_code, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
