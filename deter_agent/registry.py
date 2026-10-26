"""Transactional SQLite registry with immutable specs/evidence and CAS state claims."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .canonical import canonical_json, sha256_json
from .schema import normalize_and_validate

ENVIRONMENTS = {"sandbox", "staging", "production"}
FRAMEWORKS = {
    "rule_based", "decision_table", "finite_state_machine", "workflow_engine",
    "constraint_based", "deterministic_scoring", "hybrid_rule_workflow",
}
RISK_LEVELS = {"low", "medium", "high", "critical"}


class RegistryError(RuntimeError):
    pass


class RegistryConflict(RegistryError):
    pass


class RegistryNotFound(RegistryError):
    pass


AGENT_SPEC_SCHEMA = {
    "type": "object",
    "required": ["agent_id", "version", "name", "purpose", "owner", "framework",
                 "input_schema", "output_schema", "state_model", "decision_rules", "allowed_tools"],
    "properties": {
        "agent_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "version": {"type": "string", "pattern": r"^v?[0-9]+\.[0-9]+\.[0-9]+$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "purpose": {"type": "string", "minLength": 1, "maxLength": 4000},
        "owner": {"type": "string", "minLength": 1, "maxLength": 200},
        "framework": {"type": "string", "enum": sorted(FRAMEWORKS)},
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "state_model": {"type": "object"},
        "decision_rules": {"type": "array", "minItems": 1, "items": {"type": "object"}},
        "allowed_tools": {"type": "array", "items": {"type": "string"}},
        "rollback_version": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}


_SCHEMA_DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS agents (
  agent_id TEXT PRIMARY KEY,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
  version_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  version TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  spec_hash TEXT NOT NULL,
  created_by TEXT NOT NULL,
  change_summary TEXT NOT NULL,
  rollback_version TEXT,
  created_at REAL NOT NULL,
  UNIQUE(agent_id, version)
);
CREATE TABLE IF NOT EXISTS policies (
  policy_id TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  environment TEXT NOT NULL CHECK(environment IN ('sandbox','staging','production')),
  policy_json TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(policy_id, policy_version, environment)
);
CREATE TABLE IF NOT EXISTS version_policies (
  version_id TEXT NOT NULL REFERENCES versions(version_id),
  environment TEXT NOT NULL CHECK(environment IN ('sandbox','staging','production')),
  policy_id TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  PRIMARY KEY(version_id, environment),
  FOREIGN KEY(policy_id, policy_version, environment)
    REFERENCES policies(policy_id, policy_version, environment)
);
CREATE TABLE IF NOT EXISTS env_pointers (
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  environment TEXT NOT NULL CHECK(environment IN ('sandbox','staging','production')),
  version_id TEXT NOT NULL REFERENCES versions(version_id),
  updated_at REAL NOT NULL,
  updated_by TEXT NOT NULL,
  PRIMARY KEY(agent_id, environment)
);
CREATE TABLE IF NOT EXISTS evaluation_suites (
  suite_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  version TEXT NOT NULL,
  suite_json TEXT NOT NULL,
  suite_hash TEXT NOT NULL,
  created_by TEXT NOT NULL,
  target_author TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(suite_id, suite_hash)
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
  run_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  spec_hash TEXT NOT NULL,
  suite_id TEXT NOT NULL REFERENCES evaluation_suites(suite_id),
  suite_hash TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('passed','failed','error')),
  floors_met INTEGER NOT NULL CHECK(floors_met IN (0,1)),
  coverage_complete INTEGER NOT NULL CHECK(coverage_complete IN (0,1)),
  component_scores_json TEXT NOT NULL,
  score REAL NOT NULL,
  results_json TEXT NOT NULL,
  started_at REAL NOT NULL,
  completed_at REAL NOT NULL,
  created_by TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eval_version ON evaluation_runs(agent_id, version, spec_hash, completed_at);
CREATE TABLE IF NOT EXISTS approval_events (
  approval_id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  target_environment TEXT NOT NULL CHECK(target_environment IN ('sandbox','staging','production')),
  requested_by TEXT NOT NULL,
  approver TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','expired')),
  spec_hash TEXT NOT NULL,
  eval_run_id TEXT,
  expires_at REAL NOT NULL,
  policy_diff_hash TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  CHECK(approver <> requested_by)
);
CREATE INDEX IF NOT EXISTS ix_approval_promotion
  ON approval_events(agent_id,version,target_environment,spec_hash,eval_run_id,policy_diff_hash,decision);
CREATE TABLE IF NOT EXISTS promotion_records (
  promotion_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  target_environment TEXT NOT NULL CHECK(target_environment IN ('sandbox','staging','production')),
  spec_hash TEXT NOT NULL,
  eval_run_id TEXT NOT NULL,
  approval_event_id TEXT,
  policy_diff_hash TEXT NOT NULL,
  binding_hash TEXT NOT NULL,
  previous_version_id TEXT,
  deployed_by TEXT NOT NULL,
  created_at REAL NOT NULL,
  rollback INTEGER NOT NULL DEFAULT 0 CHECK(rollback IN (0,1))
);
CREATE INDEX IF NOT EXISTS ix_promotions_stage ON promotion_records(agent_id, version, target_environment, created_at);
CREATE TABLE IF NOT EXISTS traces (
  trace_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  environment TEXT NOT NULL,
  status TEXT NOT NULL,
  details_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_states (
  agent_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  state_json TEXT NOT NULL,
  state_version INTEGER NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(agent_id, request_id)
);
CREATE TABLE IF NOT EXISTS state_claims (
  agent_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  state_version INTEGER NOT NULL,
  claim_token TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('claimed','completed','released')),
  expires_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(agent_id, request_id)
);
CREATE TABLE IF NOT EXISTS idempotency_records (
  idempotency_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  spec_hash TEXT NOT NULL,
  request_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('in_progress','approval_pending','completed','failed','rejected','escalated')),
  result_json TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(agent_id,version,spec_hash,request_id)
);
CREATE TABLE IF NOT EXISTS frozen_decisions (
  decision_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  version TEXT NOT NULL,
  environment TEXT NOT NULL CHECK(environment IN ('sandbox','staging','production')),
  spec_hash TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  state_version INTEGER NOT NULL,
  reference_data_version TEXT NOT NULL,
  policy_diff_hash TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  decision_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""

_APPEND_ONLY = (
    "versions", "policies", "evaluation_suites", "evaluation_runs",
    "approval_events", "promotion_records", "traces", "frozen_decisions",
)


class Registry:
    """SQLite-backed registry. Write APIs use BEGIN IMMEDIATE plus unique constraints."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(database), timeout=10, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA_DDL)
        for table in _APPEND_ONLY:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"deny_{table}_{operation.lower()}"
                self._connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
                )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _json(text: str | None) -> Any:
        return None if text is None else json.loads(text)

    def register_agent(self, agent_id: str, *, now: float | None = None) -> None:
        if not agent_id or len(agent_id) > 128:
            raise RegistryError("agent_id must be a non-empty identifier")
        with self._transaction() as conn:
            row = conn.execute("SELECT agent_id FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            if row:
                return
            conn.execute("INSERT INTO agents(agent_id,created_at) VALUES(?,?)", (agent_id, now or time.time()))

    def register_version(
        self,
        agent_id: str,
        version: str,
        spec: dict[str, Any],
        *,
        created_by: str,
        change_summary: str,
        rollback_version: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_and_validate(spec, AGENT_SPEC_SCHEMA)
        if normalized["agent_id"] != agent_id or normalized["version"] != version:
            raise RegistryError("spec identity must match the registry agent_id and version")
        if not created_by or not change_summary:
            raise RegistryError("created_by and change_summary are required")
        spec_rollback = normalized.get("rollback_version", rollback_version)
        if rollback_version is not None and spec_rollback != rollback_version:
            raise RegistryError("rollback_version argument must match the immutable spec")
        spec_hash = sha256_json(normalized)
        version_id = f"{agent_id}:{version}"
        created_at = now if now is not None else time.time()
        with self._transaction() as conn:
            if not conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone():
                raise RegistryNotFound(f"agent {agent_id!r} is not registered")
            existing = conn.execute("SELECT * FROM versions WHERE agent_id=? AND version=?", (agent_id, version)).fetchone()
            if existing:
                if existing["spec_hash"] != spec_hash:
                    raise RegistryConflict("registered version is immutable; create a new semantic version")
                return self._version_row(existing)
            conn.execute(
                """INSERT INTO versions(version_id,agent_id,version,spec_json,spec_hash,created_by,
                   change_summary,rollback_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (version_id, agent_id, version, canonical_json(normalized), spec_hash, created_by,
                 change_summary, spec_rollback, created_at),
            )
            return {
                "version_id": version_id, "agent_id": agent_id, "version": version,
                "spec": normalized, "spec_json": canonical_json(normalized), "spec_hash": spec_hash,
                "created_by": created_by, "change_summary": change_summary,
                "rollback_version": spec_rollback, "created_at": created_at,
            }

    def _version_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["spec"] = self._json(result.pop("spec_json"))
        return result

    def get_version(self, agent_id: str, version: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM versions WHERE agent_id=? AND version=?", (agent_id, version)
            ).fetchone()
        if not row:
            raise RegistryNotFound(f"version {agent_id}:{version} does not exist")
        return self._version_row(row)

    def register_policy(
        self, policy_id: str, policy_version: str, environment: str, policy: dict[str, Any], *, now: float | None = None
    ) -> dict[str, Any]:
        if environment not in ENVIRONMENTS:
            raise RegistryError("invalid policy environment")
        allowed = {
            "policy_id", "version", "environment", "allowed_reads", "allowed_writes", "allowed_tools",
            "blocked_tools", "approval_required_for", "data_classes_allowed", "data_classes_blocked",
            "max_risk_level", "tool_modes", "sandbox_side_effects_allowed", "created_at",
        }
        if not isinstance(policy, dict) or set(policy) - allowed:
            raise RegistryError(f"invalid policy fields: {sorted(set(policy) - allowed) if isinstance(policy, dict) else []}")
        if policy.get("policy_id", policy_id) != policy_id:
            raise RegistryError("policy_id does not match argument")
        if policy.get("version", policy_version) != policy_version:
            raise RegistryError("policy version does not match argument")
        if policy.get("environment", environment) != environment:
            raise RegistryError("policy environment does not match argument")
        normalized = normalize_and_validate(policy, {"type": "object", "additionalProperties": True})
        for field in ("allowed_reads", "allowed_writes", "allowed_tools", "blocked_tools", "approval_required_for",
                      "data_classes_allowed", "data_classes_blocked"):
            values = normalized.get(field, [])
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise RegistryError(f"{field} must be a list of strings")
            if len(values) != len(set(values)):
                raise RegistryError(f"{field} must not contain duplicates")
        if normalized.get("max_risk_level", "critical") not in RISK_LEVELS:
            raise RegistryError("invalid max_risk_level")
        if "sandbox_side_effects_allowed" in normalized and not isinstance(normalized["sandbox_side_effects_allowed"], bool):
            raise RegistryError("sandbox_side_effects_allowed must be boolean")
        if any(mode not in {"mock_only", "sandbox_only"} for mode in normalized.get("tool_modes", {}).values()):
            raise RegistryError("tool_modes values must be mock_only or sandbox_only")
        normalized.update({"policy_id": policy_id, "version": policy_version, "environment": environment})
        policy_hash = sha256_json(normalized)
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM policies WHERE policy_id=? AND policy_version=? AND environment=?",
                (policy_id, policy_version, environment),
            ).fetchone()
            if existing:
                if existing["policy_hash"] != policy_hash:
                    raise RegistryConflict("policy version is immutable")
                return {"policy_id": policy_id, "version": policy_version, "environment": environment, "policy_hash": policy_hash, "policy": normalized}
            conn.execute(
                "INSERT INTO policies(policy_id,policy_version,environment,policy_json,policy_hash,created_at) VALUES(?,?,?,?,?,?)",
                (policy_id, policy_version, environment, canonical_json(normalized), policy_hash, now if now is not None else time.time()),
            )
        return {"policy_id": policy_id, "version": policy_version, "environment": environment, "policy_hash": policy_hash, "policy": normalized}

    def bind_policy(self, agent_id: str, version: str, environment: str, policy_id: str, policy_version: str) -> None:
        if environment not in ENVIRONMENTS:
            raise RegistryError("invalid environment")
        version_id = f"{agent_id}:{version}"
        with self._transaction() as conn:
            version_row = conn.execute("SELECT 1 FROM versions WHERE version_id=?", (version_id,)).fetchone()
            if not version_row:
                raise RegistryNotFound(f"version {version_id!r} not found")
            policy = conn.execute(
                "SELECT policy_hash FROM policies WHERE policy_id=? AND policy_version=? AND environment=?",
                (policy_id, policy_version, environment),
            ).fetchone()
            if not policy:
                raise RegistryNotFound("environment-specific policy not found")
            existing = conn.execute(
                "SELECT policy_id,policy_version,policy_hash FROM version_policies WHERE version_id=? AND environment=?",
                (version_id, environment),
            ).fetchone()
            if existing:
                if tuple(existing) != (policy_id, policy_version, policy["policy_hash"]):
                    raise RegistryConflict("environment policy binding is immutable for a version")
                return
            conn.execute(
                "INSERT INTO version_policies(version_id,environment,policy_id,policy_version,policy_hash) VALUES(?,?,?,?,?)",
                (version_id, environment, policy_id, policy_version, policy["policy_hash"]),
            )

    def get_version_policy(self, agent_id: str, version: str, environment: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT p.* FROM version_policies vp JOIN policies p
                   ON p.policy_id=vp.policy_id AND p.policy_version=vp.policy_version AND p.environment=vp.environment
                   WHERE vp.version_id=? AND vp.environment=?""",
                (f"{agent_id}:{version}", environment),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["policy"] = self._json(result.pop("policy_json"))
        return result

    def resolve_version(self, agent_id: str, version: str | None, environment: str) -> dict[str, Any]:
        if environment not in ENVIRONMENTS:
            raise RegistryError("invalid runtime environment")
        if version is None:
            with self._lock:
                pointer = self._connection.execute(
                    "SELECT version_id FROM env_pointers WHERE agent_id=? AND environment=?",
                    (agent_id, environment),
                ).fetchone()
            if not pointer:
                raise RegistryNotFound(f"no {environment} version pointer for {agent_id}")
            version_id = pointer["version_id"]
            with self._lock:
                row = self._connection.execute("SELECT * FROM versions WHERE version_id=?", (version_id,)).fetchone()
            if not row:
                raise RegistryNotFound("environment pointer references a missing version")
        else:
            with self._lock:
                row = self._connection.execute(
                    "SELECT * FROM versions WHERE agent_id=? AND version=?", (agent_id, version)
                ).fetchone()
            if not row:
                raise RegistryNotFound(f"version {agent_id}:{version} does not exist")
        result = self._version_row(row)
        result["environment_policy"] = self.get_version_policy(agent_id, result["version"], environment)
        return result

    def record_evaluation_suite(
        self, suite_id: str, agent_id: str, version: str, suite: dict[str, Any], *,
        created_by: str, now: float | None = None
    ) -> dict[str, Any]:
        target = self.get_version(agent_id, version)
        if not created_by or created_by == target["created_by"]:
            raise RegistryError("suite author must differ from target version author")
        if not isinstance(suite, dict) or not isinstance(suite.get("tests"), list) or not suite["tests"]:
            raise RegistryError("evaluation suite requires a non-empty tests list")
        if not isinstance(suite.get("thresholds", {}), dict):
            raise RegistryError("suite thresholds must be an object")
        normalized = normalize_and_validate(suite, {"type": "object", "additionalProperties": True})
        suite_hash = sha256_json(normalized)
        with self._transaction() as conn:
            existing = conn.execute("SELECT * FROM evaluation_suites WHERE suite_id=?", (suite_id,)).fetchone()
            if existing:
                if existing["suite_hash"] != suite_hash:
                    raise RegistryConflict("evaluation suite ID is immutable")
                return dict(existing)
            created = now if now is not None else time.time()
            conn.execute(
                """INSERT INTO evaluation_suites(suite_id,agent_id,version,suite_json,suite_hash,created_by,target_author,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (suite_id, agent_id, version, canonical_json(normalized), suite_hash, created_by, target["created_by"], created),
            )
        return {"suite_id": suite_id, "agent_id": agent_id, "version": version, "suite": normalized, "suite_hash": suite_hash, "created_by": created_by, "target_author": target["created_by"]}

    def get_evaluation_suite(self, suite_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM evaluation_suites WHERE suite_id=?", (suite_id,)).fetchone()
        if not row:
            raise RegistryNotFound(f"suite {suite_id!r} not found")
        result = dict(row)
        result["suite"] = self._json(result.pop("suite_json"))
        return result

    def record_evaluation(
        self, *, run_id: str, agent_id: str, version: str, spec_hash: str, suite_id: str,
        policy_version: str, engine_version: str, status: str, floors_met: bool,
        coverage_complete: bool, component_scores: dict[str, float], score: float,
        results: list[dict[str, Any]], created_by: str, started_at: float | None = None,
        completed_at: float | None = None
    ) -> dict[str, Any]:
        if status not in {"passed", "failed", "error"}:
            raise RegistryError("evaluation status must be passed/failed/error")
        current = self.get_version(agent_id, version)
        suite = self.get_evaluation_suite(suite_id)
        if current["spec_hash"] != spec_hash:
            raise RegistryError("evaluation spec_hash does not match immutable version")
        if suite["agent_id"] != agent_id or suite["version"] != version:
            raise RegistryError("suite target does not match evaluation target")
        if status == "passed" and (not floors_met or not coverage_complete):
            raise RegistryError("passing evaluation requires all floors and complete coverage")
        start = started_at if started_at is not None else time.time()
        finish = completed_at if completed_at is not None else time.time()
        row = {
            "run_id": run_id, "agent_id": agent_id, "version": version,
            "spec_hash": spec_hash, "suite_id": suite_id, "suite_hash": suite["suite_hash"],
            "policy_version": policy_version, "engine_version": engine_version, "status": status,
            "floors_met": bool(floors_met), "coverage_complete": bool(coverage_complete),
            "component_scores": component_scores, "score": float(score), "results": results,
            "started_at": start, "completed_at": finish, "created_by": created_by,
        }
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO evaluation_runs(run_id,agent_id,version,spec_hash,suite_id,suite_hash,policy_version,
                   engine_version,status,floors_met,coverage_complete,component_scores_json,score,results_json,started_at,
                   completed_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, agent_id, version, spec_hash, suite_id, suite["suite_hash"], policy_version, engine_version,
                 status, int(floors_met), int(coverage_complete), canonical_json(component_scores), float(score),
                 canonical_json(results), start, finish, created_by),
            )
        return row

    def latest_evaluation(self, agent_id: str, version: str, spec_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM evaluation_runs WHERE agent_id=? AND version=? AND spec_hash=?
                   ORDER BY completed_at DESC, run_id ASC LIMIT 1""",
                (agent_id, version, spec_hash),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["floors_met"] = bool(result["floors_met"])
        result["coverage_complete"] = bool(result["coverage_complete"])
        result["component_scores"] = self._json(result.pop("component_scores_json"))
        result["results"] = self._json(result.pop("results_json"))
        result["passed"] = result["status"] == "passed" and result["floors_met"] and result["coverage_complete"]
        return result

    def record_approval(
        self, *, approval_id: str | None = None, target_type: str, target_id: str,
        agent_id: str, version: str, target_environment: str, requested_by: str,
        approver: str, decision: str, spec_hash: str, eval_run_id: str | None,
        expires_at: float, policy_diff_hash: str, scope: Any, now: float | None = None
    ) -> dict[str, Any]:
        if target_environment not in ENVIRONMENTS or decision not in {"approved", "rejected", "expired"}:
            raise RegistryError("invalid approval environment or decision")
        if not requested_by or not approver or requested_by == approver:
            raise RegistryError("approval requires an independent approver")
        if not target_id or not spec_hash or not policy_diff_hash:
            raise RegistryError("approval target, spec hash and policy diff hash are required")
        aid = approval_id or str(uuid.uuid4())
        event = {
            "approval_id": aid, "target_type": target_type, "target_id": target_id, "agent_id": agent_id,
            "version": version, "target_environment": target_environment, "requested_by": requested_by,
            "approver": approver, "decision": decision, "spec_hash": spec_hash, "eval_run_id": eval_run_id,
            "expires_at": float(expires_at), "policy_diff_hash": policy_diff_hash, "scope": scope,
            "created_at": now if now is not None else time.time(),
        }
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO approval_events(approval_id,target_type,target_id,agent_id,version,target_environment,
                   requested_by,approver,decision,spec_hash,eval_run_id,expires_at,policy_diff_hash,scope_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid,target_type,target_id,agent_id,version,target_environment,requested_by,approver,decision,spec_hash,
                 eval_run_id,float(expires_at),policy_diff_hash,canonical_json(scope),event["created_at"]),
            )
        return event

    def find_promotion_approval(
        self, *, agent_id: str, version: str, environment: str, spec_hash: str,
        eval_run_id: str, policy_diff_hash: str, now: float | None = None
    ) -> dict[str, Any] | None:
        current = now if now is not None else time.time()
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM approval_events WHERE target_type='promotion' AND target_id=? AND agent_id=? AND version=?
                   AND target_environment=? AND spec_hash=? AND eval_run_id=? AND policy_diff_hash=?
                   AND decision='approved' AND expires_at>? AND approver<>requested_by
                   ORDER BY created_at DESC, approval_id ASC LIMIT 1""",
                (f"{agent_id}:{version}", agent_id, version, environment, spec_hash, eval_run_id, policy_diff_hash, current),
            ).fetchone()
        return self._approval_row(row) if row else None

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM approval_events WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            raise RegistryNotFound(f"approval {approval_id!r} not found")
        return self._approval_row(row)

    def find_runtime_approval(self, decision_id: str, *, now: float | None = None) -> dict[str, Any] | None:
        current = now if now is not None else time.time()
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM approval_events WHERE target_type='runtime_action' AND target_id=?
                   AND decision='approved' AND expires_at>? AND approver<>requested_by
                   ORDER BY created_at DESC, approval_id ASC LIMIT 1""",
                (decision_id, current),
            ).fetchone()
        return self._approval_row(row) if row else None

    def _approval_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["scope"] = self._json(result.pop("scope_json"))
        return result

    def append_frozen_decision(self, record: dict[str, Any]) -> None:
        required = {"decision_id","request_id","agent_id","version","environment","spec_hash","policy_version",
                    "state_version","reference_data_version","policy_diff_hash","idempotency_key","decision"}
        if not required.issubset(record):
            raise RegistryError(f"frozen decision missing fields: {sorted(required-set(record))}")
        with self._transaction() as conn:
            existing = conn.execute("SELECT decision_json FROM frozen_decisions WHERE decision_id=?", (record["decision_id"],)).fetchone()
            if existing:
                if self._json(existing["decision_json"]) != record["decision"]:
                    raise RegistryConflict("frozen decision ID collision")
                return
            conn.execute(
                """INSERT INTO frozen_decisions(decision_id,request_id,agent_id,version,environment,spec_hash,
                   policy_version,state_version,reference_data_version,policy_diff_hash,idempotency_key,decision_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record["decision_id"],record["request_id"],record["agent_id"],record["version"],record["environment"],
                 record["spec_hash"],record["policy_version"],int(record["state_version"]),record["reference_data_version"],
                 record["policy_diff_hash"],record["idempotency_key"],canonical_json(record["decision"]),
                 record.get("created_at",time.time())),
            )

    def get_frozen_decision(self, decision_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM frozen_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if not row:
            raise RegistryNotFound(f"frozen decision {decision_id!r} not found")
        result = dict(row)
        result["decision"] = self._json(result.pop("decision_json"))
        return result

    def load_state(self, agent_id: str, request_id: str) -> tuple[dict[str, Any], int]:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json,state_version FROM runtime_states WHERE agent_id=? AND request_id=?",
                (agent_id, request_id),
            ).fetchone()
        if not row:
            return {}, 0
        return self._json(row["state_json"]), int(row["state_version"])

    def claim_state(self, agent_id: str, request_id: str, state_version: int, claim_token: str, *, lease_seconds: float = 60.0, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        with self._transaction() as conn:
            state = conn.execute(
                "SELECT state_version FROM runtime_states WHERE agent_id=? AND request_id=?", (agent_id,request_id)
            ).fetchone()
            actual = int(state["state_version"]) if state else 0
            if actual != state_version:
                return False
            claim = conn.execute(
                "SELECT * FROM state_claims WHERE agent_id=? AND request_id=?", (agent_id,request_id)
            ).fetchone()
            if claim and claim["status"] == "claimed" and claim["expires_at"] > current:
                return False
            conn.execute(
                """INSERT INTO state_claims(agent_id,request_id,state_version,claim_token,status,expires_at,updated_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(agent_id,request_id) DO UPDATE SET
                   state_version=excluded.state_version,claim_token=excluded.claim_token,status='claimed',
                   expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
                (agent_id,request_id,state_version,claim_token,"claimed",current+lease_seconds,current),
            )
            return True

    def commit_state_claim(self, agent_id: str, request_id: str, claim_token: str, expected_version: int, state: dict[str, Any], *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        normalized = normalize_and_validate(state, {"type": "object", "additionalProperties": True})
        with self._transaction() as conn:
            claim = conn.execute(
                "SELECT * FROM state_claims WHERE agent_id=? AND request_id=?", (agent_id,request_id)
            ).fetchone()
            if not claim or claim["status"] != "claimed" or claim["claim_token"] != claim_token or claim["state_version"] != expected_version or claim["expires_at"] <= current:
                raise RegistryConflict("state claim missing, expired, or replaced")
            row = conn.execute(
                "SELECT state_version FROM runtime_states WHERE agent_id=? AND request_id=?", (agent_id,request_id)
            ).fetchone()
            actual = int(row["state_version"]) if row else 0
            if actual != expected_version:
                raise RegistryConflict("state compare-and-swap failed")
            new_version = actual + 1
            conn.execute(
                """INSERT INTO runtime_states(agent_id,request_id,state_json,state_version,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(agent_id,request_id) DO UPDATE SET state_json=excluded.state_json,
                   state_version=excluded.state_version,updated_at=excluded.updated_at""",
                (agent_id,request_id,canonical_json(normalized),new_version,current),
            )
            conn.execute(
                "UPDATE state_claims SET status='completed',updated_at=? WHERE agent_id=? AND request_id=? AND claim_token=?",
                (current,agent_id,request_id,claim_token),
            )
            return new_version

    def release_state_claim(self, agent_id: str, request_id: str, claim_token: str, *, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._transaction() as conn:
            conn.execute(
                "UPDATE state_claims SET status='released',updated_at=? WHERE agent_id=? AND request_id=? AND claim_token=? AND status='claimed'",
                (current,agent_id,request_id,claim_token),
            )

    def lookup_request_result(self, agent_id: str, version: str, spec_hash: str, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM idempotency_records WHERE agent_id=? AND version=? AND spec_hash=? AND request_id=?""",
                (agent_id,version,spec_hash,request_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = self._json(result.pop("result_json"))
        return result

    def claim_idempotency(self, *, key: str, agent_id: str, version: str, spec_hash: str, request_id: str, action_id: str, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM idempotency_records WHERE agent_id=? AND version=? AND spec_hash=? AND request_id=?",
                (agent_id,version,spec_hash,request_id),
            ).fetchone()
            if existing:
                if existing["idempotency_key"] != key or existing["action_id"] != action_id:
                    raise RegistryConflict("logical request was rebound to a different action/idempotency key")
                return False
            conn.execute(
                """INSERT INTO idempotency_records(idempotency_key,agent_id,version,spec_hash,request_id,action_id,
                   status,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,'in_progress',NULL,?,?)""",
                (key,agent_id,version,spec_hash,request_id,action_id,current,current),
            )
            return True

    def finish_idempotency(self, key: str, status: str, result: dict[str, Any], *, now: float | None = None) -> None:
        if status not in {"approval_pending","completed","failed","rejected","escalated"}:
            raise RegistryError("invalid final idempotency status")
        current = now if now is not None else time.time()
        with self._transaction() as conn:
            cur = conn.execute(
                "UPDATE idempotency_records SET status=?,result_json=?,updated_at=? WHERE idempotency_key=?",
                (status,canonical_json(result),current,key),
            )
            if cur.rowcount != 1:
                raise RegistryNotFound("idempotency key was not claimed")

    def record_trace(self, *, trace_id: str, request_id: str, agent_id: str, version: str, environment: str, status: str, details: dict[str, Any], now: float | None = None) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO traces(trace_id,request_id,agent_id,version,environment,status,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (trace_id,request_id,agent_id,version,environment,status,canonical_json(details),now if now is not None else time.time()),
            )

    def commit_promotion(self, *, binding: dict[str, Any], binding_hash: str, promotion_id: str,
                         deployed_by: str, expected_previous_version_id: str | None, rollback: bool = False,
                         now: float | None = None) -> None:
        current = now if now is not None else time.time()
        version_id = f"{binding['agent_id']}:{binding['version']}"
        env = binding["target_environment"]
        with self._transaction() as conn:
            pointer = conn.execute(
                "SELECT version_id FROM env_pointers WHERE agent_id=? AND environment=?",
                (binding["agent_id"],env),
            ).fetchone()
            actual_previous = pointer["version_id"] if pointer else None
            if actual_previous != expected_previous_version_id:
                raise RegistryConflict("environment pointer changed during promotion; retry the gate")
            conn.execute(
                """INSERT INTO promotion_records(promotion_id,agent_id,version,target_environment,spec_hash,eval_run_id,
                   approval_event_id,policy_diff_hash,binding_hash,previous_version_id,deployed_by,created_at,rollback)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (promotion_id,binding["agent_id"],binding["version"],env,binding["spec_hash"],binding["eval_run_id"],
                 binding.get("approval_event_id"),binding["policy_diff_hash"],binding_hash,actual_previous,deployed_by,current,int(rollback)),
            )
            conn.execute(
                """INSERT INTO env_pointers(agent_id,environment,version_id,updated_at,updated_by) VALUES(?,?,?,?,?)
                   ON CONFLICT(agent_id,environment) DO UPDATE SET version_id=excluded.version_id,
                   updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (binding["agent_id"],env,version_id,current,deployed_by),
            )

    def environment_pointer(self, agent_id: str, environment: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT p.*,v.version,v.spec_hash FROM env_pointers p JOIN versions v ON v.version_id=p.version_id
                   WHERE p.agent_id=? AND p.environment=?""",
                (agent_id,environment),
            ).fetchone()
        return dict(row) if row else None

    def promotion_history(self, agent_id: str, version: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM promotion_records WHERE agent_id=?"
        args: list[Any] = [agent_id]
        if version is not None:
            query += " AND version=?"
            args.append(version)
        query += " ORDER BY created_at ASC,promotion_id ASC"
        with self._lock:
            rows = self._connection.execute(query,args).fetchall()
        return [dict(row) for row in rows]

    def has_successful_staging(self, agent_id: str, version: str, spec_hash: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM promotion_records WHERE agent_id=? AND version=? AND target_environment='staging'
                   AND spec_hash=? ORDER BY created_at DESC LIMIT 1""",
                (agent_id,version,spec_hash),
            ).fetchone()
        return row is not None

    def was_previously_approved_for_production(self, agent_id: str, version: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM promotion_records WHERE agent_id=? AND version=? AND target_environment='production'
                   AND approval_event_id IS NOT NULL ORDER BY created_at DESC LIMIT 1""",
                (agent_id,version),
            ).fetchone()
        return row is not None

    def close(self) -> None:
        with self._lock:
            self._connection.close()
