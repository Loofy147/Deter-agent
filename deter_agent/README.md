# Executable Deter-agent core

This package is the first executable reference implementation of the deterministic-control contract.

## Modules

- \`canonical.py\`: NFC normalization, canonical JSON, and SHA-256 identities.
- \`schema.py\`: deterministic JSON Schema subset with unknown-field rejection.
- \`rules.py\`: structured conditions, subset/intersection, priority order, shadow/overlap diagnostics and finite-domain coverage.
- \`registry.py\`: SQLite-backed immutable version/evidence records, environment policy bindings, approvals, state CAS claims and request-level idempotency.
- bootstrap.py: one-time operator-signed seed, Ed25519 verification interface, step-8 expiry and atomic receipt.
- \`gateway.py\`: catalogue-derived data classification/risk and default-deny environment/resource authorization.
- \`runtime.py\`: runtime FSM slice, request dedupe, approval pause/resume from a frozen decision, idempotent retry and trace finalization.
- \`evaluation.py\`: component-floor gating and cross-process replay with varying \`PYTHONHASHSEED\`.
- \`promotion.py\`: stage-order gates and immutable promotion/rollback bindings.
- \`mutations.py\`: mutation campaigns with fresh registries; surviving mutants are reported as equivalence candidates, not proof.

## Run tests

From repository root:

\`\`\`bash
python -m unittest discover -s tests -v
python scripts/generate_enums.py --check
python scripts/validate_contract.py
\`\`\`

SQLite is used for the executable reference registry. The registry supports nested savepoints for atomic multi-record bootstrap operations. Read docs/bootstrap.md before configuring a real operator-signed seed. The registry serializes write transactions with \`BEGIN IMMEDIATE\`, uses unique constraints for logical requests, and performs pointer changes atomically with append-only promotion evidence.

The current runtime is a controlled reference implementation, not a production deployment executor. Production integration still needs an adapter-specific timeout/cancellation policy, secrets management, external-service idempotency contracts, and operational observability wiring.
