"""One-time, operator-signed bootstrap for the initial evaluation agent.

The caller supplies an out-of-band public-key trust root and a vetted cryptographic
signature verifier. A seed cannot supply its own public key or verifier.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from .canonical import canonical_json, sha256_json
from .evaluation_contract import REQUIRED_TEST_TYPES
from .registry import Registry

BOOTSTRAP_SCOPE = "only_for_initial_unregistered_evaluation_agent_before_regular_registry_validation"
BOOTSTRAP_CREATED_BY = "bootstrap"
BOOTSTRAP_EXPIRY_STEP = 8
SIGNATURE_ALGORITHM = "Ed25519"


class BootstrapError(RuntimeError):
    """Raised when bootstrap authorization, seed contents or one-time state is invalid."""


def signature_message(*, seed_id: str, key_id: str, payload_hash: str) -> bytes:
    """Return the exact canonical bytes that must be operator-signed."""
    return canonical_json({
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "payload_hash": payload_hash,
        "seed_id": seed_id,
    }).encode("utf-8")


def verify_ed25519_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature with the optional cryptography package; no fallback."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise BootstrapError(
            "Ed25519 verification requires the cryptography package in the trusted bootstrap runner"
        ) from exc
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def seed_initial_evaluation_agent(
    registry: Registry,
    envelope: dict[str, Any],
    *,
    trusted_public_keys: Mapping[str, bytes],
    verify_signature: Callable[[bytes, bytes, bytes], bool],
    current_build_step: int,
    now: float | None = None,
) -> dict[str, Any]:
    """Verify and atomically apply a signed, hash-pinned bootstrap seed exactly once."""
    if not isinstance(envelope, dict):
        raise BootstrapError("bootstrap envelope must be an object")
    seed_id, key_id = envelope.get("seed_id"), envelope.get("key_id")
    payload_hash, signature_hex, payload = envelope.get("payload_hash"), envelope.get("signature"), envelope.get("payload")
    if not all(isinstance(x, str) and x.strip() for x in (seed_id, key_id, payload_hash, signature_hex)):
        raise BootstrapError("bootstrap envelope identifiers, hash and signature are required")
    if not isinstance(payload, dict):
        raise BootstrapError("bootstrap payload must be an object")
    if sha256_json(payload) != payload_hash:
        raise BootstrapError("bootstrap payload hash mismatch")
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise BootstrapError("bootstrap signature must be hexadecimal") from exc
    if len(signature) != 64:
        raise BootstrapError("Ed25519 signature must contain 64 bytes")
    public_key = trusted_public_keys.get(key_id)
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise BootstrapError("bootstrap key_id is not pinned to a trusted Ed25519 public key")
    if not callable(verify_signature):
        raise BootstrapError("a vetted signature verifier is required")
    try:
        verified = verify_signature(public_key, signature_message(seed_id=seed_id, key_id=key_id, payload_hash=payload_hash), signature)
    except Exception as exc:
        raise BootstrapError("bootstrap signature verifier failed closed") from exc
    if verified is not True:
        raise BootstrapError("bootstrap operator signature is invalid")

    required = {
        "created_by", "scope", "build_step", "expires_after_step", "agent_role", "agent_id", "version",
        "spec", "change_summary", "policies", "evaluation_suite", "evaluation_suite_created_by",
    }
    if not required.issubset(payload):
        raise BootstrapError(f"bootstrap payload missing fields: {sorted(required - set(payload))}")
    if payload["created_by"] != BOOTSTRAP_CREATED_BY:
        raise BootstrapError("bootstrap seed created_by must equal 'bootstrap'")
    if payload["scope"] != BOOTSTRAP_SCOPE or payload["agent_role"] != "evaluation_agent":
        raise BootstrapError("bootstrap scope only permits the initial evaluation agent")
    build_step, expiry_step = payload["build_step"], payload["expires_after_step"]
    if (
        isinstance(build_step, bool) or not isinstance(build_step, int) or not 1 <= build_step <= BOOTSTRAP_EXPIRY_STEP
        or isinstance(expiry_step, bool) or not isinstance(expiry_step, int) or expiry_step != BOOTSTRAP_EXPIRY_STEP
        or isinstance(current_build_step, bool) or not isinstance(current_build_step, int)
        or not build_step <= current_build_step <= expiry_step
    ):
        raise BootstrapError("bootstrap seed is outside its signed build-step validity window")

    agent_id, version, spec = payload["agent_id"], payload["version"], payload["spec"]
    if not isinstance(agent_id, str) or not agent_id.strip() or not isinstance(version, str) or not version.strip():
        raise BootstrapError("bootstrap agent identity must be non-empty strings")
    if not isinstance(spec, dict) or spec.get("agent_id") != agent_id or spec.get("version") != version:
        raise BootstrapError("bootstrap spec identity does not match the seed target")
    if not isinstance(payload["change_summary"], str) or not payload["change_summary"].strip():
        raise BootstrapError("bootstrap change_summary is required")
    suite_author = payload["evaluation_suite_created_by"]
    if not isinstance(suite_author, str) or not suite_author.strip() or suite_author == BOOTSTRAP_CREATED_BY:
        raise BootstrapError("bootstrap evaluation suite must have an independent author")

    policies = payload["policies"]
    if not isinstance(policies, list) or len(policies) != 3:
        raise BootstrapError("bootstrap seed must bind exactly three environment policies")
    seen_envs = set()
    for record in policies:
        if not isinstance(record, dict):
            raise BootstrapError("each bootstrap policy record must be an object")
        environment = record.get("environment")
        if not isinstance(environment, str) or environment not in {"sandbox", "staging", "production"} or environment in seen_envs:
            raise BootstrapError("bootstrap policies must uniquely cover sandbox, staging and production")
        seen_envs.add(environment)
        if not all(isinstance(record.get(k), str) and record[k].strip() for k in ("policy_id", "policy_version")):
            raise BootstrapError("bootstrap policy identity is incomplete")
        if not isinstance(record.get("policy"), dict):
            raise BootstrapError("bootstrap policy body must be an object")
    if seen_envs != {"sandbox", "staging", "production"}:
        raise BootstrapError("bootstrap policy environment coverage is incomplete")

    suite_record = payload["evaluation_suite"]
    if not isinstance(suite_record, dict) or not isinstance(suite_record.get("suite_id"), str) or not suite_record.get("suite_id") or not isinstance(suite_record.get("suite"), dict):
        raise BootstrapError("bootstrap evaluation_suite must contain suite_id and suite")
    suite = suite_record["suite"]
    tests = suite.get("tests")
    if not isinstance(tests, list) or not tests:
        raise BootstrapError("bootstrap evaluation suite must contain tests")
    test_types = {
        case["test_type"] for case in tests
        if isinstance(case, dict) and isinstance(case.get("test_type"), str)
    }
    if set(REQUIRED_TEST_TYPES) - test_types:
        raise BootstrapError("bootstrap evaluation suite must cover all nine required test classes")

    created_at = now if now is not None else time.time()
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or not math.isfinite(created_at):
        raise BootstrapError("bootstrap receipt timestamp must be finite")

    try:
        with registry._transaction() as conn:
            if conn.execute("SELECT 1 FROM bootstrap_receipts WHERE seed_id=?", (seed_id,)).fetchone():
                raise BootstrapError("bootstrap seed has already been consumed")
            if conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone():
                raise BootstrapError("bootstrap is only allowed for an unregistered evaluation agent")
            if conn.execute("SELECT 1 FROM versions WHERE agent_id=? AND version=?", (agent_id, version)).fetchone():
                raise BootstrapError("bootstrap target version is already registered")
            registry.register_agent(agent_id, now=float(created_at))
            registry.register_version(agent_id, version, spec, created_by=BOOTSTRAP_CREATED_BY,
                                      change_summary=payload["change_summary"], now=float(created_at))
            for record in sorted(policies, key=lambda item: item["environment"]):
                registry.register_policy(record["policy_id"], record["policy_version"], record["environment"],
                                         record["policy"], now=float(created_at))
                registry.bind_policy(agent_id, version, record["environment"], record["policy_id"], record["policy_version"])
            suite_created = registry.record_evaluation_suite(
                suite_record["suite_id"], agent_id, version, suite, created_by=suite_author, now=float(created_at)
            )
            conn.execute(
                """INSERT INTO bootstrap_receipts(seed_id,key_id,payload_hash,agent_id,version,build_step,expires_after_step,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (seed_id, key_id, payload_hash, agent_id, version, build_step, expiry_step, float(created_at)),
            )
    except BootstrapError:
        raise
    except Exception as exc:
        raise BootstrapError("bootstrap seed application failed and was rolled back") from exc

    return {
        "status": "seeded", "seed_id": seed_id, "payload_hash": payload_hash,
        "agent_id": agent_id, "version": version, "suite_id": suite_created["suite_id"],
        "build_step": build_step, "expires_after_step": expiry_step,
    }
