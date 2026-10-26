"""Mutation testing for rule specifications with a fresh registry per mutant."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .canonical import canonical_json, sha256_json
from .registry import Registry


@dataclass(frozen=True)
class RuleMutant:
    mutant_id: str
    transform: Callable[[dict[str, Any]], dict[str, Any]]
    operator: str


def _find_rule(spec: dict[str, Any], rule_id: str) -> dict[str, Any]:
    for rule in spec.get("decision_rules", []):
        if rule.get("rule_id") == rule_id:
            return rule
    raise KeyError(f"rule {rule_id!r} not found")


def change_action(rule_id: str, action: str) -> RuleMutant:
    def transform(spec):
        _find_rule(spec, rule_id)["action"] = action
        return spec
    return RuleMutant(f"action:{rule_id}:{action}", transform, "action_change")


def shift_priority(rule_id: str, delta: int) -> RuleMutant:
    def transform(spec):
        rule = _find_rule(spec, rule_id)
        rule["priority"] = int(rule["priority"]) + delta
        return spec
    return RuleMutant(f"priority:{rule_id}:{delta}", transform, "priority_shift")


def remove_rule(rule_id: str) -> RuleMutant:
    def transform(spec):
        spec["decision_rules"] = [r for r in spec.get("decision_rules", []) if r.get("rule_id") != rule_id]
        return spec
    return RuleMutant(f"remove:{rule_id}", transform, "rule_removal")


def change_condition(rule_id: str, field: str, value: Any) -> RuleMutant:
    def transform(spec):
        _find_rule(spec, rule_id).setdefault("when", {})[field] = {"eq": value}
        return spec
    return RuleMutant(f"condition:{rule_id}:{field}", transform, "condition_change")


def change_field(path: tuple[str, ...], value: Any, *, operator: str = "field_change") -> RuleMutant:
    """Mutate an arbitrary nested JSON-spec field for policy/runtime/promotion campaigns."""
    if not path or any(not isinstance(part, str) or not part for part in path):
        raise ValueError("path must contain non-empty string field names")
    replacement = copy.deepcopy(value)
    path_label = ".".join(path)

    def transform(spec):
        target = spec
        for part in path[:-1]:
            if not isinstance(target, dict) or part not in target:
                raise KeyError(f"nested mutation path not found: {path_label}")
            target = target[part]
        if not isinstance(target, dict):
            raise TypeError(f"mutation parent is not an object: {path_label}")
        target[path[-1]] = copy.deepcopy(replacement)
        return spec

    return RuleMutant(f"field:{path_label}:{sha256_json(replacement)[:12]}", transform, operator)


@dataclass(frozen=True)
class MutationResult:
    mutant_id: str
    operator: str
    outcome: str
    failed_cases: tuple[str, ...]
    detail: str = ""


@dataclass(frozen=True)
class MutationCampaign:
    baseline_cases: int
    killed: int
    surviving_candidates: int
    invalid_mutants: int
    mutation_score: float
    results: tuple[MutationResult, ...]


class MutationHarness:
    """Build each mutant in a clean Registry to avoid contamination between mutations.

    Surviving mutants are equivalence candidates over the supplied suite, not a proof
    of semantic equivalence for every possible input.
    """

    def __init__(
        self,
        registry_factory: Callable[[], Registry] = Registry,
        *,
        prepare: Callable[[Registry, dict[str, Any]], Any],
        execute_case: Callable[[Any, dict[str, Any]], Any],
    ):
        self.registry_factory = registry_factory
        self.prepare = prepare
        self.execute_case = execute_case

    def _run(self, spec: dict[str, Any], cases: list[dict[str, Any]]) -> tuple[list[str], list[Any]]:
        registry = self.registry_factory()
        try:
            prepared = self.prepare(registry, copy.deepcopy(spec))
            outputs = []
            for case in cases:
                outputs.append(self.execute_case(prepared, copy.deepcopy(case)))
            return [str(i) for i in range(len(cases))], outputs
        finally:
            registry.close()

    def run(self, spec: dict[str, Any], cases: list[dict[str, Any]], mutants: Iterable[RuleMutant]) -> MutationCampaign:
        if not cases:
            raise ValueError("mutation campaign requires at least one test case")
        _, baseline_outputs = self._run(spec, cases)
        baseline = [canonical_json(value) for value in baseline_outputs]
        results = []
        killed = survived = invalid = 0
        for mutant in mutants:
            mutated_spec = copy.deepcopy(spec)
            try:
                transformed = mutant.transform(mutated_spec)
                if transformed is not None:
                    mutated_spec = transformed
                _, outputs = self._run(mutated_spec, cases)
                candidate = [canonical_json(value) for value in outputs]
                failed = tuple(str(i) for i, (expected, actual) in enumerate(zip(baseline, candidate, strict=True)) if expected != actual)
                if failed:
                    killed += 1
                    results.append(MutationResult(mutant.mutant_id, mutant.operator, "killed", failed))
                else:
                    survived += 1
                    results.append(MutationResult(mutant.mutant_id, mutant.operator, "equivalence_candidate", ()))
            except Exception as exc:
                invalid += 1
                results.append(MutationResult(mutant.mutant_id, mutant.operator, "invalid_mutant", (), type(exc).__name__))
        denominator = killed + survived
        score = killed / denominator if denominator else 1.0
        return MutationCampaign(len(cases), killed, survived, invalid, score, tuple(results))
