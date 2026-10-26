# First Agent Example: Agent Registry Manager + Evaluation Agent

## Purpose
The first operational agents for the Deterministic Agentic Control System should be:

1. **Agent Registry Manager Agent** — controls creation and versioning of agent records.
2. **Evaluation Agent** — runs tests and produces evaluation reports.

Together, they give the system its first control and improvement loop.

```text
Registry Manager controls what agents exist.
Evaluation Agent controls whether agents are safe enough to progress.
```

---

# Part 1: Agent Registry Manager Agent

## 1. Agent identity

```yaml
agent_id: agent-registry-manager
name: Agent Registry Manager Agent
version: v1.0.0
framework: hybrid_rule_workflow
risk_level: medium
owner: system_operator
```

---

## 2. Purpose
Manages registry records for agents, versions, specs, permissions, evaluations, deployments, and improvement proposals.

This agent does **not** deploy production agents. It creates or updates registry entries under policy control.

---

## 3. Scope

### In scope
- register new draft agents
- create new agent versions
- validate required registry fields
- attach evaluation suites
- record evaluation results
- record improvement proposals
- change status from draft to sandbox when requirements are met

### Out of scope
- production deployment
- approval decisions
- permission expansion without approval
- deleting production records
- editing historical production versions

---

## 4. Input schema

```json
{
  "request_id": "string",
  "operation": "register_agent|create_version|attach_evaluation|record_evaluation|record_proposal|update_status",
  "agent_id": "string",
  "payload": {},
  "requested_by": "string",
  "environment": "sandbox|staging|production"
}
```

---

## 5. Output schema

```json
{
  "status": "completed|rejected|approval_required|failed",
  "operation": "string",
  "agent_id": "string",
  "record_id": "string|null",
  "reason": "string",
  "trace_id": "string",
  "policy_version": "string"
}
```

---

## 6. State model

```text
received
validated
policy_checked
registry_updated
verified
completed
rejected
approval_required
failed
```

### State transitions

| Current | Next | Condition |
|---|---|---|
| received | validated | Input schema valid |
| received | rejected | Input schema invalid |
| validated | policy_checked | Required fields present |
| policy_checked | registry_updated | Operation allowed |
| policy_checked | approval_required | Operation requires approval |
| registry_updated | verified | Write completed |
| verified | completed | Record exists and is valid |
| any | failed | Unexpected runtime error |

---

## 7. Decision rules

```yaml
rules:
  - rule_id: REG-001
    name: Reject missing operation
    condition: operation is missing or unsupported
    action: reject
    priority: 1
    reason: Registry operations must be explicit.

  - rule_id: REG-002
    name: Reject missing agent ID
    condition: agent_id is missing
    action: reject
    priority: 2
    reason: Every registry operation must target an agent.

  - rule_id: REG-003
    name: Register draft agent
    condition: operation = register_agent and payload contains required agent fields
    action: create_agent_record
    priority: 10
    reason: Valid draft agent can be registered.

  - rule_id: REG-004
    name: Create new version
    condition: operation = create_version and current agent exists and payload contains required version fields
    action: create_agent_version
    priority: 20
    reason: Version creation is allowed for registered agents.

  - rule_id: REG-005
    name: Require approval for production status
    condition: operation = update_status and payload.status = production
    action: require_approval
    priority: 30
    reason: Production promotion requires deployment approval.

  - rule_id: REG-006
    name: Block historical production mutation
    condition: operation attempts to modify an existing production version
    action: reject
    priority: 5
    reason: Production versions are immutable; this deny guard outranks the generic create-version allow.

  - rule_id: REG-007
    name: Attach evaluation suite
    condition: operation = attach_evaluation and evaluation suite is complete
    action: attach_evaluation_suite
    priority: 50
    reason: Agents need evaluation suites before promotion.

  - rule_id: REG-008
    name: Record evaluation result
    condition: operation = record_evaluation and evaluation result is valid
    action: write_evaluation_run
    priority: 60
    reason: Evaluation evidence must be stored.

  - rule_id: REG-009
    name: Record improvement proposal
    condition: operation = record_proposal and proposal schema and evidence references are valid
    action: create_improvement_proposal
    priority: 70
    reason: Proposals must be typed and evidence-linked.

  - rule_id: REG-010
    name: Update non-production lifecycle
    condition: operation = update_status and payload.status in [draft, sandbox] and environment != production
    action: update_lifecycle_event
    priority: 80
    reason: Non-production lifecycle updates are explicit and auditable.

  - rule_id: REG-011
    name: Reject production-environment registry writes
    condition: environment = production and operation mutates registry records
    action: reject
    priority: 3
    reason: Registry Manager cannot mutate records from production context.

  - rule_id: REG-999
    name: Explicit fallback
    condition: no previous rule matches
    action: reject
    priority: 999
    reason: No unmatched operation may be implicitly allowed.
```

---

## 8. Tie-break policy

Use the single total order (priority ASC, specificity DESC, risk_rank ASC, rule_id ASC). Lower numeric priority wins. Equal-priority ties are valid and tested; timestamps and action names never break ties. Rule IDs must be unique.

---

## 9. Permission policy

```yaml
policy_id: registry-manager-sandbox-v1
agent_id: agent-registry-manager
environment: sandbox
allowed_reads:
  - agent_registry
  - evaluation_suites
  - permission_policies
allowed_writes:
  - agent_registry_draft
  - agent_versions_draft
  - evaluation_runs
  - improvement_proposals
allowed_tools:
  - registry_read
  - registry_write_draft
  - evaluation_record_write
blocked_tools:
  - production_deploy
  - permission_expand
  - delete_production_record
approval_required_for:
  - update_status_to_production
  - permission_policy_change
  - production_version_change
```

---

## 10. Example request

```json
{
  "request_id": "REQ-001",
  "operation": "register_agent",
  "agent_id": "support-router-agent",
  "requested_by": "builder-agent",
  "environment": "sandbox",
  "payload": {
    "name": "Support Router Agent",
    "purpose": "Route support requests to the correct queue.",
    "owner": "support_ops",
    "framework": "decision_table",
    "risk_level": "medium"
  }
}
```

## 11. Example output

```json
{
  "status": "completed",
  "operation": "register_agent",
  "agent_id": "support-router-agent",
  "record_id": "agent-support-router-agent",
  "reason": "Draft agent registered successfully.",
  "trace_id": "TRACE-001",
  "policy_version": "registry-manager-sandbox-v1"
}
```

---

## 12. Evaluation suite for Registry Manager

### TEST-REG-001: Register valid draft agent

```yaml
test_type: regression
expected_status: completed
expected_operation: register_agent
```

### TEST-REG-002: Reject missing agent ID

```yaml
test_type: validation
expected_status: rejected
expected_reason_contains: agent_id
```

### TEST-REG-003: Block production mutation

```yaml
test_type: policy
operation: create_version
condition: target version is existing production version
expected_status: rejected
```

### TEST-REG-004: Require approval for production status

```yaml
test_type: policy
operation: update_status
payload:
  status: production
expected_status: approval_required
```

### TEST-REG-005: Determinism

```yaml
test_type: determinism
repeat_count: 10
pass_condition: Same input produces the same status, operation, action, and reason.
ignored_fields:
  - trace_id
  - timestamp
```

---

# Part 2: Evaluation Agent

## 1. Agent identity

```yaml
agent_id: evaluation-agent
name: Evaluation Agent
version: v1.0.0
framework: workflow_engine
risk_level: medium
status: sandbox
owner: system_operator
```

---

## 2. Purpose
Runs evaluation suites against sandbox or staged agent versions and writes evaluation reports to the registry.

---

## 3. Scope

### In scope
- load evaluation suites
- run sandbox tests
- compare actual vs expected outputs
- calculate scores
- produce evaluation reports
- record evaluation runs

### Out of scope
- modifying agent rules
- changing permissions
- approving deployments
- deploying to production

---

## 4. Input schema

```json
{
  "request_id": "string",
  "target_agent_id": "string",
  "target_version": "string",
  "evaluation_suite_id": "string",
  "environment": "sandbox|staging",
  "requested_by": "string"
}
```

---

## 5. Output schema

```json
{
  "status": "passed|failed|error",
  "evaluation_run_id": "string",
  "target_agent_id": "string",
  "target_version": "string",
  "overall_score": "number",
  "failed_tests": [],
  "report_ref": "string",
  "trace_id": "string"
}
```

---

## 6. Workflow

```text
received
  ↓
load_suite
  ↓
load_target_agent
  ↓
run_tests
  ↓
compare_outputs
  ↓
calculate_score
  ↓
write_report
  ↓
completed
```

---

## 7. Decision rules

```yaml
rules:
  - rule_id: EVAL-001
    priority: 1
    condition: evaluation suite missing
    action: reject
    reason: Evaluation cannot run without a suite.

  - rule_id: EVAL-002
    priority: 2
    condition: target agent version missing
    action: reject
    reason: Evaluation requires a registered agent version.

  - rule_id: EVAL-003
    priority: 3
    condition: environment = production
    action: reject
    reason: Evaluation Agent runs only in sandbox or staging.

  - rule_id: EVAL-004
    priority: 10
    condition: all tests pass and thresholds met
    action: mark_passed
    reason: Evaluation passed.

  - rule_id: EVAL-005
    priority: 20
    condition: one or more required tests fail
    action: mark_failed
    reason: Evaluation failed.

  - rule_id: EVAL-006
    priority: 21
    condition: tests pass but one or more component floors fail
    action: mark_failed
    reason: Composite score cannot mask component-floor failures.

  - rule_id: EVAL-007
    priority: 4
    condition: evaluation runner or dependency returns an error
    action: mark_error
    reason: Error is never a passing evaluation.

  - rule_id: EVAL-008
    priority: 5
    condition: no environment-specific policy exists for the requested target
    action: reject
    reason: Missing environment policy defaults to deny.

  - rule_id: EVAL-999
    priority: 999
    condition: no previous rule matches
    action: reject
    reason: No unmatched evaluation request may be implicitly allowed.
```

---

## 8. Permission policy

```yaml
policy_id: evaluation-agent-sandbox-v1
agent_id: evaluation-agent
environment: sandbox
allowed_reads:
  - agent_registry
  - agent_versions
  - evaluation_suites
  - sandbox_runtime
allowed_writes:
  - evaluation_runs
  - evaluation_reports
allowed_tools:
  - run_sandbox_runtime
  - compare_outputs
  - calculate_score
  - write_evaluation_report
blocked_tools:
  - production_deploy
  - change_agent_rules
  - change_permissions
approval_required_for: []
```

---


### Evaluation Agent staging policy

Register a distinct policy before allowing `environment: staging`. A missing environment-specific policy denies by default.

```yaml
policy_id: evaluation-agent-staging-v1
agent_id: evaluation-agent
environment: staging
allowed_reads:
  - agent_registry
  - agent_versions
  - evaluation_suites
  - staging_runtime_results
allowed_writes:
  - evaluation_runs
  - evaluation_reports
allowed_tools:
  - run_staging_test
  - compare_outputs
  - calculate_score
  - write_evaluation_report
blocked_tools:
  - production_deploy
  - change_agent_rules
  - change_permissions
  - external_message_send
approval_required_for: []
```

## 9. Example evaluation request

```json
{
  "request_id": "REQ-EVAL-001",
  "target_agent_id": "support-router-agent",
  "target_version": "v1.0.0",
  "evaluation_suite_id": "suite-support-router-v1",
  "environment": "sandbox",
  "requested_by": "supervisor-agent"
}
```

---

## 10. Example evaluation output

```json
{
  "status": "passed",
  "evaluation_run_id": "EVAL-001",
  "target_agent_id": "support-router-agent",
  "target_version": "v1.0.0",
  "overall_score": 0.99,
  "failed_tests": [],
  "report_ref": "evaluation_reports/EVAL-001.json",
  "trace_id": "TRACE-EVAL-001"
}
```

---

# Part 3: First build sequence

Use an operator-signed, hash-pinned bootstrap seed with `created_by: bootstrap`. The exception is sandbox-only and expires after step 8.

```text
1. Canonicalization + shared enums from contracts/deterministic-control-contract.json.
2. Registry with static validation and append-only audit protections.
3. Permission Gateway deny-all stub.
4. Seed Registry Manager with an operator-signed bootstrap record.
5. Hash-pin the Evaluation Agent spec and suite; execute it only in sandbox.
6. Register sandbox and staging policies before allowing evaluation in each respective environment; staging policy is test-only and denies production actions.
7. Test operation coverage, fallback, rule shadowing, equal-priority tie-breaks, approval bindings, threshold failures and error paths.
8. Validate bootstrap signature/hash, record expiry, and revoke the temporary trust-root exception.
9. Register and evaluate the first domain agent in sandbox.
10. Promote only through ordered stages, component floors, independent approval and rollback gates.
```

Registry Manager rules cover every operation plus an explicit fallback. The production-mutation guard outranks generic create-version allow. The Evaluation Agent explicitly handles missing suite/version, missing environment policy, tests-pass/threshold-fail, `error`, and unmatched requests.

## Summary
The first useful system agents are the Agent Registry Manager and Evaluation Agent. They establish the control loop required before building many other agents: every agent must be registered, versioned, tested, scored, and governed before deployment.


## 13. Normative deterministic-control contract

**Normative source:** [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json). Corrected rules in Part 3 supersede earlier illustrative rule tables and build order.
