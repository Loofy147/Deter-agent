# Agent Factory Build Template

## Purpose
This template is used by the agentic system to build new deterministic agents in a controlled, repeatable way.

Use it whenever a new agent is needed.

---

## 1. New agent request

```yaml
request_id: AGENT-BUILD-001
requested_by: user_or_system
agent_name: "[Name]"
problem_to_solve: "[What problem should the agent solve?]"
expected_users:
  - "[User group]"
expected_environment: sandbox
```

---

## 2. Purpose and success criteria

### Purpose
```text
[Describe the exact job of the agent.]
```

### Success criteria

| Criterion | Target |
|---|---:|
| Success rate | >= 95% |
| Consistency rate | 100% |
| Policy violations | 0 |
| Human override rate | <= 5% |
| Average latency | <= target threshold |

---

## 3. Scope

### In scope
- `[Supported task]`
- `[Supported input type]`
- `[Supported output/action]`

### Out of scope
- `[Unsupported task]`
- `[High-risk action]`
- `[Ambiguous case]`

---

## 4. Framework selection

Choose one primary framework.

| Need | Framework |
|---|---|
| Simple explicit logic | Rule-based system |
| Many condition combinations | Decision table |
| Strict lifecycle | Finite-state machine |
| Multi-step operations | Workflow engine |
| Hard constraints | Constraint-based system |
| Ranking/prioritization | Deterministic scoring |
| Real-world production system | Hybrid rule + workflow |

### Selected framework
```yaml
framework: "[Selected framework]"
reason: "[Why this framework fits]"
```

---

## 5. Input schema

```json
{
  "request_id": "string",
  "timestamp": "string",
  "source": "string",
  "intent": "string",
  "payload": {},
  "constraints": [],
  "priority": "low|medium|high"
}
```

### Required fields
- request_id
- timestamp
- source
- intent
- payload

---

## 6. Output schema

```json
{
  "status": "completed|pending|rejected|escalated|failed",
  "decision": "string",
  "action": "string",
  "reason": "string",
  "trace_id": "string",
  "agent_id": "string",
  "agent_version": "string"
}
```

---

## 7. State model

### Allowed states
```text
created
configured
validated
sandbox_ready
tested
approved
deployed
monitored
retired
```

### Runtime states
```text
received
normalized
validated
classified
decided
executed
verified
completed
failed
escalated
```

---

## 8. Decision rules

Use this format for every rule.

```yaml
rule_id: RULE-001
name: "[Rule name]"
condition: "[Exact condition]"
action: "[Exact action]"
priority: 1
tie_break_group: "[Optional]"
reason: "[Why this rule exists]"
policy_version: "v1.0.0"
```

### Required rule types
- validation rule
- primary routing/decision rule
- fallback rule
- escalation rule
- policy violation rule

---

## 9. Tie-break policy

When multiple rules match, resolve in this order:

1. highest rule priority
2. most specific condition
3. lowest risk action
4. earliest timestamp
5. lexical order by action ID

---

## 10. Tool and permission model

```yaml
permissions:
  read:
    - "[Allowed data source]"
  write:
    - "[Allowed destination]"
  external_actions:
    - "[Allowed tool/action]"
  blocked:
    - "[Blocked tool/action]"
approval_required_for:
  - production_deploy
  - external_message_send
  - permission_expansion
  - destructive_action
```

---

## 11. Evaluation suite

### Required tests

| Test ID | Test type | Purpose |
|---|---|---|
| TEST-001 | Determinism | Same input/state gives same output |
| TEST-002 | Validation | Invalid input is rejected predictably |
| TEST-003 | Regression | Old required behavior still works |
| TEST-004 | Policy | Agent does not violate permissions |
| TEST-005 | Tie-break | Multiple valid actions resolve consistently |
| TEST-006 | Failure path | Dependency failure follows expected path |

### Test case format

```yaml
test_id: TEST-001
input: {}
state: {}
expected_output: {}
repeat_count: 10
pass_condition: "All outputs exactly match expected_output."
```

---

## 12. Build workflow

```text
1. Capture request
2. Define purpose and scope
3. Select framework
4. Define schemas
5. Define state model
6. Define rules and tie-breaks
7. Define tools and permissions
8. Generate evaluation suite
9. Build sandbox version
10. Run tests
11. Register agent
12. Request deployment approval
13. Deploy if approved
14. Monitor metrics
```

---

## 13. Agent registry entry

```yaml
agent_id: "agent-[slug]"
name: "[Agent name]"
version: "v1.0.0"
status: "sandbox|staging|production|retired"
owner: "[Owner]"
framework: "[Selected framework]"
purpose: "[Purpose]"
input_schema: "[Reference]"
output_schema: "[Reference]"
policy_version: "v1.0.0"
evaluation_suite: "[Reference]"
allowed_tools: []
created_at: "[Timestamp]"
last_reviewed_at: "[Timestamp]"
```

---

## 14. Deployment checklist

- [ ] Purpose is clear
- [ ] Scope is bounded
- [ ] Input schema exists
- [ ] Output schema exists
- [ ] State model exists
- [ ] Rules are ordered
- [ ] Tie-breaks are explicit
- [ ] Permissions are minimal
- [ ] Evaluation suite exists
- [ ] Determinism tests pass
- [ ] Regression tests pass
- [ ] Policy checks pass
- [ ] Rollback version exists
- [ ] Approval completed

---

## 15. Improvement hooks

Every new agent must expose:

```yaml
metrics:
  - success_rate
  - consistency_rate
  - failure_rate
  - escalation_rate
  - override_rate
  - average_latency
  - policy_violation_count
logs:
  - input_trace
  - decision_trace
  - action_trace
  - verification_trace
improvement_enabled: true
improvement_mode: recommend_then_sandbox
```

---

## Summary
This template turns the system into an agent factory. It lets the agentic system build new deterministic agents while preserving control, testing, permissions, and auditability.
