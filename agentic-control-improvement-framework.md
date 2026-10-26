# Agentic Control and Improvement Framework

## Purpose
This framework defines how an agentic system controls, evaluates, improves, and safely evolves deterministic agents.

The system is designed around one rule:

```text
No improvement is real until it is measured, tested, reviewed, and versioned.
```

---

## 1. Control model

The control model prevents agents from becoming uncontrolled or untraceable.

### Control layers

| Layer | Purpose |
|---|---|
| Goal control | Defines what the system is allowed to optimize |
| Policy control | Defines what agents may and may not do |
| State control | Tracks exact workflow and agent state |
| Tool control | Restricts actions and external integrations |
| Change control | Governs modifications to agents |
| Deployment control | Separates draft, sandbox, staging, and production |
| Audit control | Records every decision and change |

---

## 2. Improvement loop

The improvement loop is deterministic and measurable.

```text
Measure → Compare → Diagnose → Propose → Test → Review → Deploy → Monitor
```

### Step 1: Measure
Collect metrics from live or test agents.

Metrics:
- success rate
- failure rate
- escalation rate
- override rate
- latency
- consistency rate
- policy violation rate
- user correction rate

### Step 2: Compare
Compare actual performance against targets.

Example:

| Metric | Target | Actual | Status |
|---|---:|---:|---|
| Success rate | >= 95% | 91% | Failing |
| Escalation rate | <= 10% | 18% | Failing |
| Consistency rate | 100% | 100% | Passing |

### Step 3: Diagnose
Use logs and traces to identify why performance is below target.

Possible root causes:
- missing rule
- ambiguous input schema
- incomplete validation
- bad tie-break rule
- outdated workflow
- weak exception handling
- missing tool permission
- poor output schema

### Step 4: Propose
Generate a specific improvement proposal.

Proposal format:

```yaml
proposal_id: IMP-001
target_agent: refund-routing-agent
problem: Escalation rate too high for low-risk requests.
change_type: decision_table_update
proposed_change: Add low-risk auto-routing rule for enterprise customers under $500.
expected_impact: Reduce escalations by 8-12%.
risk_level: medium
requires_approval: true
```

### Step 5: Test
Run deterministic tests before deployment.

Required tests:
- same-input repeat test
- regression test
- boundary test
- policy compliance test
- failure-path test

### Step 6: Review
A review gate decides whether the change is safe.

Review checks:
- all required tests passed
- policy constraints preserved
- no unauthorized tools added
- rollback version exists
- metrics target is clear
- production approval completed when required

### Step 7: Deploy
Deploy through a controlled pipeline.

```text
Draft → Sandbox → Staging → Production
```

### Step 8: Monitor
Compare post-change metrics to the baseline.

If metrics improve, keep the change.  
If metrics regress, rollback or revise.

---

## 3. Control roles

### 3.1 Supervisor Agent
Owns orchestration.

Responsibilities:
- choose whether to build or improve
- assign tasks to sub-agents
- enforce workflow stage order
- request approval when needed
- maintain traceability

### 3.2 Policy Agent
Checks constraints.

Responsibilities:
- enforce tool permissions
- detect policy violations
- block unsafe changes
- require approval for sensitive actions

### 3.3 Evaluation Agent
Measures performance.

Responsibilities:
- run tests
- score outputs
- compare against baselines
- detect regressions

### 3.4 Improvement Agent
Generates controlled proposals.

Responsibilities:
- identify improvement opportunities
- propose rule, schema, state, or workflow changes
- estimate expected impact
- create test requirements

### 3.5 Builder Agent
Creates new agent drafts.

Responsibilities:
- generate specifications
- choose framework type
- define schemas
- create deterministic rules
- generate tests

### 3.6 Review Gate Agent
Approves or rejects changes before human review or deployment.

Responsibilities:
- check completeness
- check risk level
- check tests
- check policy constraints
- check rollback path

---

## 4. Autonomy levels

| Level | Name | Description | Production changes allowed? |
|---:|---|---|---|
| 0 | Manual | User designs everything | No |
| 1 | Recommend | Agent suggests improvements | No |
| 2 | Draft | Agent creates draft specs/files | No |
| 3 | Sandbox | Agent tests changes in sandbox | No |
| 4 | Staged | Agent prepares controlled rollout | With approval |
| 5 | Production | Agent deploys live changes | Only with explicit approval |

Recommended default level: **3 — Sandbox**.

---

## 5. Improvement types

| Improvement type | Example | Risk |
|---|---|---|
| Rule addition | Add routing rule | Medium |
| Rule reorder | Change priority order | High |
| Schema improvement | Add required field | Medium |
| Validation improvement | Add field constraint | Low/Medium |
| State transition fix | Block invalid transition | Medium |
| Tool restriction | Remove unsafe action | Low |
| Tool expansion | Add new external action | High |
| Output formatting | Standardize response | Low |
| Test expansion | Add regression tests | Low |

---

## 6. Build-new-agent loop

When the system needs a new agent, it follows this sequence:

```text
Need detected → Agent spec → Framework selection → Schema design → Rule design → Test design → Sandbox build → Evaluation → Approval → Registry entry → Deployment
```

### New-agent creation gates

| Gate | Requirement |
|---|---|
| Spec gate | Purpose, scope, inputs, outputs defined |
| Framework gate | Correct deterministic framework selected |
| Safety gate | Permissions and policies defined |
| Test gate | Evaluation suite created |
| Deployment gate | Approval and rollback path exist |

---

## 7. Measurement model

### Agent scorecard

```yaml
agent_id: example-agent
version: 1.0.0
period: weekly
metrics:
  success_rate: 0.96
  consistency_rate: 1.00
  escalation_rate: 0.07
  override_rate: 0.03
  average_latency_ms: 850
  policy_violations: 0
status: healthy
```

### System scorecard

```yaml
system:
  total_agents: 12
  healthy_agents: 10
  agents_needing_improvement: 2
  proposals_open: 4
  proposals_approved: 2
  failed_regressions: 1
  production_rollbacks: 0
```

---

## 8. Decision policy for improvement

Use this policy to decide what happens after measurement.

| Condition | Action |
|---|---|
| Metrics pass target | Continue monitoring |
| Minor failure, low risk | Create improvement proposal |
| Repeated failure | Escalate to review |
| Policy violation | Block and alert |
| Regression after deployment | Rollback |
| Missing tests | Generate tests before change |
| Missing schema | Stop and define schema |

---

## 9. Anti-patterns to avoid

Avoid:
- agents changing their own permissions
- agents deploying production changes without review
- rules without versions
- hidden memory driving decisions
- metrics without baselines
- improvements without regression tests
- ambiguous tie-breaks
- unlogged actions
- direct production experimentation

---

## 10. Operating cadence

### Daily
- monitor failures
- detect policy violations
- detect broken workflows

### Weekly
- review metrics
- identify improvement candidates
- run regression suite

### Monthly
- review agent registry
- retire unused agents
- consolidate duplicate agents
- update templates

---

## Summary
This framework gives the agentic system a safe improvement engine. It can observe, diagnose, propose, test, and build — but production behavior changes only through controlled gates, evaluation, versioning, and approval.
