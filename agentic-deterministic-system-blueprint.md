# Agentic Deterministic System Blueprint

## System name
**Deterministic Agentic Control System**  
Short name: **DACS**

## Purpose
DACS is an agentic system that can:

1. **Control** deterministic agents through policies, state, permissions, workflows, and audit logs.
2. **Improve** existing agents through metrics, evaluations, regression tests, and controlled updates.
3. **Build new agents** from reusable templates, framework patterns, and validated specifications.

The goal is not uncontrolled self-modification. The goal is a governed agentic system where agents can propose, test, build, and improve under measurable controls.

---

## Core principle

```text
Agentic autonomy + deterministic control = safe, repeatable improvement
```

The system is agentic because it can plan, inspect, evaluate, propose, and build.  
It remains controlled because every decision, state transition, change, and deployment is explicit, versioned, tested, and auditable.

---

## High-level architecture

```text
                         ┌──────────────────────────┐
                         │      User / Operator      │
                         └────────────┬─────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Control Plane                              │
│  Supervisor Agent · Policy Engine · Permissions · Agent Registry │
└───────────────┬───────────────────────────────┬─────────────────┘
                │                               │
                ▼                               ▼
┌────────────────────────────┐       ┌────────────────────────────┐
│       Runtime Plane         │       │      Build Plane            │
│ Worker Agents · Workflows   │       │ Agent Factory · Templates   │
│ Tools · State Machines      │       │ Spec Builder · Test Builder │
└───────────────┬────────────┘       └──────────────┬─────────────┘
                │                                   │
                ▼                                   ▼
┌────────────────────────────┐       ┌────────────────────────────┐
│     Evaluation Plane        │       │    Improvement Plane        │
│ Metrics · Logs · Traces     │──────▶│ Gap Detector · Optimizer    │
│ Regression Tests · Scoring  │       │ Patch Proposer · Review Gate│
└───────────────┬────────────┘       └──────────────┬─────────────┘
                │                                   │
                └──────────────────┬────────────────┘
                                   ▼
                         ┌──────────────────────┐
                         │ Deployment Pipeline  │
                         │ Sandbox → Staging →  │
                         │ Production           │
                         └──────────────────────┘
```

---

## 1. Control Plane
The Control Plane governs the entire system.

### Components

#### 1.1 Supervisor Agent
The top-level orchestration agent.

Responsibilities:
- receive goals from the user/operator
- select the correct worker or builder agent
- enforce workflow order
- coordinate evaluations and improvements
- route risky changes to human approval
- maintain system-level traceability

The Supervisor does not directly change production agents without passing through the review and deployment pipeline.

---

#### 1.2 Policy Engine
Defines what agents can and cannot do.

Policy examples:
- which tools an agent may use
- whether an agent can write files
- whether an agent can deploy changes
- which data sources are allowed
- whether human approval is required
- maximum autonomy level for each agent

Policy format example:

```yaml
policy_id: production_agent_change_policy
rule: Any production change requires evaluation pass and human approval.
applies_to:
  - builder_agent
  - improvement_agent
action: require_approval
```

---

#### 1.3 Agent Registry
Stores all active and proposed agents.

Registry fields:
- agent ID
- name
- purpose
- owner
- status
- version
- framework type
- tools allowed
- input/output schema
- evaluation suite
- deployment environment
- last audit result

---

#### 1.4 Permission and Tool Gateway
Controls which tools each agent can access.

Responsibilities:
- restrict sensitive actions
- block unauthorized tools
- require approval for irreversible actions
- log every external action
- isolate sandbox agents from production tools

---

## 2. Runtime Plane
The Runtime Plane contains the working deterministic agents.

### Runtime agents
Examples:
- Triage Agent
- Routing Agent
- Report Agent
- Compliance Agent
- Data Transformation Agent
- Monitoring Agent

Each runtime agent should have:
- explicit input schema
- explicit output schema
- fixed decision rules
- versioned state model
- measurable success criteria
- trace logs
- regression tests

---

## 3. Build Plane
The Build Plane creates new deterministic agents.

### Components

#### 3.1 Agent Factory
Builds new agents from approved templates.

Factory workflow:
1. receive a goal
2. clarify scope
3. select the correct framework
4. generate agent specification
5. generate schemas
6. generate rules and state model
7. generate evaluation tests
8. create sandbox version
9. run tests
10. submit for approval
11. register agent
12. deploy if approved

---

#### 3.2 Template Library
Reusable blueprints for common agent types.

Template examples:
- routing agent
- approval agent
- classification agent
- scoring agent
- monitoring agent
- reporting agent
- compliance agent
- workflow automation agent

---

#### 3.3 Capability Mapper
Maps a requested goal to the correct agent design.

Example:

| User goal | Suggested agent type | Framework |
|---|---|---|
| Route incoming requests | Routing Agent | Decision table + workflow |
| Approve or reject cases | Approval Agent | Rule engine + policy checks |
| Prioritize leads | Scoring Agent | Deterministic scoring |
| Monitor failures | Monitoring Agent | State machine + thresholds |
| Create reports | Reporting Agent | Workflow + template |

---

## 4. Evaluation Plane
The Evaluation Plane measures whether agents work correctly.

### Evaluation layers

#### 4.1 Determinism tests
Checks whether the same input and same state produce the same output.

#### 4.2 Regression tests
Checks whether new versions preserve required behavior.

#### 4.3 Policy tests
Checks whether the agent violates constraints or permissions.

#### 4.4 Performance tests
Measures latency, throughput, failures, and retries.

#### 4.5 Quality tests
Measures accuracy, completeness, routing correctness, or business outcome quality.

---

## 5. Improvement Plane
The Improvement Plane identifies weaknesses and proposes controlled changes.

### Improvement workflow

```text
Monitor → Detect gap → Diagnose cause → Propose change → Test → Review → Deploy → Monitor again
```

### Improvement agents

#### 5.1 Metrics Analyst Agent
Reads metrics and identifies underperforming agents.

Detects:
- high failure rate
- high escalation rate
- low consistency rate
- high latency
- frequent human overrides
- repeated validation errors

#### 5.2 Root Cause Agent
Analyzes logs and traces to find likely causes.

Examples:
- missing rule
- unclear input schema
- bad tie-break
- weak validation
- outdated policy
- tool failure

#### 5.3 Patch Proposal Agent
Proposes changes but does not directly deploy them.

Possible proposals:
- add a rule
- change a decision table
- add a validation check
- improve a state transition
- add a test case
- restrict a tool

#### 5.4 Test Builder Agent
Creates tests for proposed changes.

Test types:
- deterministic repeat tests
- boundary tests
- regression tests
- policy compliance tests
- failure simulation tests

#### 5.5 Review Gate Agent
Checks whether the proposed change is safe to send for approval.

---

## 6. Deployment Pipeline
Every new or improved agent moves through controlled stages.

```text
Draft → Sandbox → Evaluation → Review → Staging → Production → Monitoring
```

### Deployment requirements

| Stage | Requirement |
|---|---|
| Draft | Agent spec exists |
| Sandbox | No production tools enabled |
| Evaluation | Required tests pass |
| Review | Human or policy approval completed |
| Staging | Limited environment run |
| Production | Versioned deployment |
| Monitoring | Metrics collected continuously |

---

## 7. Control modes

| Mode | Agent can do | Requires approval |
|---|---|---|
| Observe | Read logs and metrics | No |
| Recommend | Suggest improvements | No |
| Build draft | Create proposed agent specs | Usually no |
| Sandbox execute | Run tests in sandbox | Sometimes |
| Stage | Prepare deployable version | Yes |
| Production deploy | Change live agent | Always yes |

Recommended default: **Recommend + Build Draft + Sandbox Execute**.

---

## 8. System state machine

```text
idle
  ↓
intake_goal
  ↓
analyze_need
  ↓
select_framework
  ↓
build_or_improve
  ↓
sandbox_test
  ↓
review_gate
  ↓
deploy_or_reject
  ↓
monitor
  ↓
improve
```

---

## 9. What this system can build

DACS can build:
- deterministic routing agents
- approval agents
- compliance agents
- reporting agents
- monitoring agents
- classification agents
- scoring agents
- workflow automation agents
- data transformation agents
- evaluation agents

---

## 10. Guardrails

DACS should not silently self-modify production behavior.

Required guardrails:
- version every change
- require tests for every change
- separate sandbox and production tools
- log all decisions
- require approval for production changes
- block agents from expanding their own permissions
- preserve rollback versions
- measure before and after every improvement

---

## Summary
The Agentic Deterministic Control System is a governed meta-agent architecture. It controls existing deterministic agents, improves them through measured feedback loops, and builds new ones through an agent factory — while keeping every change explicit, tested, versioned, and auditable.


## Normative implementation contract

Use [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json) as normative. The architecture diagram is illustrative; production behavior must obey the exact promotion binding, default-deny gateway, deterministic replay tuple, and stage order defined by that contract.
