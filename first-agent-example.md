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
status: sandbox
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
  "environment": "draft|sandbox|staging|production"
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
    priority: 40
    reason: Production versions are immutable.

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
```

---

## 8. Tie-break policy

If multiple rules match:

1. lowest priority number for validation/rejection rules
2. highest safety rule priority
3. most specific operation match
4. lexical order by rule ID

---

## 9. Permission policy

```yaml
policy_id: registry-manager-sandbox-v1
agent_id: agent-registry-manager
environment: sandbox
max_autonomy_level: 3
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
    condition: evaluation suite missing
    action: reject
    reason: Evaluation cannot run without a suite.

  - rule_id: EVAL-002
    condition: target agent version missing
    action: reject
    reason: Evaluation requires a registered agent version.

  - rule_id: EVAL-003
    condition: environment = production
    action: reject
    reason: Evaluation Agent runs only in sandbox or staging.

  - rule_id: EVAL-004
    condition: all tests pass and thresholds met
    action: mark_passed
    reason: Evaluation passed.

  - rule_id: EVAL-005
    condition: one or more required tests fail
    action: mark_failed
    reason: Evaluation failed.
```

---

## 8. Permission policy

```yaml
policy_id: evaluation-agent-sandbox-v1
agent_id: evaluation-agent
environment: sandbox
max_autonomy_level: 3
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
  "overall_score": 0.98,
  "failed_tests": [],
  "report_ref": "evaluation_reports/EVAL-001.json",
  "trace_id": "TRACE-EVAL-001"
}
```

---

# Part 3: First build sequence

Use this order to bring the system online:

```text
1. Create registry schema.
2. Register Agent Registry Manager Agent as draft.
3. Create its sandbox permission policy.
4. Create its evaluation suite.
5. Run Evaluation Agent manually or through sandbox runtime.
6. Register Evaluation Agent as draft.
7. Create Evaluation Agent evaluation suite.
8. Run both agents in sandbox.
9. Use them to register the first runtime agent.
10. Deploy only after review and approval pipeline exists.
```

---

## Summary
The first useful system agents are the Agent Registry Manager and Evaluation Agent. They establish the control loop required before building many other agents: every agent must be registered, versioned, tested, scored, and governed before deployment.
