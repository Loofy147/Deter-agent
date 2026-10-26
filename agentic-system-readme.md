# Agentic Deterministic System File Index

I adapted the deterministic-agent materials into a full agentic system that can control existing agents, improve them through measurement, and build new agents from templates.

## Files created

### 1. `agentic-deterministic-system-blueprint.md`
The main architecture blueprint.

Includes:
- Control Plane
- Runtime Plane
- Build Plane
- Evaluation Plane
- Improvement Plane
- Deployment Pipeline
- agent roles
- guardrails
- system state machine

Use this as the primary strategy and architecture document.

---

### 2. `agentic-control-improvement-framework.md`
The governance and improvement framework.

Includes:
- improvement loop
- control layers
- autonomy levels
- improvement proposal format
- review gates
- metrics and scorecards
- anti-patterns
- operating cadence

Use this to control how agents improve without unsafe self-modification.

---

### 3. `agent-factory-build-template.md`
The reusable template for building new deterministic agents.

Includes:
- new-agent request format
- purpose and success criteria
- framework selection
- schemas
- state model
- rules
- permissions
- evaluation suite
- registry entry
- deployment checklist

Use this whenever the system needs to create a new agent.

---

### 4. `agentic-system-manifest.yaml`
A machine-readable system manifest.

Includes:
- system principles
- planes
- agent roles
- required agent fields
- framework options
- improvement loop
- metrics
- control modes
- guardrails

Use this as a structured configuration starting point.

---

## Implementation package

These files turn the architecture into an implementable system design.

### 5. `agent-registry-schema.md`
Defines the registry database model for agents, versions, permissions, evaluations, proposals, approvals, deployments, runtime runs, and traces.

Use this to create the system of record.

---

### 6. `runtime-engine-spec.md`
Defines the controlled execution engine: job intake, queue, registry lookup, validation, state loading, decision running, permission checks, tool execution, verification, tracing, and metrics.

Use this to build the runner.

---

### 7. `evaluation-harness-spec.md`
Defines the test harness for determinism, schema validation, regression, policy checks, state transitions, failure paths, tie-breaks, and performance.

Use this to test agents before deployment.

---

### 8. `permission-policy-spec.md`
Defines the permission model, policy language, tool gateway decisions, data classes, role permissions, approval-required actions, and anti-escalation controls.

Use this to enforce control.

---

### 9. `deployment-pipeline-spec.md`
Defines promotion stages, deployment package format, versioning, approvals, rollback policy, canary release rules, and monitoring thresholds.

Use this to move agents safely from draft to production.

---

### 10. `first-agent-example.md`
Defines the first operational agents: Agent Registry Manager Agent and Evaluation Agent.

Use this to bootstrap the platform.

---

## Recommended next step

Implement in this order:

```text
1. Build Agent Registry from agent-registry-schema.md
2. Build Runtime Engine from runtime-engine-spec.md
3. Build Evaluation Harness from evaluation-harness-spec.md
4. Add Permission Gateway from permission-policy-spec.md
5. Add Deployment Pipeline from deployment-pipeline-spec.md
6. Bootstrap Agent Registry Manager + Evaluation Agent from first-agent-example.md
7. Use Agent Factory to build the first domain runtime agent
```

Suggested first domain runtime agent after the platform is bootstrapped:

```text
Support Request Router Agent
```

Why: it is concrete, measurable, and easy to evaluate with deterministic routing rules.
