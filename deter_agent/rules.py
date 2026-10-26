"""Structured deterministic rules, constraint subset logic and coverage checks."""
from __future__ import annotations
import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Any
from .canonical import canonical_json, normalize_json

RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
MAX_RULES = 10_000
MAX_CONDITION_FIELDS = 100
MAX_IN_VALUES = 1_000
MAX_COVERAGE_COMBINATIONS = 100_000


class RuleValidationError(ValueError):
    pass


def _path(value: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _scalar_key(value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise RuleValidationError("eq/in constraints accept JSON scalar values only")
    return canonical_json(value)


@dataclass(frozen=True)
class Domain:
    existence: str = "any"
    values: frozenset[str] | None = None
    low: tuple[float, bool] | None = None
    high: tuple[float, bool] | None = None
    numeric_only: bool = False
    impossible: bool = False

    @classmethod
    def from_spec(cls, spec: Any) -> "Domain":
        operators = {"eq", "in", "gt", "gte", "lt", "lte", "exists"}
        if not isinstance(spec, dict) or not (set(spec) & operators):
            return cls("present", frozenset({_scalar_key(spec)}))
        unknown = set(spec) - operators
        if unknown:
            raise RuleValidationError(f"unsupported operators: {sorted(unknown)}")
        exists = spec.get("exists")
        if exists is not None and not isinstance(exists, bool):
            raise RuleValidationError("exists must be boolean")
        existence = "present" if exists is True else "absent" if exists is False else "any"
        values: frozenset[str] | None = None
        if "eq" in spec:
            values = frozenset({_scalar_key(spec["eq"])})
        if "in" in spec:
            if not isinstance(spec["in"], list) or len(spec["in"]) > MAX_IN_VALUES:
                raise RuleValidationError(f"in must be a list with at most {MAX_IN_VALUES} values")
            incoming = frozenset(_scalar_key(v) for v in spec["in"])
            values = incoming if values is None else values & incoming
        low = high = None
        numeric = False
        for key in ("gt", "gte"):
            if key in spec:
                value = spec[key]
                if not _is_number(value):
                    raise RuleValidationError(f"{key} requires a finite number")
                candidate = (float(value), key == "gte")
                if low is None or candidate[0] > low[0] or (candidate[0] == low[0] and not candidate[1]):
                    low = candidate
                numeric = True
        for key in ("lt", "lte"):
            if key in spec:
                value = spec[key]
                if not _is_number(value):
                    raise RuleValidationError(f"{key} requires a finite number")
                candidate = (float(value), key == "lte")
                if high is None or candidate[0] < high[0] or (candidate[0] == high[0] and not candidate[1]):
                    high = candidate
                numeric = True
        if existence == "absent" and (values is not None or numeric):
            raise RuleValidationError("exists:false cannot be combined with value constraints")
        if values is not None:
            existence = "present"
            if numeric:
                values = frozenset(
                    item for item in values
                    if _is_number(_parse_scalar(item)) and _within(_parse_scalar(item), low, high)
                )
        if numeric:
            existence = "present"
        impossible = (values is not None and not values) or _empty_interval(low, high)
        return cls(existence, values, low, high, numeric, impossible)

    def matches(self, present: bool, value: Any) -> bool:
        if self.impossible:
            return False
        if not present:
            return self.existence in ("any", "absent") and self.values is None and not self.numeric_only
        if self.existence == "absent":
            return False
        if self.values is not None and _scalar_key(value) not in self.values:
            return False
        if self.numeric_only and (not _is_number(value) or not _within(value, self.low, self.high)):
            return False
        return True

    def intersection(self, other: "Domain") -> "Domain":
        if self.impossible or other.impossible:
            return Domain(impossible=True)
        existence = _intersection_existence(self.existence, other.existence)
        if existence == "none":
            return Domain(impossible=True)
        values = self.values if other.values is None else other.values if self.values is None else self.values & other.values
        numeric = self.numeric_only or other.numeric_only
        low, high = _max_low(self.low, other.low), _min_high(self.high, other.high)
        if values is not None and numeric:
            values = frozenset(
                item for item in values
                if _is_number(_parse_scalar(item)) and _within(_parse_scalar(item), low, high)
            )
        impossible = (values is not None and not values) or _empty_interval(low, high)
        if values is not None or numeric:
            existence = "present"
        return Domain(existence, values, low, high, numeric, impossible)

    def subset_of(self, other: "Domain") -> bool:
        if self.impossible:
            return True
        if other.impossible:
            return False
        if not _existence_subset(self.existence, other.existence):
            return False
        if self.existence == "absent":
            return other.values is None and not other.numeric_only
        if other.values is not None:
            if self.values is None:
                return self.numeric_only and _singleton_interval(self.low, self.high) and _scalar_key(self.low[0]) in other.values
            return all(other.matches(True, _parse_scalar(item)) for item in self.values)
        if other.numeric_only:
            if not self.numeric_only:
                return self.values is not None and all(
                    _is_number(_parse_scalar(item)) and _within(_parse_scalar(item), other.low, other.high)
                    for item in self.values
                )
            return _lower_subset(self.low, other.low) and _upper_subset(self.high, other.high)
        return self.values is not None or not self.numeric_only or self.numeric_only


def _parse_scalar(value: str) -> Any:
    import json
    return json.loads(value)


def _within(value: Any, low: tuple[float, bool] | None, high: tuple[float, bool] | None) -> bool:
    if low is not None and (value < low[0] or (value == low[0] and not low[1])):
        return False
    if high is not None and (value > high[0] or (value == high[0] and not high[1])):
        return False
    return True


def _intersection_existence(a: str, b: str) -> str:
    if a == "any": return b
    if b == "any" or a == b: return a
    return "none"


def _existence_subset(a: str, b: str) -> bool:
    return b == "any" or a == b


def _max_low(a, b):
    if a is None: return b
    if b is None: return a
    if a[0] > b[0]: return a
    if b[0] > a[0]: return b
    return (a[0], a[1] and b[1])


def _min_high(a, b):
    if a is None: return b
    if b is None: return a
    if a[0] < b[0]: return a
    if b[0] < a[0]: return b
    return (a[0], a[1] and b[1])


def _empty_interval(low, high):
    return bool(low and high and (low[0] > high[0] or (low[0] == high[0] and not (low[1] and high[1]))))


def _singleton_interval(low, high):
    return bool(low and high and low[0] == high[0] and low[1] and high[1])


def _lower_subset(a, b):
    if b is None: return True
    if a is None: return False
    return a[0] > b[0] or (a[0] == b[0] and (not a[1] or b[1]))


def _upper_subset(a, b):
    if b is None: return True
    if a is None: return False
    return a[0] < b[0] or (a[0] == b[0] and (not a[1] or b[1]))


@dataclass(frozen=True)
class Condition:
    fields: dict[str, Domain]
    impossible: bool = False

    @classmethod
    def compile(cls, raw: dict[str, Any] | None) -> "Condition":
        raw = {} if raw is None else raw
        if not isinstance(raw, dict) or len(raw) > MAX_CONDITION_FIELDS:
            raise RuleValidationError("condition must be an object within field limits")
        fields = {}
        for path, spec in raw.items():
            if not isinstance(path, str) or not path or any(not part for part in path.split(".")):
                raise RuleValidationError("condition paths must be non-empty dotted paths")
            fields[path] = Domain.from_spec(spec)
        return cls(fields, any(domain.impossible for domain in fields.values()))

    @property
    def specificity(self) -> int:
        return sum(domain != Domain() for domain in self.fields.values())

    def matches(self, value: dict[str, Any]) -> bool:
        return not self.impossible and all(domain.matches(*_path(value, path)) for path, domain in self.fields.items())

    def subset_of(self, other: "Condition") -> bool:
        if self.impossible: return True
        if other.impossible: return False
        return all(
            self.fields.get(path, Domain()).subset_of(other.fields.get(path, Domain()))
            for path in set(self.fields) | set(other.fields)
        )

    def overlaps(self, other: "Condition") -> bool:
        if self.impossible or other.impossible: return False
        return all(
            not self.fields.get(path, Domain()).intersection(other.fields.get(path, Domain())).impossible
            for path in set(self.fields) | set(other.fields)
        )


@dataclass(frozen=True)
class Rule:
    rule_id: str
    priority: int
    when: dict[str, Any]
    action: str
    risk_rank: str = "low"
    operation: str | None = None
    fallback: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", self.rule_id or ""):
            raise RuleValidationError("rule_id must be a stable ASCII identifier")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int) or self.priority < 0:
            raise RuleValidationError("priority must be a non-negative integer")
        if not self.action:
            raise RuleValidationError("action must be a non-empty string")
        if self.risk_rank not in RISK_RANK:
            raise RuleValidationError(f"risk_rank must be one of {sorted(RISK_RANK)}")
        if self.fallback and self.when:
            raise RuleValidationError("fallback rules cannot have ordinary match conditions")
        if self.fallback and self.action not in {"reject", "escalate", "deny"}:
            raise RuleValidationError("fallback must fail closed")

    @property
    def condition(self) -> Condition:
        return Condition.compile(self.when)

    @property
    def specificity(self) -> int:
        return self.condition.specificity

    @property
    def sort_key(self):
        return (self.priority, -self.specificity, RISK_RANK[self.risk_rank], self.rule_id)

    def matches(self, value: dict[str, Any]) -> bool:
        return False if self.fallback else self.condition.matches(value)


@dataclass(frozen=True)
class RuleIssue:
    code: str
    message: str
    rule_ids: tuple[str, ...] = ()
    severity: str = "error"


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    required_operations: tuple[str, ...] = ()

    def ordered(self):
        return tuple(sorted((r for r in self.rules if not r.fallback), key=lambda r: r.sort_key))

    @property
    def fallback(self):
        items = [r for r in self.rules if r.fallback]
        if len(items) != 1:
            raise RuleValidationError("ruleset must have exactly one fallback")
        return items[0]

    def validate(self, *, fail_on_overlap: bool = False):
        issues: list[RuleIssue] = []
        if len(self.rules) > MAX_RULES:
            return [RuleIssue("rule_limit_exceeded", f"ruleset exceeds {MAX_RULES} rules")]
        ids = [r.rule_id for r in self.rules]
        if len(ids) != len(set(ids)):
            issues.append(RuleIssue("duplicate_rule_id", "rule IDs must be unique"))
        fallbacks = [r for r in self.rules if r.fallback]
        if len(fallbacks) != 1:
            issues.append(RuleIssue("fallback_count", "exactly one fail-closed fallback is required"))
        for rule in self.rules:
            if rule.condition.impossible:
                issues.append(RuleIssue("unsatisfiable_rule", "condition is unsatisfiable", (rule.rule_id,)))
        ordered = self.ordered()
        for i, earlier in enumerate(ordered):
            for later in ordered[i + 1:]:
                if later.condition.subset_of(earlier.condition):
                    issues.append(RuleIssue("shadowed_rule", f"{later.rule_id} is shadowed by {earlier.rule_id}", (earlier.rule_id,later.rule_id)))
                elif earlier.condition.overlaps(later.condition):
                    issues.append(RuleIssue("overlapping_rules", f"{earlier.rule_id} overlaps {later.rule_id}", (earlier.rule_id,later.rule_id), "error" if fail_on_overlap else "warning"))
        for operation in self.required_operations:
            if not any(r.operation == operation or _operation_match(r.condition, operation) for r in ordered):
                issues.append(RuleIssue("operation_uncovered", f"no explicit rule covers operation {operation!r}"))
        return issues

    def raise_if_invalid(self, *, fail_on_overlap: bool = False):
        errors = [x for x in self.validate(fail_on_overlap=fail_on_overlap) if x.severity == "error"]
        if errors:
            raise RuleValidationError("; ".join(f"{x.code}: {x.message}" for x in errors))

    def resolve(self, value: dict[str, Any]):
        candidates = [r for r in self.ordered() if r.matches(value)]
        if candidates:
            return candidates[0], tuple(r.rule_id for r in candidates)
        return self.fallback, ()


def _operation_match(condition: Condition, operation: str) -> bool:
    domain = condition.fields.get("operation")
    return domain is not None and domain.matches(True, operation)


def validate_rules(rules: tuple[Rule, ...] | list[Rule], *, required_operations=(), fail_on_overlap=False):
    return RuleSet(tuple(rules), tuple(required_operations)).validate(fail_on_overlap=fail_on_overlap)


class RuleEngine:
    def __init__(self, ruleset: RuleSet):
        ruleset.raise_if_invalid()
        self.ruleset = ruleset

    def decide(self, value: dict[str, Any]) -> dict[str, Any]:
        winner, matches = self.ruleset.resolve(value)
        return {
            "rule_id": winner.rule_id,
            "action": winner.action,
            "reason_code": winner.metadata.get("reason_code", "NO_RULE_MATCHED" if winner.fallback else "MATCHED_RULE"),
            "matched_rule_ids": list(matches),
            "priority": winner.priority,
            "specificity": winner.specificity,
            "risk_rank": winner.risk_rank,
            "fallback": winner.fallback,
        }


@dataclass(frozen=True)
class CoverageResult:
    combinations_checked: int
    explicit_matches: int
    fallback_matches: int
    examples_using_fallback: tuple[dict[str, Any], ...]


def check_totality(ruleset: RuleSet, input_domains: dict[str, list[Any]], *, max_combinations: int = MAX_COVERAGE_COMBINATIONS, fallback_example_limit: int = 20):
    names = sorted(input_domains)
    domains = [input_domains[name] for name in names]
    if any(not isinstance(items, list) or not items for items in domains):
        raise RuleValidationError("finite coverage domains must be non-empty lists")
    size = math.prod(len(items) for items in domains)
    if size > max_combinations:
        raise RuleValidationError(f"coverage product {size} exceeds limit {max_combinations}")
    explicit = fallback = 0
    examples = []
    for values in itertools.product(*domains):
        case = dict(zip(names, values, strict=True))
        winner, _ = ruleset.resolve(case)
        if winner.fallback:
            fallback += 1
            if len(examples) < fallback_example_limit:
                examples.append(case)
        else:
            explicit += 1
    return CoverageResult(size, explicit, fallback, tuple(examples))


def normalize_rule_value(value: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):
        raise RuleValidationError("rule input must be a JSON object")
    return normalized
