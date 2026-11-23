"""Prompt-Schema 契约守卫（2026-11-09，schema-in-prompt 修复的回归钉子）。

背景：四个新一代模板（train_question / quiz_grade / quiz_variant / explanation）曾只在
要求里写"字段见 schema"，模板里却**没有** ``{schema}`` 占位符——模型从未见过输出格式
定义，首发输出全靠盲猜（实测首发合规 0/6，全靠错误反馈重试兜底，延迟翻倍）。
本测试钉住：**凡在 SCHEMA_REGISTRY 注册了 schema 的用途，模板必须把 schema 展示给模型**。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.client import _render_prompt, _schema_dump  # noqa: E402
from src.llm.prompts import PROMPT_REGISTRY  # noqa: E402
from src.llm.schema import SCHEMA_REGISTRY  # noqa: E402

#: 修复时补上占位符的四个模板（防止版本回退）
RESCUED = {"train_question", "quiz_grade", "quiz_variant", "explanation"}


class TestPromptSchemaContract(unittest.TestCase):
    def test_every_schema_purpose_shows_schema_to_model(self) -> None:
        missing = [
            name
            for name in PROMPT_REGISTRY
            if name in SCHEMA_REGISTRY and "{schema}" not in PROMPT_REGISTRY[name][0]
        ]
        self.assertEqual(
            missing,
            [],
            "有 schema 却不向模型展示的用途（首发合规会退化）：" + ", ".join(missing),
        )

    def test_rescued_templates_carry_placeholder_and_bumped_version(self) -> None:
        expected = {
            "train_question": "v1.2.0",  # v1.2.0 = 填空题每空答案键（fill-grading 修复）
            "quiz_grade": "v1.4.0",  # v1.4.0 = 证据引用判分（grading-rubric-hardening）
            "quiz_variant": "v1.1.0",
            "explanation": "v1.2.0",
        }
        for name, version in expected.items():
            template, actual = PROMPT_REGISTRY[name]
            self.assertIn("{schema}", template, f"{name} 占位符不得回退")
            self.assertEqual(actual, version, f"{name} 版本号不得回退")

    def test_schema_renders_into_prompt_verbatim(self) -> None:
        """schema 自动注入后必须真实出现在渲染结果里（client._run_once 同款拼装）。"""
        template, _ = PROMPT_REGISTRY["quiz_grade"]
        variables = {"items": "[]", "memory_block": ""}
        variables = {**variables, "schema": _schema_dump(SCHEMA_REGISTRY["quiz_grade"])}
        rendered = _render_prompt(template, variables)
        self.assertIn('"results"', rendered, "schema JSON 应出现在渲染后的 prompt 中")
        self.assertNotIn("{schema}", rendered, "占位符必须被真实替换")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
