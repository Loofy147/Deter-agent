# Deployment Pipeline Specification

## Purpose
The Deployment Pipeline controls how new or improved agents move from draft to production. It prevents untested or unauthorized changes from affecting live behavior.

---

## 1. Deployment principle

```text
Nothing reaches production without registry entry, evaluation evidence, policy check, approval, and rollback plan.
```

---

## 2. Pipeline stages

```text
Draft → Sandbox → Evaluation → Review → Staging → Production → Monitoring → Retired
```

---

## 3. Stage definitions

### 3.1 Draft
Agent specification exists but is not executable in production.

Requirements:
- purpose defined
- scope defined
- framework selected
- input/output schemas drafted
- initial rules drafted

Allowed actions:
- edit spec
- generate tests
- run static checks

---

### 3.2 Sandbox
Agent can run in isolated test mode.

Requirements:
- registry entry exists
- permissions limited to sandbox
- no real production side effects
- mock tools used by default

Allowed actions:
- run test cases
- generate traces
- compare versions
- improve draft rules

---

### 3.3 Evaluation
Agent runs formal test suite.

Requirements:
- determinism tests
- regression tests
- schema tests
- policy tests
- state transition tests
- failure-path tests

Promotion requires:
- determinism score = 1.00
- policy score = 1.00
- regression score = 1.00
- overall score >= 0.95

---

### 3.4 Review
Human or authorized review gate evaluates the change.

Review package must include:
- change summary
- agent version diff
- evaluation report
- risk assessment
- permission changes
- rollback plan
- expected impact

---

### 3.5 Staging
Agent runs in a controlled pre-production environment.

Requirements:
- approval for staging
- limited data or test data
- controlled side effects
- monitoring enabled

Exit criteria:
- no policy violations
- no critical runtime errors
- target latency acceptable
- no unexpected escalations

---

### 3.6 Production
Agent handles real workflows.

Requirements:
- production approval
- successful staging or approved exception
- version tag
- rollback version
- monitoring active
- owner assigned

---

### 3.7 Monitoring
Post-deployment system watches for regressions.

Monitor:
- success rate
- failure rate
- escalation rate
- override rate
- latency
- policy violations
- deterministic consistency

---

### 3.8 Retired
Agent is no longer active.

Requirements:
- replacement or deprecation reason
- final evaluation archive
- last production version retained
- rollback no longer active unless needed

---

## 4. Promotion criteria

| From | To | Required evidence |
|---|---|---|
| Draft | Sandbox | Complete minimum spec |
| Sandbox | Evaluation | Agent runs without runtime errors |
| Evaluation | Review | Required tests pass |
| Review | Staging | Reviewer approves |
| Staging | Production | Staging checks pass and production approval exists |
| Production | Retired | Owner approval and migration/deprecation plan |

---

## 5. Deployment package

Every deployment should include:

```yaml
deployment_id: DEPLOY-001
agent_id: support-router-agent
version: v1.1.0
environment: production
change_summary: Added enterprise billing priority route.
evaluation_report_id: EVAL-010
approval_id: APPROVAL-004
rollback_version: v1.0.0
risk_level: medium
deployed_by: deployment_pipeline
```

---

## 6. Versioning rules

Use semantic versioning:

```text
MAJOR.MINOR.PATCH
```

Recommended meaning:

| Change | Version bump |
|---|---|
| Breaking input/output schema change | MAJOR |
| New rule or capability | MINOR |
| Bug fix or validation improvement | PATCH |
| Permission expansion | MINOR or MAJOR depending risk |
| Permission restriction | PATCH or MINOR |

Examples:
- `v1.0.0` initial release
- `v1.1.0` new routing rule
- `v1.1.1` validation bug fix
- `v2.0.0` schema change

---

## 7. Approval workflow

```text
Create deployment request
  ↓
Attach evaluation evidence
  ↓
Attach risk assessment
  ↓
Attach rollback plan
  ↓
Reviewer approves or rejects
  ↓
Pipeline executes decision
```

Approval record:

```yaml
approval_id: APPROVAL-001
target_type: production_deployment
target_id: DEPLOY-001
requested_by: supervisor_agent
approver: authorized_operator
decision: approved
reason: Evaluation passed and risk is acceptable.
decided_at: timestamp
```

---

## 8. Rollback policy

Rollback triggers:

- policy violation
- critical runtime failure
- determinism failure
- severe latency regression
- error rate above threshold
- human override spike
- owner requests rollback

Rollback action:

```text
production current_version = rollback_version
new deployment record status = rolled_back
incident/improvement proposal created
```

Rollback requirements:
- rollback version exists
- rollback version is compatible with current state
- rollback is logged
- post-rollback evaluation is recorded

---

## 9. Canary release option

For higher-risk agents, use canary deployment.

```text
Deterministic cohort buckets: 5% → monitor → 25% → monitor → 100%. Assign each logical request using int(sha256(UTF8(request_id)).hexdigest(), 16) % 100; random assignment is forbidden.
```

Canary promotion requires:
- no policy violations
- no critical errors
- metrics equal or better than baseline
- no unexpected decision drift

---

## 10. Production monitoring thresholds

Example thresholds:

```yaml
rollback_thresholds:
  policy_violations: "> 0"
  determinism_rate: "< 1.00"
  success_rate: "< 0.90 for 30 minutes"
  error_rate: "> 0.05 for 30 minutes"
  p95_latency_ms: "> 3000 for 30 minutes"
  human_override_rate: "> 0.20 for 1 hour"
```

---

## 11. Deployment gate pseudocode

```python
def can_promote(agent_id, version, env):
    v = registry.version(agent_id, version)
    prev = registry.env_pointer(agent_id, env)
    if not stage_order_ok(v, env):
        return deny("STAGE_SKIPPED")
    if not v.is_immutable or not v.spec_hash:
        return deny("SPEC_HASH_MISMATCH")
    ev = registry.latest_eval(agent_id, version, spec_hash=v.spec_hash)
    if not (ev and ev.status == "passed" and ev.floors_met and ev.coverage_complete):
        return deny("EVALUATION_FLOOR_FAILED")
    policy = registry.version_policy(version_id=v.id, environment=env)
    if not policy:
        return deny("POLICY_DENIED")
    diff_hash = sha256(jcs(policy_diff(prev.policy_snapshot if prev else None, policy.snapshot)))
    approval_id = None
    if env in ("staging", "production"):
        ap = registry.approval(agent_id, version, env, v.spec_hash, ev.run_id, diff_hash)
        if not (ap and ap.decision == "approved" and not ap.expired
                and ap.approver != ap.requested_by
                and approval_scope_covers(ap.scope, policy_diff_hash=diff_hash)):
            return deny("APPROVAL_EXPIRED_OR_MISMATCHED")
        approval_id = ap.approval_id
    if env == "production":
        if not staging_succeeded_for(agent_id, version, v.spec_hash):
            return deny("STAGING_NOT_VERIFIED")
        if prev and not previously_approved_rollback_target(v.rollback_version):
            return deny("ROLLBACK_TARGET_MISSING")
    binding = {
        "agent_id": agent_id, "version": version, "target_environment": env,
        "spec_hash": v.spec_hash, "eval_run_id": ev.run_id,
        "approval_event_id": approval_id, "policy_diff_hash": diff_hash
    }
    registry.append_promotion_record(binding, sha256(jcs(binding)))
    return allow()
```

Approval must be approved, unexpired and independently requested, and must bind the exact target version, environment, spec hash, evaluation run and policy diff. Permission expansions require `permission_change` scope. Rollback is a production change and may target only a previously approved version; record it immutably.

## 12. Deployment checklist

- [ ] Agent exists in registry
- [ ] Version exists in registry
- [ ] Input schema exists
- [ ] Output schema exists
- [ ] State model exists
- [ ] Decision rules are versioned
- [ ] Permission policy exists
- [ ] Required evaluations passed
- [ ] Risk assessment exists
- [ ] Rollback version exists
- [ ] Approval exists for production
- [ ] Monitoring thresholds configured
- [ ] Owner assigned

---

## Summary
The Deployment Pipeline turns the agentic system into a controlled production system. It allows agents to evolve while preserving review, testing, rollback, and auditability.


## 13. Normative deterministic-control contract

**Normative source:** [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json).

- The promotion binding is `sha256(jcs({agent_id, version, target_environment, spec_hash, eval_run_id, approval_event_id, policy_diff_hash}))`. Store it as an append-only promotion record. Evaluation, approval, runtime gateway scope, and pipeline must match this exact binding; existence of an unrelated approval is not sufficient.
- Production requires successful staging for the same spec hash, passed component floors, complete suite coverage, an unexpired independent approval, and a policy-diff hash matching that approval.
- Any policy expansion requires `permission_change` scope. Rollback is a production change: pre-authorize rollback only to a previously approved version and log the promotion/rollback binding.
- Canary cohorts derive solely from the stable logical `request_id` hash. A retry preserves cohort assignment.
