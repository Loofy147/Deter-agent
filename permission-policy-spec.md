# Permission Policy Specification

## Purpose
The Permission Policy defines what each agent can read, write, execute, change, and deploy. It prevents agents from expanding their own authority or taking unsafe actions without approval.

---

## 1. Security principle

```text
Default deny. Explicit allow. Approval for sensitive actions.
```

Agents should only receive the minimum permissions needed for their role.

---

## 2. Policy decision types

| Decision | Meaning |
|---|---|
| allow | Action may execute |
| deny | Action is blocked |
| require_approval | Action pauses until approved |
| sandbox_only | Action is allowed only in sandbox |
| mock_only | Action must use a mock or dry-run |

---

## 3. Policy schema

```yaml
policy_id: policy-support-router-v1
agent_id: support-router-agent
version: v1.0.0
environment: production
allowed_reads:
  - support_request_queue
  - customer_tier_table
allowed_writes:
  - support_ticket_queue
allowed_tools:
  - create_support_ticket
blocked_tools:
  - send_external_email
  - delete_customer_record
approval_required_for:
  - production_deploy
  - permission_expansion
  - external_message_send
  - destructive_action
data_classes_allowed:
  - internal
  - customer_limited
data_classes_blocked:
  - secrets
  - payment_full
created_at: timestamp
```

---

## 4. Permission dimensions

### 4.1 Environment

Permissions differ by environment.

| Environment | Default behavior |
|---|---|
| sandbox | No real external side effects unless allowed |
| staging | Limited side effects with test resources |
| production | Real side effects only through approved policy |

---

### 4.2 Resource

Examples:
- agent registry
- runtime state store
- evaluation results
- customer records
- support tickets
- files
- external APIs

---

### 4.3 Action

Examples:
- read
- write
- create
- update
- delete
- send
- deploy
- approve
- execute_tool
- change_permission

---

### 4.4 Data classification

| Class | Description | Default |
|---|---|---|
| public | Non-sensitive public data | allow if needed |
| internal | Internal operational data | allow if needed |
| customer_limited | Customer data with limited fields | approval or allow by role |
| customer_sensitive | Sensitive customer data | approval required |
| secrets | Credentials/API keys/tokens | always deny to agents |
| regulated | Legal, financial, health, or compliance data | explicit approval required |

---

## 5. Role-based permissions

| Role | Reads | Writes | Deploys | Permission changes |
|---|---|---|---|---|
| Supervisor Agent | Registry, metrics, proposals | Proposals, orchestration state | No | No |
| Builder Agent | Templates, registry specs | Draft specs | No | No |
| Evaluation Agent | Agent specs, test cases | Evaluation results | No | No |
| Improvement Agent | Metrics, traces | Improvement proposals | No | No |
| Runtime Agent | Its assigned inputs/state | Its assigned outputs/state | No | No |
| Human Operator | As assigned | As assigned | Yes if authorized | Yes if authorized |

---

## 6. Tool Gateway enforcement

Every tool request must include:

```json
{
  "agent_id": "string",
  "agent_version": "string",
  "environment": "sandbox|staging|production",
  "tool_name": "string",
  "action": "string",
  "target_resource": "string"
}
```

The gateway returns:

```json
{
  "decision": "allow|deny|require_approval|sandbox_only|mock_only",
  "reason": "string",
  "approval_policy": "string|null"
}
```

---

## 7. Approval-required actions

The following should always require approval:

- production deployment
- permission expansion
- destructive action
- external communication outside sandbox
- access to sensitive or regulated data
- changing another agent's policy
- disabling logging or evaluation
- modifying production state outside normal workflow

---

## 8. Permission expansion rule

Agents cannot expand their own permissions.

```text
If requested_runtime_permission not in current_policy.allowed_permissions:
    decision = deny_and_log_and_increment_unauthorized_tool_attempt_count
```

A permission expansion must create:
- proposal record
- risk analysis
- approval event
- updated policy version
- audit log

---

## 9. Example policies

### 9.1 Builder Agent policy

```yaml
policy_id: builder-agent-sandbox-v1
agent_id: builder-agent
environment: sandbox
allowed_reads:
  - template_library
  - agent_registry_draft
allowed_writes:
  - agent_specs_draft
  - test_suites_draft
allowed_tools:
  - write_draft_spec
  - create_test_suite
blocked_tools:
  - deploy_production
  - send_external_message
  - change_permissions
approval_required_for:
  - staging_promotion
  - permission_expansion
```

### 9.2 Evaluation Agent policy

```yaml
policy_id: evaluation-agent-v1
agent_id: evaluation-agent
environment: sandbox
allowed_reads:
  - agent_registry
  - test_suites
  - sandbox_runtime_results
allowed_writes:
  - evaluation_runs
  - evaluation_reports
allowed_tools:
  - run_sandbox_test
  - compare_outputs
blocked_tools:
  - production_deploy
  - external_message_send
approval_required_for: []
```

### 9.3 Runtime Agent policy

```yaml
policy_id: support-router-production-v1
agent_id: support-router-agent
environment: production
allowed_reads:
  - support_request_queue
  - customer_tier_table
allowed_writes:
  - support_ticket_queue
allowed_tools:
  - create_support_ticket
blocked_tools:
  - delete_ticket
  - send_external_email
approval_required_for:
  - external_message_send
  - permission_expansion
```

---

## 10. Policy test cases

Every permission policy should have tests for:

- allowed read succeeds
- blocked read fails
- allowed write succeeds
- blocked write fails
- blocked tool is denied
- approval-required action pauses
- sandbox-only action does not execute in production
- permission expansion is blocked

---

## 11. Audit requirements

Every policy decision must log:

- agent ID
- version
- environment
- requested action
- requested tool
- target resource
- policy ID
- decision
- reason
- timestamp

---

## 12. Anti-escalation controls

The system must block:

- self-granted tools
- self-approved deployments
- hidden tool calls
- policy changes without versioning
- disabling the permission gateway
- reading secrets through logs
- bypassing sandbox with production tools

---

## Summary
The Permission Policy Specification creates the enforcement layer for agentic control. It lets agents build and improve safely while preventing unauthorized tool use, production changes, data access, and permission escalation.


## 13. Normative deterministic-control contract

**Normative source:** [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json).

- Default deny is literal for runtime calls: an unlisted tool, action, resource, or permission is denied, logged, and counted. Do not create approval requests for routine unauthorized calls; this would create an approval-channel denial-of-service path.
- Approval is reserved for explicit out-of-band permission-expansion proposals. Such a proposal must carry a policy diff, immutable spec hash, requester, risk evidence, and intended scope; an independent approver must approve it.
- The gateway derives `data_class` and `risk_level` from a versioned resource/tool catalog. These values are not accepted as authoritative caller inputs.
- `sandbox_only` rejects execution outside sandbox. `mock_only` must select a mock adapter and must never fall through to a live adapter. Missing environment-specific policy means deny.
- Canonical policy-decision values are `allow`, `deny`, `require_approval`, `sandbox_only`, and `mock_only`. Permission scope is evaluated against the exact registered version and target resource.


Autonomy levels are meta-agent orchestration settings only, not permission-policy fields. They do not grant runtime agents tools or bypass resource/tool authorization. Runtime authority comes exclusively from the versioned environment policy and the Permission Gateway.
