# Operator-signed bootstrap seed

This module bootstraps only the initial, unregistered evaluation agent. It is deliberately not a general-purpose import path.

## Trust model

The caller must supply a trusted public-key map from configuration outside the repository and a vetted signature verifier. The seed cannot supply a key or verifier. The built-in `verify_ed25519_signature` adapter requires the optional `cryptography` package; production callers should pin that dependency and keep private signing keys in an operator-controlled key store.

No operator private key or live signed seed is committed here. A real seed is an environment-specific release artifact signed by the authorized operator.

## Signed envelope

The envelope contains `seed_id`, `key_id`, `payload_hash`, `payload`, and a 128-character hexadecimal Ed25519 `signature`. The payload hash is `sha256(jcs(payload))`. The operator signs the UTF-8 bytes returned by `signature_message(seed_id=..., key_id=..., payload_hash=...)`, which canonically binds the signature to the seed ID, key ID, algorithm, and payload hash.

The signature must verify against the trusted 32-byte public key selected by `key_id`. Payload tampering, unknown keys, invalid signatures, invalid scopes, and expired build steps fail closed.

## Required payload invariants

- `created_by` is exactly `bootstrap` and `agent_role` is exactly `evaluation_agent`.
- `scope` is exactly `only_for_initial_unregistered_evaluation_agent_before_regular_registry_validation`.
- The signed `build_step` is at least 1, no later than the current build step, and the current build step is no later than 8. `expires_after_step` is exactly 8.
- The agent must not exist in the registry, and the seed ID must not have a prior receipt.
- Exactly one policy binding is supplied for each of `sandbox`, `staging`, and `production`.
- The evaluation suite includes all nine required test classes and uses an author distinct from `bootstrap`.
- The seed operation registers the agent, immutable version, environment policies, policy bindings, evaluation suite, and append-only receipt in one transaction. Nested savepoints ensure any failure rolls the operation back.

## Integration call

After parsing the signed envelope and loading the operator public key from a trusted source, call `seed_initial_evaluation_agent(registry, envelope, trusted_public_keys=keyring, verify_signature=verify_ed25519_signature, current_build_step=step)`. The caller must select the current build step from the governed release workflow rather than the seed itself.

The test suite uses a fake verifier strictly as a test adapter for signature flow; it is not a production signing algorithm.