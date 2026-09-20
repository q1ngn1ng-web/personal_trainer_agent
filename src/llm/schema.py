"""JSON Schema definitions for each LLM call purpose."""
from __future__ import annotations

from typing import Any

TOPIC_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_valid": {"type": "boolean"},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["is_valid", "suggestions", "reason"],
    "additionalProperties": False,
}

KEYWORD_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keywords": {"type": "array", "items": {"type": "string"}},
        "must_cover_count": {"type": "integer", "minimum": 1},
        "forbidden": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["keywords", "must_cover_count", "forbidden"],
    "additionalProperties": False,
}

BASELINE_Q_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": ["concept", "read", "write"]},
                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 3},
                    "question": {"type": "string"},
                    "reference_answer": {"type": "string"},
                },
                "required": ["dimension", "difficulty", "question", "reference_answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

BASELINE_SCORING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_idx": {"type": "integer", "minimum": 0},
                    "score": {"type": "string", "enum": ["mastered", "partial", "missing"]},
                    "notes": {"type": "string"},
                },
                "required": ["question_idx", "score", "notes"],
                "additionalProperties": False,
            },
        },
        "overall": {"type": "string", "enum": ["high", "mid", "low"]},
        "partial_topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["scores", "overall", "partial_topics"],
    "additionalProperties": False,
}

WEEKLY_CALIBRATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "baseline_score_delta": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "schedule_adjustment": {"type": "object"},
        "material_recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "remove"]},
                    "ref": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "ref", "reason"],
                "additionalProperties": False,
            },
        },
        "reward_refresh": {"type": "string"},
        "next_week_focus": {"type": "string"},
    },
    "required": [
        "baseline_score_delta",
        "schedule_adjustment",
        "material_recommendations",
        "reward_refresh",
        "next_week_focus",
    ],
    "additionalProperties": False,
}

MD_GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 10,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["files"],
    "additionalProperties": False,
}

PRETRAIN_CHECKLIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 5,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "materials": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["concept", "materials"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

GOAL_CLARIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "draft": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "level": {"type": "string", "enum": ["了解", "会用", "熟练", "能讲清"]},
                "acceptance": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["quantitative", "qualitative"]},
                        "statement": {"type": "string"},
                        "metric": {"type": "string", "enum": ["accuracy", "volume", "speed", "streak"]},
                        "target": {"type": "number"},
                        "unit": {"type": "string"},
                        "check": {"type": "string"},
                    },
                    "required": ["type", "statement"],
                    "additionalProperties": False,
                },
            },
            "required": ["content", "level", "acceptance"],
            "additionalProperties": False,
        },
        "field_sources": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "level": {"type": "string"},
                "acceptance": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "follow_up_question": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["draft", "field_sources", "missing_fields", "follow_up_question", "confidence"],
    "additionalProperties": False,
}

EDGE_PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "knowledge_point": {"type": "string"},
                    "heading_path": {"type": "string"},
                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 4},
                    "question": {"type": "string"},
                    "reference_answer": {"type": "string"},
                },
                "required": [
                    "knowledge_point",
                    "heading_path",
                    "difficulty",
                    "question",
                    "reference_answer",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

EDGE_PROBE_GRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "knowledge_point": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["pass", "fail"]},
                    "reason": {"type": "string"},
                },
                "required": ["knowledge_point", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

PATH_SKELETON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "horizon_weeks": {"type": "integer", "minimum": 1, "maximum": 52},
        "weekly_frequency": {"type": "integer", "minimum": 1, "maximum": 14},
        "daily_budget_minutes": {"type": "integer", "minimum": 5, "maximum": 240},
        "stages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "item_type": {
                                    "type": "string",
                                    "enum": ["memory", "comprehension", "practice", "prerequisite"],
                                },
                                "difficulty": {"type": "integer", "minimum": 1, "maximum": 4},
                                "knowledge_point": {"type": "string"},
                                "minutes": {"type": "integer", "minimum": 1, "maximum": 120},
                            },
                            "required": ["title", "item_type", "difficulty", "knowledge_point", "minutes"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "goal", "items"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["horizon_weeks", "weekly_frequency", "daily_budget_minutes", "stages"],
    "additionalProperties": False,
}

QUIZ_VARIANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "question": {"type": "string"},
                    "reference_answer": {"type": "string"},
                },
                "required": ["item_key", "question", "reference_answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

QUIZ_GRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["pass", "fail"]},
                    "reason": {"type": "string"},
                },
                "required": ["item_key", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


SCHEMA_REGISTRY: dict[str, dict[str, Any]] = {
    "topic_validation": TOPIC_VALIDATION_SCHEMA,
    "keyword_generation": KEYWORD_GENERATION_SCHEMA,
    "baseline_q": BASELINE_Q_SCHEMA,
    "baseline_scoring": BASELINE_SCORING_SCHEMA,
    "weekly_calibration": WEEKLY_CALIBRATION_SCHEMA,
    "md_generation": MD_GENERATION_SCHEMA,
    "pretrain_checklist": PRETRAIN_CHECKLIST_SCHEMA,
    "goal_clarification": GOAL_CLARIFICATION_SCHEMA,
    "edge_probe": EDGE_PROBE_SCHEMA,
    "edge_probe_grade": EDGE_PROBE_GRADE_SCHEMA,
    "path_skeleton": PATH_SKELETON_SCHEMA,
    "quiz_variant": QUIZ_VARIANT_SCHEMA,
    "quiz_grade": QUIZ_GRADE_SCHEMA,
}
