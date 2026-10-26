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
  "agent_id": "string",
  "agent_version": "string|null",
  "environment": "sandbox|staging|production",
  "input": {},
  "requested_by": "string",
  "priority": "low|medium|high",
  "idempotency_key": "string",
  "created_at": "timestamp"
}
```

If `agent_version` is null, the Runtime Engine loads the current version for the requested environment.

---

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

Each run has a runtime state:

```text
queued
started
normalizing
validating
loading_state
deciding
checking_permissions
executing
verifying
completed
failed
rejected
escalated
```

### Allowed transitions

| Current state | Next state |
|---|---|
| queued | started |
| started | normalizing |
| normalizing | validating |
| validating | loading_state |
| validating | rejected |
| loading_state | deciding |
| deciding | checking_permissions |
| checking_permissions | executing |
| checking_permissions | rejected |
| executing | verifying |
| executing | failed |
| verifying | completed |
| verifying | failed |
| any | escalated |

---

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
- risk level

Possible decisions:

```text
allow
deny
require_approval
sandbox_only
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
idempotency_key = hash(agent_id + version + job_id + action_id + normalized_input)
```

This prevents duplicate task creation, duplicate messages, or repeated state changes during retries.

---

## 12. Runtime pseudocode

```python
def run_job(job):
    trace = create_trace(job)

    spec = registry.get_agent_version(
        agent_id=job.agent_id,
        version=job.agent_version,
        environment=job.environment
    )

    normalized = normalize(job.input, spec.input_schema)
    validation = validate(normalized, spec.input_schema)
    if not validation.ok:
        return reject(job, validation.reason, trace)

    state = state_store.load(job.agent_id, job.job_id)
    decision = decision_runner.run(spec, normalized, state)

    permission = permission_gateway.check(
        agent_id=job.agent_id,
        version=spec.version,
        environment=job.environment,
        action=decision.action,
        action_input=decision.action_input
    )

    if permission.decision == "deny":
        return reject(job, permission.reason, trace)

    if permission.decision == "require_approval":
        return pause_for_approval(job, decision, permission, trace)

    result = tool_executor.execute(
        action=decision.action,
        action_input=decision.action_input,
        idempotency_key=job.idempotency_key
    )

    verification = verifier.verify(result, decision.expected_result, spec.output_schema)
    final_output = build_output(decision, result, verification)

    state_store.save(job.agent_id, job.job_id, final_output.state)
    trace_logger.write(trace, decision, result, verification)
    metrics_collector.record(job, final_output)

    return final_output
```

---

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
