# Agent Registry Schema

## Purpose
The Agent Registry is the source of truth for every agent controlled by the Deterministic Agentic Control System. It tracks agents, versions, schemas, policies, permissions, evaluations, deployments, and improvement history.

The registry makes the system controllable because no agent can be built, improved, evaluated, or deployed without an explicit record.

---

## 1. Core entities

```text
Agent
  └── Agent Version
        ├── Input Schema
        ├── Output Schema
        ├── State Model
        ├── Decision Rules
        ├── Permission Policy
        ├── Evaluation Suite
        ├── Deployment Records
        └── Improvement Proposals
```

---

## 2. Required registry fields

Every agent must have:

```yaml
agent_id: string
name: string
purpose: string
owner: string
framework: rule_based|decision_table|finite_state_machine|workflow_engine|constraint_based|deterministic_scoring|hybrid_rule_workflow
risk_level: low|medium|high|critical
created_at: timestamp
updated_at: timestamp
```

Every version must have:

```yaml
agent_id: string
version: string
input_schema_ref: string
output_schema_ref: string
state_model_ref: string
decision_rules_ref: string
policy_bindings_ref: string
evaluation_suite_ref: string
rollback_version: string|null
created_by: string
created_at: timestamp
change_summary: string
```

---

## 3. Recommended database tables

### 3.1 `agents`

| Field | Type | Required | Notes |
|---|---|---:|---|
| agent_id | string | Yes | Stable unique ID |
| name | string | Yes | Human-readable name |
| purpose | text | Yes | Exact role of the agent |
| owner | string | Yes | Responsible person/team |
| framework | enum | Yes | Primary deterministic framework |
| risk_level | enum | Yes | low/medium/high/critical |
| created_at | timestamp | Yes | Creation time |
| updated_at | timestamp | Yes | Last modification time |

---

### 3.2 `agent_versions`

| Field | Type | Required | Notes |
|---|---|---:|---|
| version_id | string | Yes | Unique version record |
| agent_id | string | Yes | Foreign key to `agents` |
| version | string | Yes | Semantic version, e.g. v1.0.0 |
| spec_hash | string | Yes | Hash of full agent spec |
| input_schema | json | Yes | Input contract |
| output_schema | json | Yes | Output contract |
| state_model | json | Yes | Allowed states and transitions |
| decision_rules | json | Yes | Ordered deterministic logic |
| tie_break_policy | json | Yes | Deterministic tie-breaks |
| evaluation_suite_id | string | Yes | Foreign key to test suite |
| rollback_version | string | No | Safe rollback target |
| created_by | string | Yes | User or builder agent |
| created_at | timestamp | Yes | Creation time |
| change_summary | text | Yes | Why this version exists |

---

### 3.3 `permission_policies`

| Field | Type | Required | Notes |
|---|---|---:|---|
| policy_id | string | Yes | Unique policy ID |
| agent_id | string | Yes | Applies to this agent |
| environment | enum | Yes | sandbox/staging/production |
| allowed_reads | json | Yes | Data sources allowed |
| allowed_writes | json | Yes | Destinations allowed |
| allowed_tools | json | Yes | Tool/action allowlist |
| blocked_tools | json | Yes | Explicit denylist |
| approval_required_for | json | Yes | Sensitive actions |
| created_at | timestamp | Yes | Creation time |

---

### 3.4 `evaluation_suites`

| Field | Type | Required | Notes |
|---|---|---:|---|
| evaluation_suite_id | string | Yes | Unique ID |
| agent_id | string | Yes | Target agent |
| version | string | Yes | Suite version |
| required_tests | json | Yes | Required test IDs |
| pass_thresholds | json | Yes | Required metrics |
| created_at | timestamp | Yes | Creation time |

---

### 3.5 `test_cases`

| Field | Type | Required | Notes |
|---|---|---:|---|
| test_id | string | Yes | Unique test case ID |
| evaluation_suite_id | string | Yes | Parent suite |
| test_type | enum | Yes | determinism/regression/policy/schema/state/performance/failure |
| input | json | Yes | Test input |
| initial_state | json | Yes | Starting state |
| expected_output | json | No | Exact or partial expected output |
| expected_properties | json | No | Property-based expectations |
| repeat_count | integer | Yes | Repetitions for determinism tests |
| pass_condition | text | Yes | Human-readable pass rule |

---

### 3.6 `evaluation_runs`

| Field | Type | Required | Notes |
|---|---|---:|---|
| run_id | string | Yes | Unique evaluation run |
| agent_id | string | Yes | Target agent |
| version | string | Yes | Version tested |
| evaluation_suite_id | string | Yes | Suite used |
| spec_hash | string | Yes | Immutable spec hash evaluated |
| suite_hash | string | Yes | Exact suite hash |
| policy_version | string | Yes | Policy used |
| engine_version | string | Yes | Engine/evaluator version |
| status | enum | Yes | passed/failed/error |
| score | number | Yes | Informational composite score |
| component_scores | json | Yes | Hard-gate components |
| floors_met | boolean | Yes | All required component floors pass |
| coverage_complete | boolean | Yes | Required suite coverage is complete |
| results | json | Yes | Test-level details |
| started_at | timestamp | Yes | Start time |
| completed_at | timestamp | Yes | End time |

---

### 3.7 `improvement_proposals`

| Field | Type | Required | Notes |
|---|---|---:|---|
| proposal_id | string | Yes | Unique proposal |
| target_agent_id | string | Yes | Agent to improve |
| target_version | string | Yes | Current version |
| proposed_version | string | No | Candidate version |
| problem | text | Yes | What is wrong |
| evidence | json | Yes | Metrics/logs supporting the problem |
| proposed_change | json | Yes | Exact change |
| expected_impact | text | Yes | Expected improvement |
| risk_level | enum | Yes | low/medium/high/critical |
| status | enum | Yes | draft/tested/reviewed/approved/rejected/deployed |
| created_by | string | Yes | Agent or user |
| created_at | timestamp | Yes | Creation time |

---

### 3.8 `deployments`

| Field | Type | Required | Notes |
|---|---|---:|---|
| deployment_id | string | Yes | Unique deployment |
| agent_id | string | Yes | Target agent |
| version | string | Yes | Version deployed |
| environment | enum | Yes | sandbox/staging/production |
| status | enum | Yes | pending/deployed/failed/rolled_back |
| approval_id | string | No | Required for production |
| deployed_by | string | Yes | User or deploy process |
| deployed_at | timestamp | Yes | Deploy time |
| rollback_version | string | No | Rollback target |

---

### 3.9 `approval_events`

| Field | Type | Required | Notes |
|---|---|---:|---|
| approval_id | string | Yes | Unique immutable approval |
| target_type | enum | Yes | proposal/deployment/permission_change |
| target_id | string | Yes | ID being approved |
| agent_id | string | Yes | Exact target agent |
| version | string | Yes | Exact target version |
| target_environment | enum | Yes | sandbox/staging/production |
| requested_by | string | Yes | Requester identity |
| approver | string | Yes | Independent authorized approver |
| decision | enum | Yes | approved/rejected/expired |
| spec_hash | string | Yes | Exact immutable spec hash |
| eval_run_id | string | Conditional | Required for promotion approvals |
| policy_diff_hash | string | Yes | Exact policy delta reviewed |
| scope | json | Yes | Typed approval scope |
| expires_at | timestamp | Yes | Expiry instant |
| evidence | json | Yes | Test results and change summary |
| decided_at | timestamp | Yes | Decision time |

---

### 3.10 `runtime_runs`

| Field | Type | Required | Notes |
|---|---|---:|---|
| run_id | string | Yes | Unique run |
| agent_id | string | Yes | Agent executed |
| version | string | Yes | Agent version |
| environment | enum | Yes | sandbox/staging/production |
| input | json | Yes | Raw input |
| normalized_input | json | No | Canonical input |
| initial_state | json | Yes | State before run |
| final_state | json | No | State after run |
| output | json | No | Result |
| status | enum | Yes | completed/failed/rejected/escalated |
| trace_id | string | Yes | Trace reference |
| started_at | timestamp | Yes | Start time |
| completed_at | timestamp | No | End time |

---

## 4. Minimal SQL-style schema

```sql
CREATE TABLE agents (
  agent_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  owner TEXT NOT NULL,
  framework TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE agent_versions (
  version_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  version TEXT NOT NULL,
  spec_hash TEXT NOT NULL,
  input_schema JSONB NOT NULL,
  output_schema JSONB NOT NULL,
  state_model JSONB NOT NULL,
  decision_rules JSONB NOT NULL,
  tie_break_policy JSONB NOT NULL,
  evaluation_suite_id TEXT NOT NULL,
  rollback_version TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  change_summary TEXT NOT NULL
);

CREATE TABLE evaluation_runs (
  run_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  evaluation_suite_id TEXT NOT NULL,
  status TEXT NOT NULL,
  score NUMERIC NOT NULL,
  results JSONB NOT NULL,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP
);
```

---

## 5. Registry API surface

Recommended registry operations:

```text
register_agent(spec)
create_agent_version(agent_id, version_spec)
get_agent(agent_id)
get_agent_version(agent_id, version)
list_agents(filter)
record_lifecycle_event(agent_id, event)
attach_evaluation_suite(agent_id, version, suite_id)
record_evaluation_run(result)
create_improvement_proposal(proposal)
record_approval_event(event)
record_deployment(deployment)
```

---

## 6. Registry validation rules

The registry must reject any agent version if:

- input schema is missing
- output schema is missing
- state model is missing
- decision rules are unordered
- tie-break policy is missing
- permission policy is missing
- evaluation suite is missing
- production deployment lacks approval
- production deployment lacks rollback version
- requested tools are not explicitly allowed

---

## 7. Status lifecycle

```text
draft → sandbox → staging → production → retired
          ↓          ↓           ↓
        failed     failed     rolled_back
```

Only the deployment pipeline should promote status to `staging` or `production`.

---

## 8. Registry guardrails

- Agents cannot edit their own registry permissions.
- Production versions cannot be overwritten; create a new version instead.
- Production deployment requires evaluation results and approval evidence.
- Every permission expansion requires a separate approval event.
- Every improvement proposal must reference evidence.
- Every deployed version must have a rollback target unless it is the first production release.

---

## Summary
The Agent Registry turns the agentic system from a loose collection of agents into a controlled platform. It provides the durable records needed for control, evaluation, improvement, deployment, rollback, and audit.


## 10. Normative deterministic-control contract

**Normative source:** [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json). They override conflicting earlier examples in this document.

- Do not store `agents.status` or a single `agents.current_version`. Represent lifecycle transitions as append-only events and active selection through `env_pointers(agent_id, environment, version_id, updated_at, updated_by)`.
- Do not attach one policy directly to an agent version. Use `version_policies(version_id, environment, policy_id, policy_version, policy_hash)`, with a unique key on `(version_id, environment)`.
- Every `evaluation_runs` row records `spec_hash`, `suite_hash`, `policy_version`, and `engine_version`. An evaluation is eligible only when its `spec_hash` equals the exact immutable version spec hash.
- Every `approval_events` row records `spec_hash`, `eval_run_id`, `expires_at`, `policy_diff_hash`, and a typed approval `scope`. Enforce `decision = 'approved'`, non-expiry, target equality, and `approver <> requested_by` at promotion time.
- Add append-only `traces` and `promotion_records`; `evaluation_runs`, `approval_events`, `traces`, and `promotion_records` must reject UPDATE and DELETE at the database boundary.
- Enforce suite-author/target-author separation of duties. Validate enum consistency, rule shadowing, decision-table totality and overlap, operation coverage, fallback rules, FSM reachability, and append-only guarantees before accepting a registered version.
- `rollback_version` may be null for draft/non-production versions and the first production release. If an environment already has a production pointer, a promotion requires a compatible rollback target that is a previously approved version.
- No runtime agent may set meta-agent autonomy configuration; `max_autonomy_level` applies only to explicitly registered meta-agents.


### 3.11 `env_pointers`

One row per `(agent_id, environment)`; this replaces singleton `current_version`.

| Field | Type | Required |
|---|---|---:|
| agent_id | string FK | Yes |
| environment | enum | Yes |
| version_id | string FK | Yes |
| updated_at | timestamp | Yes |
| updated_by | string | Yes |

### 3.12 `version_policies`

One environment-specific policy binding per immutable version.

| Field | Type | Required |
|---|---|---:|
| version_id | string FK | Yes |
| environment | enum | Yes |
| policy_id | string FK | Yes |
| policy_version | string | Yes |
| policy_hash | string | Yes |

Primary key: `(version_id, environment)`. Add a `promotion_records` table containing the exact promotion binding and binding hash. Evaluation runs, approval events, traces and promotion records are append-only and reject UPDATE/DELETE at the database boundary. Lifecycle history is event-based; the agent row has no mutable environment-independent status.
