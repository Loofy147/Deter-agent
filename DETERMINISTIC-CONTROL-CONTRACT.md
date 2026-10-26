# Deter-agent Deterministic Control Contract

Status: **Normative**
Contract version: **1.0.0**
Machine-readable source: [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json)

## Purpose and precedence

This document defines the binding lifecycle and execution rules for the Deterministic Agentic Control System. Where a legacy example conflicts with this contract, this contract and its machine-readable JSON take precedence. The registry stores the immutable identities and evidence; the evaluation harness produces evidence; the gateway enforces runtime scope; and the deployment pipeline validates the same promotion binding.

The promotion binding is:

```text
promotion_binding_hash =
  sha256(jcs({
    agent_id, version, target_environment,
    spec_hash, eval_run_id, approval_event_id, policy_diff_hash
  }))
```

Use RFC 8785 JSON Canonicalization Scheme (JCS) before hashing. A spec, evaluation, approval, policy diff, or environment mismatch denies promotion.

## Canonical identity and replay

- `spec_hash = sha256(jcs(immutable_agent_spec))`.
- Normalize strings to Unicode NFC, sort object keys and rule evaluation, represent money as integer minor units, and reject unknown fields with per-intent JSON Schema `additionalProperties: false`.
- Snapshot reference data before deciding and record its `reference_data_version`. Bind every decision to the immutable `spec_hash`, `engine_version`, `state_version`, selected rules, policy version, action-catalog version, and input-carried `received_at`.
- Writes use compare-and-swap against the `state_version` read. A state conflict never overwrites state; it is recorded and escalated.
- The replay tuple is stored in `contracts/deterministic-control-contract.json` and includes state, reference data, spec, and engine identity.

## Rule resolution

Resolve matching rules using exactly:

```text
(priority ASC, specificity DESC, risk_rank ASC, rule_id ASC)
```

Lower numeric priority wins. Specificity is the count of distinct fields constrained in the rule condition. Risk rank is ordered low, medium, high, critical. No timestamp or action-name ordering is permitted. Every agent must have an explicit fallback that rejects or escalates; no-match is never implicit allow.

**Design decision — equal priorities:** the earlier notes required both unique priorities and a meaningful equal-priority tie-break test. Those requirements conflict: unique priorities make specificity/risk/rule-ID tie-breaks unreachable on valid rule sets. This contract therefore requires unique `rule_id` values but allows equal priorities, resolved by the total order above. Static validation must test an equal-priority match and detect shadowing.

## Registry model

- Agent lifecycle is separate from environment version selection. Do not store a single `agents.status` or `agents.current_version`.
- Store active targets in `env_pointers(agent_id, environment, version_id, updated_at, updated_by)`.
- Store environment-specific policy bindings in `version_policies(version_id, environment, policy_id, policy_version, policy_hash)`.
- Evaluation evidence records `spec_hash`, `suite_hash`, `policy_version`, and `engine_version`.
- Approval evidence records the exact `spec_hash`, `eval_run_id`, `expires_at`, `policy_diff_hash`, and typed `scope`.
- Evaluation runs, approvals, traces, and promotion records are append-only. The suite author must differ from the target agent author.

## Gateway and runtime FSM

The runtime FSM includes `approval_pending`. On approval, resume from the immutable frozen decision record; never decide again. Terminal states `completed`, `failed`, `rejected`, and `escalated` are absorbing.

| Gateway decision | Runtime behavior |
|---|---|
| `allow` | Execute only within environment, tool and resource scope |
| `deny` | Reject, trace, record metrics |
| `require_approval` | Freeze decision and pause pending independent approval |
| `sandbox_only` | Reject outside sandbox |
| `mock_only` | Route exclusively to mock/dry-run adapter |

An unlisted runtime permission is denied, logged, and counted; do not send routine unauthorized calls to the approval queue. The gateway derives data class and risk from a versioned resource/tool catalog, never from caller-provided labels. All paths, including rejection and approval pause, finalize traces and metrics through `try/finally`.

The action catalog must define `idempotent` and `supports_idempotency_key`. A retry is allowed at most once and only when both are true. Intake requires a stable logical `request_id`, and the runtime derives:

```python
idempotency_key = sha256(jcs([agent_id, version, spec_hash, request_id, action_id]))
```

## Evaluation

The following component floors are hard gates: determinism, regression, policy, schema, state transitions, tie-breaks and failure paths must each score 1.00. Performance has an explicit suite-specific threshold. A composite score is informational and cannot mask any failed floor.

Determinism tests run in separate processes with varied `PYTHONHASHSEED` and shuffled key order. Test normalization idempotence (`normalize(normalize(x)) == normalize(x)`) and compare `reason_code` enums. Check suite coverage at attachment time, including operations, decision combinations, transitions, fallbacks, permission decisions, environments and error paths.

## Promotion and rollback

A promotion is allowed only when:

1. The version spec is immutable and its hash matches the evaluation run.
2. All required tests and component floors pass, and coverage is complete.
3. Stage order is respected; production requires verified staging for the same spec hash.
4. Staging and production approvals are approved, unexpired, independently requested, and bound to the exact agent/version/environment/spec/evaluation/policy diff.
5. Any permission expansion is covered by `permission_change` scope.
6. If a production pointer already exists, the target version has a rollback target that was previously approved.

Rollback is itself a production change. It may only target a previously approved version and must produce an append-only record. Canary cohorts are deterministic: `int(sha256(UTF8(request_id)).hexdigest(), 16) % 100`.

## Static validation and build order

Static validation must check canonical enum consistency, unique rule IDs, valid priority values, rule shadowing, decision-table totality/overlap, operation coverage, explicit fallback rules, FSM reachability and absorbing terminal states, environment-specific policy coverage, complete evaluation coverage, immutable promotion bindings, approval expiry, append-only records, and retry metadata.

Build in dependency order:

```text
canonicalization + shared enums
registry with static checks
permission gateway deny-all stub
runtime
evaluation harness
deployment gate
operator-signed bootstrap seed
first agents
```

Bootstrap records must be operator-signed and hash-pinned, use `created_by: bootstrap`, run only within the sandbox scope, and expire after build step 8.
