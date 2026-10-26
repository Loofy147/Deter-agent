# Evaluation Harness Specification

## Purpose
The Evaluation Harness tests agents before and after changes. It ensures that new agents and improved agents are deterministic, correct, policy-compliant, and safe to deploy.

No agent should move from sandbox to staging or production without passing its required evaluation suite.

---

## 1. Evaluation principle

```text
If an agent cannot be tested, it cannot be safely improved or deployed.
```

---

## 2. Evaluation architecture

```text
[Test Suite Loader]
       ↓
[Test Case Runner]
       ↓
[Sandbox Runtime]
       ↓
[Comparator]
       ↓
[Score Calculator]
       ↓
[Regression Checker]
       ↓
[Evaluation Report]
       ↓
[Deployment Gate]
```

---

## 3. Evaluation suite schema

```yaml
evaluation_suite_id: suite-support-router-v1
agent_id: support-router-agent
agent_version: v1.0.0
required_pass: true
thresholds:
  determinism_rate: 1.0
  schema_pass_rate: 1.0
  policy_pass_rate: 1.0
  regression_pass_rate: 1.0
  minimum_overall_score: 0.95
tests:
  - TEST-001
  - TEST-002
  - TEST-003
```

---

## 4. Test case schema

```yaml
test_id: TEST-001
test_type: determinism
name: Same input produces same output
input: {}
initial_state: {}
expected_output: {}
expected_properties: []
repeat_count: 10
allowed_variance: none
pass_condition: All repeated outputs exactly match.
```

---

## 5. Test types

### 5.1 Determinism test
Runs the same input and state multiple times.

Pass condition:

```text
All outputs match exactly, except approved volatile fields such as trace_id or timestamp.
```

Volatile fields must be explicitly ignored.

---

### 5.2 Schema test
Validates input and output contracts.

Checks:
- valid inputs are accepted
- invalid inputs are rejected
- outputs match schema
- required fields are present

---

### 5.3 Regression test
Confirms that previously required behavior still works.

Pass condition:
- previous expected outputs remain unchanged
- no protected rule behavior regresses

---

### 5.4 Policy test
Checks that the agent respects permissions.

Examples:
- blocked tools are not called
- restricted resources are not accessed
- production-only actions are not executed in sandbox
- approval-required actions pause instead of executing

---

### 5.5 State transition test
Verifies state machine behavior.

Examples:
- valid transitions pass
- invalid transitions are blocked
- failure states are reached predictably

---

### 5.6 Tie-break test
Creates inputs where multiple rules match.

Pass condition:
- the same tie-break winner is selected every time

---

### 5.7 Failure-path test
Simulates tool failures or dependency errors.

Examples:
- timeout
- permission denied
- malformed downstream response
- state conflict

Pass condition:
- expected retry, escalation, rejection, or failure path occurs

---

### 5.8 Performance test
Checks operational limits.

Metrics:
- average latency
- maximum latency
- throughput
- retry count
- queue wait time

---

## 6. Comparator model

The comparator checks actual output against expected output.

Comparison modes:

| Mode | Use case |
|---|---|
| exact | Fully deterministic outputs |
| partial | Ignore approved volatile fields |
| property | Check properties instead of exact value |
| schema_only | Output must match schema |
| metric | Performance or quality threshold |

Example ignored fields:

```yaml
ignored_fields:
  - trace_id
  - timestamp
  - run_id
```

---

## 7. Scoring model

Recommended overall score:

```text
overall_score =
  0.30 * determinism_score +
  0.25 * regression_score +
  0.20 * policy_score +
  0.15 * schema_score +
  0.10 * performance_score
```

Production deployment should require:

```text
determinism_score = 1.00
policy_score = 1.00
regression_score = 1.00
overall_score >= 0.95
```

---

## 8. Evaluation report format

```yaml
evaluation_run_id: EVAL-001
agent_id: support-router-agent
agent_version: v1.0.0
status: passed
overall_score: 0.98
scores:
  determinism: 1.00
  regression: 1.00
  policy: 1.00
  schema: 1.00
  performance: 0.90
failed_tests: []
warnings:
  - Average latency is near threshold.
started_at: timestamp
completed_at: timestamp
```

---

## 9. Example test cases

### TEST-001: Deterministic routing

```yaml
test_id: TEST-001
test_type: determinism
input:
  intent: route_support_request
  payload:
    customer_tier: enterprise
    topic: billing
    severity: medium
initial_state:
  status: received
expected_output:
  status: completed
  decision: route_to_billing_priority
  action: create_priority_billing_ticket
repeat_count: 10
ignored_fields:
  - trace_id
  - timestamp
pass_condition: All non-ignored fields match expected output.
```

### TEST-002: Policy denial

```yaml
test_id: TEST-002
test_type: policy
input:
  intent: send_external_email
  payload:
    recipient: customer@example.com
initial_state:
  status: received
expected_output:
  status: rejected
  reason: Action is not permitted for this agent.
repeat_count: 1
```

### TEST-003: Tie-break behavior

```yaml
test_id: TEST-003
test_type: tie_break
input:
  intent: route_support_request
  payload:
    topic: billing_and_technical
    severity: high
initial_state:
  status: received
expected_output:
  decision: route_to_incident_support
pass_condition: Highest severity rule wins before topic-specific rules.
```

---

## 10. Evaluation runner pseudocode

```python
def run_evaluation(agent_id, version, suite_id):
    suite = registry.get_evaluation_suite(suite_id)
    results = []

    for test in suite.tests:
        outputs = []
        for _ in range(test.repeat_count):
            output = sandbox_runtime.run(
                agent_id=agent_id,
                version=version,
                input=test.input,
                initial_state=test.initial_state
            )
            outputs.append(output)

        result = comparator.compare(outputs, test)
        results.append(result)

    report = score_results(results, suite.thresholds)
    registry.record_evaluation_run(report)
    return report
```

---

## 11. Deployment gate rules

A version cannot be promoted if:

- any policy test fails
- any determinism test fails
- any protected regression test fails
- output schema validation fails
- required test coverage is missing
- overall score is below threshold

---

## 12. Required coverage

Each production agent should have tests for:

- happy path
- invalid input
- missing required field
- each major decision branch
- tie-break case
- permission denied case
- tool failure case
- state transition error
- known regression cases

---

## 13. Improvement integration

When the Improvement Agent proposes a change, the Evaluation Harness must:

1. run current version baseline
2. run proposed version
3. compare both reports
4. detect regressions
5. produce before/after evidence

Improvement is accepted only if:

- targeted metric improves or stays acceptable
- protected behavior does not regress
- policy and determinism remain perfect

---

## Summary
The Evaluation Harness is the evidence engine for the agentic system. It converts proposed builds and improvements into measurable pass/fail decisions before deployment.
