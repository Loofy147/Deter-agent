"""Evaluation harness with hard component floors and cross-process replay checks."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any, Callable

from .canonical import canonical_json, normalize_json, sha256_json
from .registry import Registry, RegistryError
from .rules import Rule, RuleSet

HARD_COMPONENTS = (
    "determinism_score", "regression_score", "policy_score", "schema_score",
    "state_transition_score", "tie_break_score", "failure_path_score",
)
TEST_COMPONENT = {
    "determinism": "determinism_score",
    "regression": "regression_score",
    "policy": "policy_score",
    "schema": "schema_score",
    "state_transition": "state_transition_score",
    "tie_break": "tie_break_score",
    "failure_path": "failure_path_score",
}


def _without_fields(value: Any, ignored: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: _without_fields(item, ignored) for key,item in value.items() if key not in ignored}
    if isinstance(value, list):
        return [_without_fields(item, ignored) for item in value]
    return value


class EvaluationHarness:
    def __init__(self, registry: Registry, *, engine_version: str = "0.1.0"):
        self.registry = registry
        self.engine_version = engine_version

    def evaluate(
        self, *, suite_id: str, agent_id: str, version: str, policy_version: str,
        execute: Callable[[dict[str, Any]], Any], created_by: str, now: float | None = None
    ) -> dict[str, Any]:
        start = now if now is not None else time.time()
        suite_row = self.registry.get_evaluation_suite(suite_id)
        suite = suite_row["suite"]
        target = self.registry.get_version(agent_id, version)
        if suite_row["agent_id"] != agent_id or suite_row["version"] != version:
            raise RegistryError("suite target mismatch")
        test_results = []
        component_results: dict[str, list[bool]] = {name: [] for name in HARD_COMPONENTS}
        all_required_pass = True
        covered_types = set()
        for case in suite["tests"]:
            test_type = case.get("test_type")
            if test_type not in TEST_COMPONENT:
                raise RegistryError(f"unsupported test type {test_type!r}")
            covered_types.add(test_type)
            repeats = case.get("repeat_count", 1) if test_type == "determinism" else 1
            outputs = []
            started = time.perf_counter()
            error = None
            for _ in range(repeats):
                try:
                    outputs.append(normalize_json(execute(case)))
                except Exception as exc:
                    error = type(exc).__name__
                    break
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            passed = error is None and bool(outputs)
            ignored = set(case.get("ignored_fields", []))
            if passed and test_type == "determinism":
                passed = all(canonical_json(_without_fields(outputs[0], ignored)) == canonical_json(_without_fields(out, ignored)) for out in outputs[1:])
            if passed and "expected_output" in case:
                expected = _without_fields(case["expected_output"], ignored)
                actual = _without_fields(outputs[-1], ignored)
                passed = canonical_json(actual) == canonical_json(expected)
            if passed and case.get("expected_reason_code") is not None:
                passed = outputs[-1].get("reason_code") == case["expected_reason_code"]
            component = TEST_COMPONENT[test_type]
            component_results[component].append(bool(passed))
            required = case.get("required", True)
            if required and not passed:
                all_required_pass = False
            test_results.append({
                "test_id": case.get("test_id", f"test-{len(test_results)+1}"),
                "test_type": test_type, "component": component,
                "passed": bool(passed), "required": bool(required),
                "error_code": error, "elapsed_ms": round(elapsed_ms, 3),
                "output_hash": sha256_json(outputs[-1]) if outputs else None,
            })

        component_scores = {}
        for component in HARD_COMPONENTS:
            results = component_results[component]
            component_scores[component] = (sum(results) / len(results)) if results else 0.0
        thresholds = suite.get("thresholds", {})
        performance_floor = float(thresholds.get("minimum_performance_score", 0.0))
        performance_observed = float(suite.get("performance_score", 1.0))
        component_scores["performance_score"] = performance_observed
        floors_met = all(component_scores[name] == 1.0 for name in HARD_COMPONENTS) and performance_observed >= performance_floor

        required_coverage = set(suite.get("required_test_types", list(TEST_COMPONENT)))
        coverage_complete = required_coverage.issubset(covered_types)
        # Any hard component without a test means evidence is missing, even if suite author omitted coverage metadata.
        coverage_complete = coverage_complete and all(component_results[name] for name in HARD_COMPONENTS)

        weights = {
            "determinism_score": .20, "regression_score": .20, "policy_score": .20,
            "schema_score": .10, "state_transition_score": .10, "tie_break_score": .10,
            "failure_path_score": .05, "performance_score": .05,
        }
        composite = sum(component_scores[k] * w for k,w in weights.items())
        status = "passed" if all_required_pass and floors_met and coverage_complete else "failed"
        completed_at = now if now is not None else time.time()
        run_id = suite.get("evaluation_run_id") or f"EVAL-{sha256_json([agent_id,version,target['spec_hash'],suite_row['suite_hash'],start])[:16]}"
        report = {
            "run_id": run_id, "agent_id": agent_id, "version": version, "spec_hash": target["spec_hash"],
            "suite_id": suite_id, "suite_hash": suite_row["suite_hash"], "policy_version": policy_version,
            "engine_version": self.engine_version, "status": status, "floors_met": floors_met,
            "coverage_complete": coverage_complete, "component_scores": component_scores,
            "score": round(composite, 6), "results": test_results, "started_at": start,
            "completed_at": completed_at, "created_by": created_by,
        }
        self.registry.record_evaluation(
            run_id=run_id, agent_id=agent_id, version=version, spec_hash=target["spec_hash"],
            suite_id=suite_id, policy_version=policy_version, engine_version=self.engine_version,
            status=status, floors_met=floors_met, coverage_complete=coverage_complete,
            component_scores=component_scores, score=composite, results=test_results, created_by=created_by,
            started_at=start, completed_at=completed_at,
        )
        return report

    @staticmethod
    def cross_process_rule_replay(rules: list[dict[str, Any]], input_value: dict[str, Any], *, processes: int = 8) -> dict[str, Any]:
        if processes < 2 or processes > 100:
            raise ValueError("processes must be between 2 and 100")
        outputs = []
        base = {"rules": rules, "input": input_value}
        for seed in range(processes):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = str(seed)
            # Reversed key order in each process exercises dict-order independence.
            payload = {"input": input_value, "rules": rules} if seed % 2 else base
            run = subprocess.run(
                [sys.executable, "-m", "deter_agent.replay_worker"],
                input=canonical_json(payload), text=True, capture_output=True, env=env, timeout=10,
            )
            if run.returncode != 0:
                raise RuntimeError(f"replay worker failed: {run.stderr.strip()}")
            outputs.append(run.stdout.strip())
        unique = sorted(set(outputs))
        return {"processes": processes, "consistent": len(unique) == 1, "unique_outputs": len(unique), "output_hashes": [sha256_json(x) for x in unique], "output": unique[0] if len(unique) == 1 else None}
