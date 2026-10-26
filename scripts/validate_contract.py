#!/usr/bin/env python3
"""Validate the normative Deter-agent contract using only the Python standard library."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "deterministic-control-contract.json"
errors: list[str] = []

def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)

try:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"FAIL: cannot load {CONTRACT_PATH}: {exc}", file=sys.stderr)
    raise SystemExit(1)

enums = contract.get("enums", {})
for name, values in enums.items():
    check(isinstance(values, list) and bool(values), f"enum {name} must be a non-empty list")
    check(len(values) == len(set(values)), f"enum {name} contains duplicate values")

expected_frameworks = {
    "rule_based", "decision_table", "finite_state_machine", "workflow_engine",
    "constraint_based", "deterministic_scoring", "hybrid_rule_workflow",
}
check(set(enums.get("framework", [])) == expected_frameworks, "framework enum drift")

rule_order = contract.get("rule_resolution", {})
check(
    rule_order.get("order") == ["priority ASC", "specificity DESC", "risk_rank ASC", "rule_id ASC"],
    "rule resolution order is not the canonical total order",
)
check(rule_order.get("priority_may_repeat") is True, "equal-priority cases must remain testable")
check(rule_order.get("required_unique_field") == "rule_id", "rule_id uniqueness is required")

promotion = contract.get("promotion", {})
required_binding = {
    "agent_id", "version", "target_environment", "spec_hash",
    "eval_run_id", "approval_event_id", "policy_diff_hash",
}
check(set(promotion.get("binding_fields", [])) == required_binding, "promotion binding fields incomplete or unexpected")
check(promotion.get("evaluation_must_match_spec_hash") is True, "evaluation must bind to spec_hash")
check(promotion.get("approval_must_be_unexpired") is True, "approval expiry must be checked")
check(promotion.get("approver_must_differ_from_requester") is True, "separation of duties missing")
check(promotion.get("stage_skipping_allowed") is False, "stage skipping must be denied")
check(promotion.get("permission_expansion_requires_scope") == "permission_change", "permission expansion approval scope missing")

registry = contract.get("registry", {})
check(set(registry.get("agents_table_excludes", [])) == {"status", "current_version"}, "per-agent status/current_version must be removed")
check(registry.get("environment_pointer_table", {}).get("key") == ["agent_id", "environment"], "environment pointer key must be per agent/environment")
check(registry.get("version_policy_join_table", {}).get("key") == ["version_id", "environment"], "version policy must be per version/environment")
for field in ["spec_hash", "suite_hash", "policy_version", "engine_version"]:
    check(field in registry.get("required_evaluation_binding_fields", []), f"evaluation_runs missing {field}")
for field in ["spec_hash", "eval_run_id", "expires_at", "policy_diff_hash", "scope"]:
    check(field in registry.get("required_approval_binding_fields", []), f"approval_events missing {field}")
for table in ["evaluation_runs", "approval_events", "traces", "promotion_records"]:
    check(table in registry.get("append_only_tables", []), f"{table} must be append-only")

runtime = contract.get("runtime", {})
states = set(runtime.get("states", []))
terminals = set(runtime.get("terminal_states", []))
check(terminals == {"completed", "failed", "rejected", "escalated"}, "terminal-state set drift")
transitions = runtime.get("transitions", {})
for terminal in terminals:
    check(terminal not in transitions, f"terminal state {terminal} has outgoing transitions")
for source, targets in transitions.items():
    check(source in states, f"transition source {source} is not a declared state")
    for target in targets:
        check(target in states, f"transition target {target} is not a declared state")
check("approval_pending" in states, "approval_pending state missing")
check("approval_pending" in transitions.get("checking_permissions", []), "permission-to-approval transition missing")
check("executing" in transitions.get("approval_pending", []), "approval resume transition missing")
check(runtime.get("decision_frozen_across_approval_pause") is True, "approval resume must use frozen decision")
check(runtime.get("trace_and_metrics_finalization", "").startswith("try_finally"), "trace/metrics finalization must cover all paths")
check(runtime.get("policy_decision_behavior", {}).get("sandbox_only") is not None, "sandbox_only runtime behavior missing")
check(runtime.get("policy_decision_behavior", {}).get("mock_only") == "use_mock_adapter_never_live_adapter", "mock_only must never fall through to live adapter")
check(runtime.get("unknown_or_unlisted_tool", "").startswith("deny_log"), "unknown runtime tools must default-deny")

idempotency = contract.get("idempotency", {})
check(idempotency.get("request_id") == "stable_logical_request_id_required_at_intake", "stable logical request_id must be required at intake")
check(idempotency.get("formula") == "sha256(jcs([agent_id, version, spec_hash, request_id, action_id]))", "idempotency formula drift")
check(set(idempotency.get("catalog_required_fields", [])) == {"idempotent", "supports_idempotency_key"}, "action catalog retry fields missing")
check(idempotency.get("maximum_retries") == 1, "retry limit must be one retry")
check("job_id" in idempotency.get("excludes", []), "job_id must not be part of idempotency identity")

replay = set(contract.get("replay_tuple", []))
for field in ["reference_data_version", "state_version", "spec_hash", "engine_version", "input.received_at"]:
    check(field in replay, f"replay tuple missing {field}")

evaluation = contract.get("evaluation", {})
floors = evaluation.get("hard_component_floors", {})
required_floors = {
    "determinism_score", "regression_score", "policy_score", "schema_score",
    "state_transition_score", "tie_break_score", "failure_path_score",
}
check(set(floors) == required_floors, "evaluation component floor coverage incomplete")
check(all(value == 1.0 for value in floors.values()), "hard component floors must all equal 1.0")
check(evaluation.get("composite_score") == "informational_only_not_a_substitute_for_component_floors", "composite must not replace hard floors")
check(evaluation.get("coverage_check_on_attach") is True, "coverage matrix must be checked on suite attach")
check(evaluation.get("evaluation_status_error_is_never_pass") is True, "evaluation error must never pass")

deployment = contract.get("deployment", {})
check(deployment.get("stage_order", []) == ["draft", "sandbox", "evaluation", "review", "staging", "production", "monitoring", "retired"], "deployment stage order drift")
check(deployment.get("random_assignment") is False, "canary allocation must be deterministic")
check(deployment.get("rollback_must_target_previously_approved_version", True) is True, "rollback target must be previously approved")

checks = set(contract.get("static_checks", []))
for required in [
    "rule_shadowing", "decision_table_totality_and_overlap", "each_operation_has_a_rule",
    "every_agent_has_an_explicit_fallback_rule", "fsm_reachability_and_dead_ends",
    "terminal_states_are_absorbing", "promotion_binding_is_complete",
    "approval_binding_and_expiry", "append_only_audit_tables",
]:
    check(required in checks, f"static check missing: {required}")

metrics = contract.get("metrics", {})
dictionary = metrics.get("dictionary", {})
check(metrics.get("canonical_determinism_metric") == "determinism_rate", "canonical determinism metric drift")
check(not (set(metrics.get("forbidden_legacy_aliases", [])) & set(dictionary)), "legacy metric alias must not be canonical")
for name, definition in dictionary.items():
    check(bool(definition.get("formula")) and bool(definition.get("window")), f"metric {name} must define formula and window")

manifest = ROOT / "agentic-system-manifest.yaml"
check(manifest.exists(), "canonical YAML manifest missing")
check(not (ROOT / "agentic-system-manifest.yaml.txt").exists(), "old manifest filename remains")
check(not (ROOT / "agentic-system-manifest.yaml (1).txt").exists(), "duplicate manifest remains")
if manifest.exists():
    raw = manifest.read_text(encoding="utf-8")
    for framework in sorted(expected_frameworks):
        check(f"  {framework}:" in raw, f"manifest missing canonical framework {framework}")
    check("production_changes_allowed:" not in raw, "mixed boolean/string approval field remains")
    check("approval_requirement:" in raw, "approval requirement enum is not used")
    check("same_input_same_output_rate" not in raw and "consistency_rate" not in raw, "legacy determinism metric alias remains in manifest")

readme_path = ROOT / "agentic-system-readme.md"
if readme_path.exists():
    readme = readme_path.read_text(encoding="utf-8")
    marker = "Implement in dependency order:"
    marker_position = readme.find(marker)
    check(marker_position >= 0, "README missing corrected build-order heading")
    if marker_position >= 0:
        fenced = readme.find("```text", marker_position)
        closing = readme.find("```", fenced + len("```text")) if fenced >= 0 else -1
        check(fenced >= 0 and closing > fenced, "README missing fenced build-order sequence")
        block = readme[fenced + len("```text"):closing] if fenced >= 0 and closing > fenced else ""
        required_order = [
            "canonicalization + shared enums",
            "registry with static checks",
            "permission gateway deny-all stub",
            "runtime",
            "evaluation harness",
            "deployment gate",
            "operator-signed bootstrap seed",
            "first agents",
        ]
        positions = [block.find(item) for item in required_order]
        check(all(pos >= 0 for pos in positions), "README missing corrected build-order steps")
        check(positions == sorted(positions), "README build order is not dependency-correct")

for name in [
    "agent-registry-schema.md", "runtime-engine-spec.md", "permission-policy-spec.md",
    "deployment-pipeline-spec.md", "evaluation-harness-spec.md", "first-agent-example.md",
    "agent-factory-build-template.md",
]:
    path = ROOT / name
    if path.exists():
        check("DETERMINISTIC-CONTROL-CONTRACT.md" in path.read_text(encoding="utf-8"),
              f"{name} does not reference the normative contract")


# Validate actual decision rules, not only the checklist labels in the JSON contract.
registry_doc = ROOT / "agent-registry-schema.md"
first_doc = ROOT / "first-agent-example.md"
factory_doc = ROOT / "agent-factory-build-template.md"
improvement_doc = ROOT / "agentic-control-improvement-framework.md"
registry_text = registry_doc.read_text(encoding="utf-8")
first_text = first_doc.read_text(encoding="utf-8")
factory_text = factory_doc.read_text(encoding="utf-8")
improvement_text = improvement_doc.read_text(encoding="utf-8")

framework_line = re.search(r"(?m)^framework: ([a-z_]+(?:\|[a-z_]+)*)$", registry_text)
check(framework_line is not None, "registry does not define the canonical framework enum")
if framework_line:
    check(set(framework_line.group(1).split("|")) == expected_frameworks,
          "registry framework enum differs from contract")
factory_frameworks = set(re.findall(r"(?m)^\| [^|]+ \| `([a-z_]+)` \|$", factory_text))
check(factory_frameworks == expected_frameworks, "factory framework choices differ from contract")
check("policy_version: string" not in registry_text.split("### 3.2 `agent_versions`", 1)[-1].split("### 3.3", 1)[0],
      "agent_versions must not bind one policy_version across environments")
check("permission_policy_id" not in registry_text, "singleton permission_policy_id remains")
permission_table = registry_text.split("### 3.3 `permission_policies`", 1)[1].split("### 3.4", 1)[0] if "### 3.3 `permission_policies`" in registry_text else registry_text
check("max_autonomy_level" not in permission_table, "autonomy level must not be stored as a runtime permission column")
for alias in ["same_input_same_output_rate", "consistency_rate"]:
    check(alias not in factory_text and alias not in improvement_text,
          f"legacy determinism metric alias remains in docs: {alias}")

def parse_rule_table(block: str, label: str) -> list[tuple[str, int, str]]:
    matches = re.findall(r"(?ms)^  - rule_id: ([A-Z][A-Z0-9-]*)\s*\n(.*?)(?=^  - rule_id: |\Z)", block)
    parsed: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for rule_id, body in matches:
        check(rule_id not in seen, f"{label} contains duplicate rule_id {rule_id}")
        seen.add(rule_id)
        priority = re.search(r"(?m)^    priority: (\d+)\s*$", body)
        check(priority is not None, f"{label} rule {rule_id} has no integer priority")
        if priority:
            parsed.append((rule_id, int(priority.group(1)), body))
    check(bool(parsed), f"{label} rule table could not be parsed")
    check(any("condition: no previous rule matches" in body.lower() for _, _, body in parsed),
          f"{label} requires an explicit fallback rule")
    return parsed

reg_section = first_text.split("## 7. Decision rules", 1)[1].split("## 8. Tie-break policy", 1)[0]
reg_rules = parse_rule_table(reg_section, "Registry Manager")
reg_ops = {"register_agent", "create_version", "attach_evaluation", "record_evaluation", "record_proposal", "update_status"}
reg_condition_text = "\n".join(body for _, _, body in reg_rules)
for operation in sorted(reg_ops):
    check(f"operation = {operation}" in reg_condition_text, f"Registry Manager lacks rule for {operation}")
reg_priority = {rule_id: priority for rule_id, priority, _ in reg_rules}
check(reg_priority.get("REG-006", 10**9) < reg_priority.get("REG-004", -1),
      "production-mutation deny guard is shadowed by create-version allow")
check(reg_priority.get("REG-011", 10**9) < reg_priority.get("REG-004", -1),
      "production-environment deny guard is shadowed by create-version allow")

part2 = first_text.split("# Part 2: Evaluation Agent", 1)[1]
eval_section = part2.split("## 7. Decision rules", 1)[1].split("## 8. Permission policy", 1)[0]
eval_rules = parse_rule_table(eval_section, "Evaluation Agent")
eval_ids = {rule_id for rule_id, _, _ in eval_rules}
eval_condition_text = "\n".join(body for _, _, body in eval_rules).lower()
check({"EVAL-006", "EVAL-007", "EVAL-008", "EVAL-999"}.issubset(eval_ids),
      "Evaluation Agent lacks threshold-failure, error, missing-policy or fallback rules")
check("component floors fail" in eval_condition_text, "Evaluation Agent threshold-floor rule missing")
check("returns an error" in eval_condition_text and "mark_error" in eval_condition_text,
      "Evaluation Agent error path missing")
check("policy_id: evaluation-agent-staging-v1" in first_text,
      "Evaluation Agent accepts staging without a staging-specific policy")

# All defined runtime states must be reachable from queued.
if transitions:
    reachable = set()
    frontier = ["queued"]
    while frontier:
        node = frontier.pop()
        if node in reachable:
            continue
        reachable.add(node)
        frontier.extend(transitions.get(node, []))
    check(reachable == states, "runtime FSM has unreachable states: " + ", ".join(sorted(states - reachable)))

if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    print(f"{len(errors)} contract validation failure(s).", file=sys.stderr)
    raise SystemExit(1)

print("PASS: deterministic control contract and specification cross-references are valid.")
