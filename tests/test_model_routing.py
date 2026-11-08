"""按用途路由模型的测试（成本治理，2026-11-09）。

钉住四件事：
1. 未配置 ``LLM_LIGHT_MODEL`` 时全部用途走主力模型（行为与路由前完全一致）；
2. 配置后仅 ``LIGHT_PURPOSES`` 路由到轻模型，其余（含判分）保持主力；
3. **护栏：quiz_grade 永远不路由**——人工一致率标注完成前不得更换判分模型；
4. ``complete()`` 实际把 ``model_for`` 的结果传给 API 且审计记录真实模型。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm import client as llm_client  # noqa: E402

TOPIC_OK = json.dumps(
    {"is_valid": True, "suggestions": [], "reason": "主题清晰"}, ensure_ascii=False
)
GRADE_OK = json.dumps(
    {"results": [{"item_key": "k1", "verdict": "pass", "reason": "答到"}]}, ensure_ascii=False
)


class TestModelFor(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("LLM_LIGHT_MODEL", None)

    def test_without_env_everything_uses_main_model(self) -> None:
        os.environ.pop("LLM_LIGHT_MODEL", None)
        for purpose in ("topic_validation", "keyword_generation", "quiz_grade", "train_question"):
            self.assertEqual(llm_client.model_for(purpose), llm_client.DEEPSEEK_MODEL)

    def test_light_purposes_route_when_configured(self) -> None:
        os.environ["LLM_LIGHT_MODEL"] = "qwen-flash"
        self.assertEqual(llm_client.model_for("topic_validation"), "qwen-flash")
        self.assertEqual(llm_client.model_for("keyword_generation"), "qwen-flash")
        # 非轻用途保持主力
        for purpose in ("quiz_grade", "train_question", "goal_clarification", "explanation"):
            self.assertEqual(llm_client.model_for(purpose), llm_client.DEEPSEEK_MODEL)

    def test_grading_never_in_light_purposes(self) -> None:
        """护栏：判分不路由——换判分模型必须先过人工一致率标注。"""
        self.assertNotIn("quiz_grade", llm_client.LIGHT_PURPOSES)
        self.assertNotIn("quiz_variant", llm_client.LIGHT_PURPOSES)


class TestRoutingThroughComplete(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_call_api = llm_client._call_api
        self._captured: dict = {}

        def recorder(messages, *args, **kwargs):  # noqa: ANN001, ANN003
            content = messages[1]["content"]
            payload = TOPIC_OK if "主题评审员" in content else GRADE_OK
            self._captured = {
                "model": kwargs.get("model"),
                "temperature": kwargs.get("temperature"),
                "prompt": content,
            }
            return payload, 10, 20

        llm_client._call_api = recorder

    def tearDown(self) -> None:
        llm_client._call_api = self._orig_call_api
        os.environ.pop("LLM_LIGHT_MODEL", None)

    def test_complete_routes_topic_validation_to_light_model(self) -> None:
        os.environ["LLM_LIGHT_MODEL"] = "qwen-flash"
        result = llm_client.complete(
            "topic_validation", {"topic": "Redis 八股", "description": "备考"}
        )
        self.assertEqual(self._captured["model"], "qwen-flash")
        self.assertEqual(result["model"], "qwen-flash", "审计必须记录真实调用模型")

    def test_complete_keeps_main_model_without_env(self) -> None:
        os.environ.pop("LLM_LIGHT_MODEL", None)
        result = llm_client.complete(
            "topic_validation", {"topic": "Redis 八股", "description": "备考"}
        )
        self.assertEqual(self._captured["model"], llm_client.DEEPSEEK_MODEL)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
