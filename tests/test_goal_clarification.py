"""目标澄清的纯函数单测（OpenSpec change: goal-clarification-confirm）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.goal import (  # noqa: E402
    CLARIFY_HARD_LIMIT,
    CLARIFY_SOFT_LIMIT,
    GOAL_SCHEMA_VERSION,
    GoalDraft,
    GoalFieldSource,
    InvalidTransitionError,
    assert_transition,
    build_inferred_acceptance,
    can_transition,
    is_generation_ready,
    is_vague,
    merge_goal,
    next_action,
    normalize_status,
    validate_acceptance,
)


class TestStatusMachine(unittest.TestCase):
    def test_normalize_created_is_draft(self) -> None:
        self.assertEqual(normalize_status("created"), "draft")
        self.assertEqual(normalize_status(None), "draft")
        self.assertEqual(normalize_status("confirmed"), "confirmed")

    def test_legal_transitions(self) -> None:
        self.assertTrue(can_transition("draft", "pending_confirm"))
        self.assertTrue(can_transition("pending_confirm", "confirmed"))
        self.assertTrue(can_transition("pending_confirm", "pending_confirm"))
        self.assertTrue(can_transition("confirmed", "active"))
        self.assertTrue(can_transition("created", "draft"))

    def test_illegal_transition_rejected(self) -> None:
        self.assertFalse(can_transition("confirmed", "draft"))
        with self.assertRaises(InvalidTransitionError):
            assert_transition("confirmed", "draft")

    def test_only_confirmed_can_generate(self) -> None:
        self.assertFalse(is_generation_ready("draft"))
        self.assertFalse(is_generation_ready("pending_confirm"))
        self.assertFalse(is_generation_ready("created"))
        self.assertTrue(is_generation_ready("confirmed"))


class TestAcceptanceValidation(unittest.TestCase):
    def test_quantitative_dict_ok(self) -> None:
        result = validate_acceptance(
            {"type": "quantitative", "metric": "accuracy", "target": 0.8, "unit": "10 句改错题"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "quantitative")

    def test_quantitative_unknown_metric_rejected(self) -> None:
        result = validate_acceptance({"type": "quantitative", "metric": "vibes", "target": 0.8})
        self.assertFalse(result.ok)

    def test_quantitative_target_out_of_range(self) -> None:
        result = validate_acceptance({"type": "quantitative", "metric": "accuracy", "target": 1.5})
        self.assertFalse(result.ok)

    def test_qualitative_without_check_needs_check(self) -> None:
        result = validate_acceptance({"type": "qualitative", "statement": "能不看稿讲清三种用法"})
        self.assertTrue(result.ok)
        self.assertTrue(result.needs_check)

    def test_qualitative_with_check_ok(self) -> None:
        result = validate_acceptance(
            {"type": "qualitative", "statement": "能不看稿讲清三种用法", "check": "录音回听"}
        )
        self.assertTrue(result.ok)
        self.assertFalse(result.needs_check)

    def test_vague_text_rejected(self) -> None:
        for text in ("比较熟练", "差不多了", "感觉还行", "随便"):
            with self.subTest(text=text):
                self.assertFalse(validate_acceptance(text).ok)

    def test_free_text_with_numbers_is_quantitative(self) -> None:
        result = validate_acceptance("10 句改错题做对 8 句")
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "quantitative")

    def test_observable_behaviour_is_qualitative(self) -> None:
        result = validate_acceptance("能自己讲清楚虚拟语气的用法")
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "qualitative")
        self.assertTrue(result.needs_check)

    def test_vague_helper(self) -> None:
        self.assertTrue(is_vague("差不多"))
        self.assertTrue(is_vague("短"))
        self.assertFalse(is_vague("10 句改错题正确率 80%"))


class TestGoalDraft(unittest.TestCase):
    def test_missing_fields(self) -> None:
        draft = GoalDraft(content="英语虚拟语气")
        self.assertEqual(set(draft.missing_fields()), {"level", "acceptance"})
        self.assertFalse(draft.is_complete())

    def test_level_must_be_in_enum(self) -> None:
        draft = GoalDraft(content="x", level="随便学学", acceptance="10 题对 8 题")
        self.assertIn("level", draft.missing_fields())

    def test_complete_draft(self) -> None:
        draft = GoalDraft(
            content="英语虚拟语气",
            level="会用",
            acceptance={"type": "quantitative", "metric": "accuracy", "target": 0.8},
        )
        self.assertTrue(draft.is_complete())
        self.assertEqual(draft.missing_fields(), ())

    def test_snapshot_contains_schema_version_and_sources(self) -> None:
        draft = GoalDraft(content="c", level="会用", acceptance="10 题对 8 题")
        draft.field_sources = {"content": GoalFieldSource.USER_INPUT.value}
        snapshot = draft.to_snapshot(2)
        self.assertEqual(snapshot["schema_version"], GOAL_SCHEMA_VERSION)
        self.assertEqual(snapshot["clarification_rounds"], 2)
        self.assertEqual(snapshot["field_sources"]["content"], "user_input")

    def test_snapshot_values_are_not_booleans(self) -> None:
        draft = GoalDraft(content="英语虚拟语气", level="能用", acceptance="10 题对 8 题")
        snapshot = draft.to_snapshot(0)
        self.assertEqual(snapshot["content"], "英语虚拟语气")
        self.assertNotIsInstance(snapshot["level"], bool)


class TestMergeGoal(unittest.TestCase):
    def test_user_value_wins(self) -> None:
        llm = {"draft": {"content": "英语虚拟语气", "level": "了解", "acceptance": "x"}}
        merged = merge_goal(
            llm,
            locked={"content": "英语虚拟语气", "level": "熟练"},
            locked_sources={"content": "user_input", "level": "user_reply"},
        )
        self.assertEqual(merged.level, "熟练")
        self.assertEqual(merged.field_sources["level"], "user_reply")
        self.assertEqual(merged.field_sources["content"], "user_input")

    def test_llm_fills_unlocked_fields(self) -> None:
        llm = {"draft": {"content": "x", "level": "会用", "acceptance": "10 题对 8 题"}}
        merged = merge_goal(llm, locked={"content": "x"})
        self.assertEqual(merged.level, "会用")
        self.assertEqual(merged.acceptance, "10 题对 8 题")

    def test_empty_llm_values_are_marked_inferred(self) -> None:
        merged = merge_goal({"draft": {"content": "x", "level": "", "acceptance": None}})
        self.assertEqual(merged.field_sources["level"], "inferred")


class TestClarifyLimits(unittest.TestCase):
    def test_ask_before_soft_limit(self) -> None:
        self.assertEqual(next_action(0, ("level",)), "ask")
        self.assertEqual(next_action(CLARIFY_SOFT_LIMIT - 1, ("level",)), "ask")

    def test_suggest_at_soft_limit(self) -> None:
        self.assertEqual(next_action(CLARIFY_SOFT_LIMIT, ("level",)), "suggest")

    def test_close_at_hard_limit(self) -> None:
        self.assertEqual(next_action(CLARIFY_HARD_LIMIT, ("level",)), "close")
        self.assertEqual(next_action(CLARIFY_HARD_LIMIT + 3, ("level",)), "close")

    def test_close_when_nothing_missing(self) -> None:
        self.assertEqual(next_action(0, ()), "close")

    def test_inferred_acceptance_shape(self) -> None:
        value = build_inferred_acceptance("英语虚拟语气")
        self.assertEqual(value["type"], "qualitative")
        self.assertTrue(value["check"])
        self.assertTrue(validate_acceptance(value).ok)


if __name__ == "__main__":
    unittest.main()
