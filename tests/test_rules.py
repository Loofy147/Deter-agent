import itertools
import unittest

from deter_agent.rules import Condition, Rule, RuleEngine, RuleSet, RuleValidationError, check_totality


def rule(rule_id, priority, when, action, risk_rank="low", fallback=False, operation=None):
    return Rule(rule_id, priority, when, action, risk_rank, operation, fallback)


class DomainLogicTests(unittest.TestCase):
    def test_eq_subset_of_in(self):
        exact = Condition.compile({"topic": {"eq": "billing"}})
        enum = Condition.compile({"topic": {"in": ["billing", "technical"]}})
        self.assertTrue(exact.subset_of(enum))
        self.assertFalse(enum.subset_of(exact))
        self.assertTrue(exact.overlaps(enum))

    def test_interval_subset_and_overlap(self):
        narrow = Condition.compile({"amount": {"gte": 10, "lt": 20}})
        wide = Condition.compile({"amount": {"gte": 0, "lte": 50}})
        disjoint = Condition.compile({"amount": {"gt": 30, "lte": 40}})
        self.assertTrue(narrow.subset_of(wide))
        self.assertTrue(narrow.overlaps(wide))
        self.assertFalse(narrow.overlaps(disjoint))

    def test_field_subset(self):
        broad = Condition.compile({"intent": {"eq": "route"}})
        narrow = Condition.compile({"intent": {"eq": "route"}, "severity": {"eq": "critical"}})
        self.assertTrue(narrow.subset_of(broad))
        self.assertFalse(broad.subset_of(narrow))

    def test_absent_and_present_disjoint(self):
        absent = Condition.compile({"payload.customer": {"exists": False}})
        present = Condition.compile({"payload.customer": {"exists": True}})
        self.assertFalse(absent.overlaps(present))

    def test_normalization_idempotence(self):
        import unicodedata
        one = unicodedata.normalize("NFC", "Cafe\u0301")
        two = unicodedata.normalize("NFC", one)
        self.assertEqual(one, two)


class RuleEngineTests(unittest.TestCase):
    def setUp(self):
        self.rules = RuleSet((
            rule("ALLOW-BASE", 20, {"operation": {"eq": "route"}, "severity": {"in": ["low", "high"]}}, "route_general"),
            rule("ALLOW-CRITICAL", 20, {"operation": {"eq": "route"}, "severity": {"eq": "high"}, "topic": {"eq": "billing"}}, "route_priority", "high"),
            rule("FALLBACK", 999, {}, "reject", fallback=True),
        ), required_operations=("route",))

    def test_specificity_wins_equal_priority(self):
        result = RuleEngine(self.rules).decide({"operation": "route", "severity": "high", "topic": "billing"})
        self.assertEqual(result["rule_id"], "ALLOW-CRITICAL")
        self.assertEqual(result["matched_rule_ids"], ["ALLOW-CRITICAL", "ALLOW-BASE"])

    def test_fallback_explicit(self):
        self.assertTrue(RuleEngine(self.rules).decide({"operation": "unknown"})["fallback"])

    def test_shadow_detection(self):
        rules = RuleSet((
            rule("BROAD", 1, {"operation": {"eq": "route"}}, "route"),
            rule("DEAD", 2, {"operation": {"eq": "route"}, "severity": {"eq": "critical"}}, "route_critical"),
            rule("FALLBACK", 999, {}, "reject", fallback=True),
        ))
        self.assertIn("shadowed_rule", [issue.code for issue in rules.validate()])

    def test_overlap_warning(self):
        rules = RuleSet((
            rule("A", 5, {"level": {"in": ["a", "b"]}}, "x"),
            rule("B", 10, {"level": {"in": ["b", "c"]}}, "y"),
            rule("FALLBACK", 999, {}, "reject", fallback=True),
        ))
        self.assertIn("overlapping_rules", [issue.code for issue in rules.validate()])

    def test_duplicate_ids_raise(self):
        rules = RuleSet((
            rule("DUP", 1, {"x": {"eq": 1}}, "a"),
            rule("DUP", 2, {"x": {"eq": 2}}, "b"),
            rule("FALLBACK", 999, {}, "reject", fallback=True),
        ))
        with self.assertRaises(RuleValidationError):
            RuleEngine(rules)

    def test_totality_reports_fallback(self):
        result = check_totality(self.rules, {"operation": ["route", "other"], "severity": ["low", "high", "critical"]})
        self.assertEqual(result.combinations_checked, 6)
        self.assertGreater(result.fallback_matches, 0)
        self.assertEqual(result.explicit_matches + result.fallback_matches, 6)

    def test_coverage_limit(self):
        with self.assertRaises(RuleValidationError):
            check_totality(self.rules, {"a": list(range(101)), "b": list(range(100))}, max_combinations=1000)

    def test_input_order_independent(self):
        payload = {"operation": "route", "severity": "high", "topic": "billing"}
        expected = RuleEngine(self.rules).decide(payload)
        for permutation in itertools.islice(itertools.permutations(self.rules.rules), 6):
            self.assertEqual(RuleEngine(RuleSet(tuple(permutation))).decide(payload), expected)
