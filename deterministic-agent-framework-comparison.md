# Deterministic Agent Framework Comparison

## Purpose
This document compares major framework patterns for deterministic agents. Use it to choose the right design depending on whether the agent needs to route, classify, approve, prioritize, orchestrate, or enforce policy.

---

## Comparison table

| Framework | Best for | Determinism level | Strengths | Weaknesses | Example use case |
|---|---|---:|---|---|---|
| Rule-based system | Simple explicit business logic | Very high | Transparent, easy to explain, easy to test | Can become brittle as rules grow | Compliance routing |
| Decision table | Many condition/action combinations | Very high | Compact, auditable, business-readable | Harder to maintain with too many dimensions | Approval decisions |
| Finite-state machine | Step-by-step workflows | Very high | Predictable transitions, easy debugging | Rigid for flexible work | Support ticket lifecycle |
| Workflow engine | Operational orchestration | High | Handles handoffs, retries, approvals, timers | Requires process modeling | Employee onboarding |
| Constraint-based system | Hard limits and policies | High | Strong safety and compliance | May be complex or restrictive | Resource scheduling |
| Deterministic scoring | Ranking and prioritization | High | Measurable, tunable, good for ordering | Score design can be subjective | Lead prioritization |
| Planning with fixed tie-breaks | Path or action selection | High | Repeatable planning outcomes | More complex to implement | Multi-step task planning |
| Hybrid rule + workflow | Real-world operational systems | High | Practical and scalable | Requires strong governance | Operations automation |

---

## Framework details

### 1. Rule-based system
Uses explicit `if/then` rules.

Best when:
- logic is simple
- business rules are stable
- decisions need to be explainable

Example:
```text
IF customer_tier = enterprise AND issue_severity = high
THEN route_to = priority_support
```

Use when transparency matters more than flexibility.

---

### 2. Decision table
Uses a structured matrix of conditions and actions.

Best when:
- many conditions interact
- business users need to review logic
- auditability is required

Example:

| Customer tier | Amount | Risk | Action |
|---|---:|---|---|
| Enterprise | < 500 | Low | Auto-approve |
| Enterprise | >= 500 | Medium | Manager review |
| Standard | >= 100 | High | Reject or escalate |

Use when rule combinations are more important than process flow.

---

### 3. Finite-state machine
Defines states and allowed transitions.

Example states:
```text
received → validated → classified → decided → executed → completed
```

Best when:
- the process has clear stages
- invalid transitions must be blocked
- debugging needs to be simple

Use when lifecycle control matters.

---

### 4. Workflow engine
Coordinates a business process across steps, systems, and people.

Best when:
- there are handoffs
- some steps are asynchronous
- approvals are required
- retries and timeouts matter

Use when the agent is part of an operational process.

---

### 5. Constraint-based system
Chooses only actions that satisfy hard constraints.

Examples of constraints:
- budget limit
- policy rule
- capacity limit
- time window
- permission boundary

Use when safety and compliance are more important than speed or flexibility.

---

### 6. Deterministic scoring
Ranks options using a fixed formula.

Example:
```text
score = priority_weight + urgency_weight + customer_value - risk_penalty
```

Tie-break example:
```text
If scores are equal, choose earliest created request.
If still equal, choose lexicographic order by request_id.
```

Use when options must be prioritized consistently.

---

### 7. Planning with fixed tie-breaks
Uses planning/search but removes randomness from path choice.

Best when:
- tasks require multiple steps
- there are several valid paths
- the same plan should be selected every time

Use only if planning is needed; simpler frameworks are easier to audit.

---

### 8. Hybrid rule + workflow
Combines workflow orchestration with deterministic decision points.

Typical design:
```text
Workflow engine controls process.
Decision tables choose actions.
State machine controls lifecycle.
Rules enforce policies.
```

This is often the best production pattern.

---

## Selection guide

| If you need... | Use... |
|---|---|
| Simple explainable logic | Rule-based system |
| Many condition combinations | Decision table |
| Strict process states | Finite-state machine |
| Business process orchestration | Workflow engine |
| Hard policy boundaries | Constraint-based system |
| Ranking or prioritization | Deterministic scoring |
| Multi-step plan selection | Planning with fixed tie-breaks |
| Production operational automation | Hybrid rule + workflow |

---

## Evaluation criteria

When choosing a framework, evaluate:
- repeatability
- explainability
- testability
- maintainability
- scalability
- auditability
- implementation complexity
- ease of policy updates
- suitability for human review

---

## Recommended production stack

For most deterministic agents:

```text
Workflow engine
+ State machine
+ Decision tables
+ Rule-based policy checks
+ Deterministic scoring only where ranking is needed
+ Full logging and replay
```

This balances control, scale, and auditability.

---

## Summary
Determinism is not one framework. It is a property created by explicit state, fixed logic, stable tie-breaks, versioning, verification, and logging. The framework should match the type of decision the agent must make.
