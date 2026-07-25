"""Fallback responses per call_purpose when LLM calls fail after retries."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("src.llm.fallback")

FALLBACK_BASELINE_Q: dict[str, Any] = {
    "questions": [
        {
            "dimension": "concept",
            "difficulty": 1,
            "question": "请用自己的话解释这个训练主题的核心概念是什么？它要解决什么问题？",
            "reference_answer": (
                "应回答: 主题名称 + 一句话定义 + 该主题存在要解决的 1-2 个具体问题。"
                "若回答泛泛而谈、没有点出主题名词与具体问题，则判定 partial。"
            ),
        },
        {
            "dimension": "concept",
            "difficulty": 2,
            "question": "该主题最关键的 3 个知识点是什么？它们之间的联系与边界是什么？",
            "reference_answer": (
                "应回答: 列出 3 个关键知识点 + 给出它们如何组合/依赖/互补的关系。"
                "若只列点不解释关系、或知识点不准确，则判定 partial。"
            ),
        },
        {
            "dimension": "write",
            "difficulty": 3,
            "question": "请给出一个能体现你对该主题整体掌握的实战场景或小例子。",
            "reference_answer": (
                "应回答: 1 个具体场景（背景 + 你的操作 + 预期结果）。"
                "若场景与主题弱相关、缺少操作细节，则判定 partial。"
            ),
        },
    ]
}


def fallback_for(purpose: str) -> dict[str, Any] | None:
    """Return a fallback response dict for the given call purpose, or None if no fallback is defined."""
    if purpose == "baseline_q":
        logger.warning("fallback_for: serving preset baseline_q fallback (LLM exhausted)")
        return FALLBACK_BASELINE_Q
    logger.warning("fallback_for: no fallback defined for purpose=%s", purpose)
    return None