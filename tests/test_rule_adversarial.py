"""Adversarial boundary and deterministic-order tests for the rule engine."""
from __future__ import annotations

import itertools
import unittest

from deter_agent.rules import Condition, Rule, RuleEngine, RuleSet, RuleValidationError


def make_rule(rule_id, priority, when, action, *, risk="low", fallback=False):
    return Rule(
        rule_id=rule_id,
        priority=priority,
        when=when,
        action=action,
        risk_rank=risk,
        fallback=fallback,
    )


class RuleAdversarialTests(unittest.TestCase):
    def test_exists_operator_rejects_null_and_non_boolean_operands(self):
        for operand in (None, 0, 1, "true", []):
            with self.subTest(operand=operand):
                with self.assertRaises(RuleValidationError):
                    Condition.compile({"customer": {"exists": operand}})

    def test_subset_claim_is_sound_over_finite_boundary_corpus(self):
        raw_conditions = [
            {},
            {"x": {"exists": True}},
            {"x": {"exists": False}},
            {"x": {"eq": 1}},
            {"x": {"eq": True}},
            {"x": {"in": [1, 2]}},
            {"x": {"gte": 0}},
            {"x": {"gt": 1}},
            {"x": {"lt": 3}},
            {"x": {"lte": 2}},
            {"x": {"gte": 1, "lte": 1}},
            {"x": {"in": [1, 2], "gt": 1}},
            {"x": {"exists": True}, "y": {"eq": "yes"}},
            {"x": {"eq": 1}, "y": {"exists": True}},
        ]
        conditions = [Condition.compile(item) for item in raw_conditions]
        corpus = [
            {}, {"x": None}, {"x": False}, {"x": True}, {"x": -1}, {"x": 0},
            {"x": 1}, {"x": 1.0}, {"x": 2}, {"x": 3}, {"x": 4},
            {"x": "1"}, {"x": "other"}, {"x": 1, "y": None},
            {"x": 1, "y": "yes"}, {"x": 2, "y": "no"},
        ]
        for left, right in itertools.product(conditions, repeat=2):
            if left.subset_of(right):
                for value in corpus:
                    if left.matches(value):
                        self.assertTrue(
                            right.matches(value),
                            msg=f"subset claim did not hold for {value!r}: {left!r} subset {right!r}",
                        )

    def test_total_order_uses_priority_then_specificity_then_risk_then_id(self):
        rules = RuleSet((
            make_rule("Z-LOW", 5, {"x": {"in": ["a", "b"]}}, "z-low", risk="low"),
            make_rule("A-HIGH", 5, {"x": {"in": ["b", "c"]}}, "a-high", risk="high"),
            make_rule("A-LOW", 5, {"y": {"in": ["yes", "maybe"]}}, "a-low", risk="low"),
            make_rule(
                "SPECIFICITY-FIRST", 5,
                {"x": {"in": ["a", "b", "c"]}, "y": {"exists": True}},
                "specific", risk="high",
            ),
            make_rule("PRIORITY-FIRST", 1, {"z": {"eq": "go"}}, "priority", risk="critical"),
            make_rule("FALLBACK", 999, {}, "reject", fallback=True),
        ))
        values = {"x": "b", "y": "yes", "z": "go"}
        expected_order = [
            "PRIORITY-FIRST", "SPECIFICITY-FIRST", "A-LOW", "Z-LOW", "A-HIGH",
        ]
        for permutation in itertools.islice(itertools.permutations(rules.rules), 120):
            engine = RuleEngine(RuleSet(tuple(permutation)))
            decision = engine.decide(values)
            self.assertEqual(decision["matched_rule_ids"], expected_order)
            self.assertEqual(decision["rule_id"], expected_order[0])

    def test_invalid_exists_does_not_silently_turn_into_unconstrained_match(self):
        # A malformed exists operand must fail at compilation, not match any value.
        with self.assertRaises(RuleValidationError):
            Condition.compile({"customer": {"exists": None}})


if __name__ == "__main__":
    unittest.main()
