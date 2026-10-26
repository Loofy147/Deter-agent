# Runtime Engine Specification

## Purpose
The Runtime Engine executes deterministic agents in a controlled way. It loads the correct agent version, validates inputs, enforces permissions, manages state, executes actions, verifies outputs, and writes traces.

The Runtime Engine is the operational core of the system.

---

## 1. Runtime design principle

```text
Execution must be repeatable, observable, permissioned, and rollback-safe.
```

An agent should not directly control its environment. It should request actions through the Runtime Engine and Tool Gateway.

---

## 2. Runtime architecture

```text
[Job Intake]
    ↓
[Queue]
    ↓
[Runtime Orchestrator]
    ↓
[Registry Lookup]
    ↓
[Input Normalizer]
    ↓
[Validator]
    ↓
[State Manager]
    ↓
[Decision Runner]
    ↓
[Permission Gateway]
    ↓
[Tool Executor]
    ↓
[Verifier]
    ↓
[Trace Logger]
    ↓
[Metrics Collector]
```

---

## 3. Runtime job schema

```json
{
  "job_id": "string",
  "request_id": "string",
  "agent_id": "string",
  "agent_version": "string|null",
  "environment": "sandbox|staging|production",
  "input": {},
  "requested_by": "string",
  "priority": "low|medium|high",
  "created_at": "timestamp"
}
```

`request_id` is the stable logical request identity and persists across resubmissions. The runtime derives the idempotency key after an `action_id` is selected; callers cannot supply it. A null `agent_version` resolves through `env_pointers(agent_id, environment)`.

## 4. Execution cycle

```text
1. Receive job
2. Load agent spec from registry
3. Check job is allowed in environment
4. Normalize input
5. Validate input schema
6. Load state
7. Execute deterministic decision logic
8. Check selected action against permission policy
9. Execute action through Tool Gateway
10. Verify result
11. Persist output and state
12. Write trace and metrics
13. Return response
```

---

## 5. Runtime state model

States: `queued`, `started`, `normalizing`, `validating`, `loading_state`, `deciding`, `checking_permissions`, `approval_pending`, `executing`, `verifying`, `completed`, `failed`, `rejected`, `escalated`.

| Current state | Permitted next states |
|---|---|
| queued | started, rejected, failed, escalated |
| started | normalizing, rejected, failed, escalated |
| normalizing | validating, rejected, failed, escalated |
| validating | loading_state, rejected, failed, escalated |
| loading_state | deciding, failed, escalated |
| deciding | checking_permissions, rejected, failed, escalated |
| checking_permissions | approval_pending, executing, rejected, failed, escalated |
| approval_pending | executing, rejected, escalated |
| executing | executing (one retry only), verifying, failed, escalated |
| verifying | completed, failed, escalated |

Terminal states `completed`, `failed`, `rejected`, and `escalated` are absorbing. Approval resume reuses an immutable frozen decision record and must not re-run the decision function.

## 6. Decision runner

The Decision Runner executes the deterministic policy logic for an agent.

Supported logic types:
- ordered rules
- decision tables
- finite-state machines
- workflow graphs
- deterministic scoring
- constraint checks

Decision output format:

```json
{
  "decision_id": "string",
  "matched_rule_id": "string",
  "action": "string",
  "action_input": {},
  "expected_result": {},
  "reason": "string",
  "risk_level": "low|medium|high|critical"
}
```

The Decision Runner may select exactly one action. If multiple actions match, it must apply the agent's tie-break policy.

---

## 7. Permission Gateway

Before execution, every selected action passes through the Permission Gateway.

Inputs:
- agent ID
- agent version
- environment
- requested action
- requested tool
- target resource
- risk level resolved from the versioned tool/resource catalog (never caller-supplied)
- data class resolved from the versioned resource catalog
- action-catalog version

Possible decisions:

```text
allow
deny
require_approval
sandbox_only
mock_only
```

If the result is `require_approval`, the Runtime Engine pauses execution and creates an approval event.

---

## 8. Tool Executor

The Tool Executor performs allowed external actions.

Responsibilities:
- enforce idempotency keys
- prevent duplicate side effects
- redact sensitive values from logs
- return structured results
- classify tool failures

Tool result format:

```json
{
  "tool_call_id": "string",
  "tool_name": "string",
  "status": "success|failed|timeout|blocked",
  "result": {},
  "error": null,
  "started_at": "timestamp",
  "completed_at": "timestamp"
}
```

---

## 9. Verification

Verification checks whether execution matched the decision's expected result.

Verification result:

```json
{
  "verified": true,
  "checks": [
    {
      "name": "schema_match",
      "status": "passed"
    }
  ],
  "reason": "All checks passed."
}
```

Required verification checks:
- output schema valid
- state transition valid
- side effect confirmed if applicable
- policy constraints preserved

---

## 10. Retry model

Retries must be deterministic.

| Failure type | Retry? | Rule |
|---|---:|---|
| Validation failure | No | Reject |
| Permission denied | No | Reject or request approval |
| Tool timeout | Yes | Retry once with same idempotency key |
| Tool permanent error | No | Fail or escalate |
| Verification failure | Sometimes | Retry only if action is idempotent |
| State conflict | No | Escalate |

---

## 11. Idempotency model

Every external side effect should use an idempotency key:

```text
idempotency_key = sha256(jcs([agent_id, version, spec_hash, request_id, action_id]))
```

This prevents duplicate task creation, duplicate messages, or repeated state changes during retries.

---

## 12. Runtime pseudocode

```python
def run_job(job):
    trace = create_trace(job)
    outcome = None
    try:
        spec = registry.resolve_version(job.agent_id, job.agent_version, job.environment)
        ref_snapshot, ref_version = reference_data.snapshot(spec.reference_data_refs)
        state, state_version = state_store.load_with_version(job.agent_id, job.request_id)
        normalized = normalize_nfc_and_sort(job.input, spec.input_schema)
        validation = validate(normalized, spec.input_schema, additional_properties=False)
        if not validation.ok:
            outcome = reject(job, "INPUT_VALIDATION_FAILED", validation.reason)
            return outcome

        decision = decision_runner.run(spec, normalized, state, ref_snapshot, normalized["received_at"])
        action_id = decision.action_id
        key = sha256(jcs([job.agent_id, spec.version, spec.spec_hash, job.request_id, action_id]))
        permission = permission_gateway.check(
            agent_id=job.agent_id, version=spec.version, environment=job.environment,
            action=decision.action, action_input=decision.action_input,
            target_resource=decision.target_resource
        )
        if permission.decision == "deny":
            outcome = reject(job, "POLICY_DENIED", permission.reason)
            return outcome
        if permission.decision == "sandbox_only" and job.environment != "sandbox":
            outcome = reject(job, "POLICY_DENIED", "Action is sandbox-only")
            return outcome
        if permission.decision == "require_approval":
            frozen = freeze_decision_record(
                decision, spec.spec_hash, state_version, ref_version, key
            )
            outcome = pause_for_approval(job, frozen, permission)
            return outcome

        adapter = mock_adapter if permission.decision == "mock_only" else live_adapter
        result = tool_executor.execute(adapter, decision.action, decision.action_input, key)
        verification = verifier.verify(result, decision.expected_result, spec.output_schema)
        if not verification.ok:
            outcome = fail(job, "VERIFICATION_FAILED", verification.reason)
            return outcome
        if not state_store.compare_and_swap(
            job.agent_id, job.request_id, state_version, verification.state
        ):
            outcome = escalate(job, "STATE_VERSION_CONFLICT")
            return outcome
        outcome = complete(job, decision, result, verification)
        return outcome
    except Exception as exc:
        outcome = fail(job, "UNKNOWN_RUNTIME_ERROR", sanitize(exc))
        return outcome
    finally:
        trace_logger.write_redacted(trace, job, outcome)
        metrics_collector.record_terminal_or_paused(job, outcome)
```

Every exit path, including validation rejection, permission denial, approval pause, tool failure, state conflict and exception, finalizes trace and metrics in `finally`. The gateway derives risk and data class from the versioned resource/tool catalog. Unknown tools deny, log and increment `unauthorized_tool_attempt_count`. Retry at most once only if both `idempotent` and `supports_idempotency_key` are true; reuse the derived key. `mock_only` must never fall through to a live adapter.

## 13. Runtime environments

| Environment | External side effects | Purpose |
|---|---|---|
| sandbox | Blocked or mocked by default | Safe testing |
| staging | Limited, controlled side effects | Pre-production validation |
| production | Allowed by policy | Live operation |

---

## 14. Error classes

```text
INPUT_VALIDATION_ERROR
STATE_TRANSITION_ERROR
POLICY_DENIED
APPROVAL_REQUIRED
TOOL_TIMEOUT
TOOL_PERMANENT_FAILURE
VERIFICATION_FAILURE
REGISTRY_LOOKUP_FAILURE
UNKNOWN_RUNTIME_ERROR
```

Each error class must have a deterministic handling path.

---

## 15. Runtime output schema

```json
{
  "job_id": "string",
  "agent_id": "string",
  "agent_version": "string",
  "status": "completed|rejected|failed|escalated|approval_required",
  "decision": "string",
  "action": "string",
  "reason": "string",
  "result": {},
  "trace_id": "string",
  "started_at": "timestamp",
  "completed_at": "timestamp"
}
```

---

## 16. Runtime guardrails

- Runtime loads agent specs only from the registry.
- Runtime does not execute unregistered agents.
- Runtime does not allow agents to bypass the Permission Gateway.
- Runtime does not write production state from sandbox runs.
- Runtime does not retry non-idempotent actions automatically.
- Runtime logs every decision and every external action.

---

## Summary
The Runtime Engine is the controlled execution layer for deterministic agents. It ensures agents run with explicit versions, valid inputs, known state, enforced permissions, verified outputs, and complete traces.


## 17. Normative deterministic-control contract

**Normative source:** [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json). These rules supersede conflicting examples above.

- Intake requires a stable logical `request_id`. The runtime creates the idempotency key after the decision assigns `action_id`: `sha256(jcs([agent_id, version, spec_hash, request_id, action_id]))`. Never key on `job_id` or wall-clock values.
- Before deciding, snapshot all reference data and record `reference_data_version`, `spec_hash`, `engine_version`, the selected rule-set hash, policy version, action-catalog version, `state_version`, and `input.received_at`. A state write must use compare-and-swap against the exact `state_version` read; on conflict, do not overwrite—escalate and trace it.
- Use NFC Unicode normalization, sorted object keys and rule evaluation, integer minor units for money, and per-intent JSON Schema with `additionalProperties: false`. Unknown fields are rejected.
- Complete the runtime FSM with `approval_pending`. On approval, resume from the frozen immutable decision record; do not re-run the decision function. Terminal states `completed`, `failed`, `rejected`, and `escalated` are absorbing.
- `deny` rejects and logs; `require_approval` freezes the decision and pauses; `sandbox_only` can execute only inside sandbox; `mock_only` routes exclusively to a mock/dry-run adapter. Unknown or unlisted runtime tools always deny, log, and increment `unauthorized_tool_attempt_count`.
- The gateway derives data class and risk from a versioned resource/tool catalog, never caller-supplied `data_class` or `risk_level`. The action catalog must declare both `idempotent` and `supports_idempotency_key`; retry at most once only when both are true, reusing the same key.
- Every exit path—including rejection, escalation, approval pause, timeout, and exception—must finalize the trace and metrics through `try/finally`. Redaction occurs before trace persistence.


### Approval resume path

```python
def resume_approved_job(frozen_decision, approval_event):
    require_approval_matches(
        approval_event,
        agent_id=frozen_decision.agent_id,
        version=frozen_decision.version,
        environment=frozen_decision.environment,
        spec_hash=frozen_decision.spec_hash,
        decision_id=frozen_decision.decision_id,
        policy_diff_hash=frozen_decision.policy_diff_hash,
        not_expired=True,
        approver_differs_from_requester=True,
    )
    # Resume the immutable decision; never run decision_runner again.
    return execute_frozen_decision(frozen_decision)
```

`input.received_at` is the submitted, schema-validated timestamp used for any timestamp-based business tie-break; engine wall-clock timestamps are observational metadata, never decision inputs.
