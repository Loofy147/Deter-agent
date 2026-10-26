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

## Normative contract and implementation order

The authoritative rules are [DETERMINISTIC-CONTROL-CONTRACT.md](DETERMINISTIC-CONTROL-CONTRACT.md) and [contracts/deterministic-control-contract.json](contracts/deterministic-control-contract.json). Examples are subordinate to those files. Run `python scripts/validate_contract.py` for the contract's static checks.

Implement in dependency order:

```text
1. canonicalization + shared enums
2. registry with static checks
3. permission gateway deny-all stub
4. runtime
5. evaluation harness
6. deployment gate
7. operator-signed bootstrap seed
8. first agents
```

The bootstrap seed is operator-signed, hash-pinned and sandbox-only; its temporary trust exception expires after step 8.

Suggested first domain runtime agent after the platform is bootstrapped:

```text
Support Request Router Agent
```

Why: it is concrete, measurable, and easy to evaluate with deterministic routing rules.


## Executable implementation

The `deter_agent/` package provides the reference implementation for canonical serialization, schema validation, rule matching/shadow analysis, SQLite registry, policy gateway, runtime, evaluation, promotion/rollback, and mutation campaigns. CI exercises normalization, decision ordering, state CAS, approval resumption, retries/idempotency, stage order, rollback and mutation killing.

Run from repository root:

```text
python -m unittest discover -s tests -v
python scripts/generate_enums.py --check
python scripts/validate_contract.py
```

This is an executable reference core, not a production integration. External adapters, secret management, cancellation guarantees and operational telemetry still require deployment-specific implementation.

## Canonical source rules

- Shared enums are sourced from `contracts/deterministic-control-contract.json`.
- The contract validator runs in GitHub Actions for pushes to `main` and pull requests.
- `agentic-system-manifest.yaml` is the only manifest file. The duplicated upload-name copies are removed.
- Promotion binds an immutable spec hash, an evaluation run, an independent unexpired approval, and a policy diff; no record may be substituted after evaluation.
