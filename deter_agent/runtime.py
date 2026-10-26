"""Deterministic job execution, approval pause/resume, state fencing and idempotent retries."""
from __future__ import annotations

import inspect
import re
import threading
import time
import uuid
from typing import Any, Callable

from .canonical import sha256_json
from .gateway import GatewayDecision, PermissionGateway
from .registry import Registry, RegistryError, RegistryNotFound, RegistryConflict
from .rules import Rule, RuleEngine, RuleSet
from .schema import SchemaValidationError, normalize_and_validate

TERMINAL_STATES = {"completed", "failed", "rejected", "escalated"}
ALLOWED_ENVIRONMENTS = {"sandbox", "staging", "production"}


def _render(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{(input|state|reference_data)\.([A-Za-z0-9_.]+)\}", value)
        if not match:
            return value
        root = context.get(match.group(1), {})
        current = root
        for part in match.group(2).split("."):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"action template field {value!r} is unavailable")
            current = current[part]
        return current
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, context) for key, item in value.items()}
    return value


def _ruleset_from_spec(spec: dict[str, Any]) -> RuleSet:
    rules = []
    for raw in spec.get("decision_rules", []):
        if not isinstance(raw, dict):
            raise ValueError("decision_rules entries must be objects")
        rules.append(Rule(
            rule_id=raw["rule_id"],
            priority=raw["priority"],
            when=raw.get("when", {}),
            action=raw["action"],
            risk_rank=raw.get("risk_rank", "low"),
            operation=raw.get("operation"),
            fallback=raw.get("fallback", False),
            metadata=raw.get("metadata", {}),
        ))
    return RuleSet(tuple(rules), tuple(spec.get("required_operations", [])))


class ReferenceDataStore:
    """Immutable named/versioned reference data snapshots."""

    def __init__(self):
        self._items: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()

    def put(self, name: str, version: str, data: Any) -> str:
        if not name or not version:
            raise ValueError("reference data name and version are required")
        digest = sha256_json(data)
        key = (name, version)
        with self._lock:
            if key in self._items and sha256_json(self._items[key]) != digest:
                raise RegistryConflict("reference data version is immutable")
            self._items[key] = data
        return digest

    def snapshot(self, refs: list[Any] | None) -> tuple[dict[str, Any], str]:
        output = {}
        identity = []
        for ref in refs or []:
            if isinstance(ref, str) and "@" in ref:
                name, version = ref.rsplit("@", 1)
            elif isinstance(ref, dict) and set(ref) == {"name", "version"}:
                name, version = ref["name"], ref["version"]
            else:
                raise ValueError("reference_data_refs must use name@version or {name,version}")
            with self._lock:
                key = (name, version)
                if key not in self._items:
                    raise RegistryNotFound(f"reference data snapshot {name}@{version} is missing")
                data = self._items[key]
            digest = sha256_json(data)
            output[name] = data
            identity.append({"name": name, "version": version, "hash": digest})
        identity.sort(key=lambda item: item["name"])
        return output, sha256_json(identity)


class RuntimeEngine:
    def __init__(
        self,
        registry: Registry,
        gateway: PermissionGateway,
        handlers: dict[str, Callable[..., Any]] | None = None,
        *,
        reference_data: ReferenceDataStore | None = None,
        engine_version: str = "0.1.0",
        claim_lease_seconds: float = 300.0,
    ):
        self.registry = registry
        self.gateway = gateway
        self.handlers = handlers or {}
        self.reference_data = reference_data or ReferenceDataStore()
        self.engine_version = engine_version
        self.claim_lease_seconds = claim_lease_seconds
        self.metrics: dict[str, int] = {
            "runs": 0, "completed": 0, "failed": 0, "rejected": 0,
            "escalated": 0, "approval_pending": 0, "trace_write_failure": 0,
        }
        self._metrics_lock = threading.Lock()

    def _metric(self, name: str) -> None:
        with self._metrics_lock:
            self.metrics[name] = self.metrics.get(name, 0) + 1

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        request_id = str(job.get("request_id", "missing-request-id"))
        agent_id = str(job.get("agent_id", "missing-agent-id"))
        environment = job.get("environment", "invalid")
        if environment not in ALLOWED_ENVIRONMENTS:
            result = self._result("rejected", "INPUT_VALIDATION_FAILED", "environment is invalid", request_id=request_id)
            self._write_trace(trace_id, request_id, agent_id, "unresolved", environment, result, None)
            return result

        version = job.get("agent_version") or "unresolved"
        resolved = None
        normalized_input = None
        claim_token = None
        claim_active = False
        idempotency_key = None
        outcome: dict[str, Any] | None = None
        state = {}
        state_version = 0
        context: dict[str, Any] = {}
        decision_id: str | None = None
        try:
            resolved = self.registry.resolve_version(agent_id, job.get("agent_version"), environment)
            version = resolved["version"]
            spec = resolved["spec"]
            if resolved.get("environment_policy") is None:
                outcome = self._result("rejected", "POLICY_DENIED", "environment-specific policy is missing", request_id=request_id, version=version, spec_hash=resolved["spec_hash"])
                return outcome

            cached = self.registry.lookup_request_result(agent_id, version, resolved["spec_hash"], request_id)
            if cached:
                if cached.get("result") is not None:
                    outcome = cached["result"]
                elif cached["status"] in {"in_progress", "approval_pending"}:
                    outcome = self._result(
                        "approval_pending" if cached["status"] == "approval_pending" else "escalated",
                        "DUPLICATE_REQUEST_IN_PROGRESS",
                        "logical request already has an active execution or pending approval",
                        request_id=request_id, version=version, spec_hash=resolved["spec_hash"],
                    )
                else:
                    outcome = self._result("escalated", "IDEMPOTENCY_RECORD_INCOMPLETE", "existing request has no final result", request_id=request_id)
                return outcome

            try:
                normalized_input = normalize_and_validate(job.get("input"), spec["input_schema"])
                # Input-carried received_at is the only decision-time timestamp permitted by the contract.
                if "received_at" not in normalized_input:
                    outcome = self._result("rejected", "INPUT_VALIDATION_FAILED", "input.received_at is required for deterministic replay", request_id=request_id, version=version, spec_hash=resolved["spec_hash"])
                    return outcome
                reference_snapshot, reference_data_version = self.reference_data.snapshot(spec.get("reference_data_refs", []))
                state, state_version = self.registry.load_state(agent_id, request_id)
                claim_token = str(uuid.uuid4())
                if not self.registry.claim_state(agent_id, request_id, state_version, claim_token, lease_seconds=self.claim_lease_seconds):
                    outcome = self._result("escalated", "STATE_VERSION_CONFLICT", "state is already claimed or has changed", request_id=request_id, version=version, spec_hash=resolved["spec_hash"])
                    return outcome
                claim_active = True
                context = dict(normalized_input)
                context["input"] = normalized_input
                context["state"] = state
                context["reference_data"] = reference_snapshot
                ruleset = _ruleset_from_spec(spec)
                ruleset.raise_if_invalid()
                winner, candidates = ruleset.resolve(context)
                if winner.fallback or winner.action in {"reject", "deny", "escalate"}:
                    status = "escalated" if winner.action == "escalate" else "rejected"
                    outcome = self._result(
                        status, winner.metadata.get("reason_code", "NO_RULE_MATCHED" if winner.fallback else "RULE_REJECTED"),
                        winner.metadata.get("reason", "no rule matched; fail-closed fallback selected"),
                        request_id=request_id, version=version, spec_hash=resolved["spec_hash"],
                        rule_id=winner.rule_id, matched_rule_ids=list(candidates),
                    )
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome

                action_input_template = winner.metadata.get("action_input", {})
                action_input = _render(action_input_template, context)
                target_resource = _render(winner.metadata.get("target_resource"), context)
                action_id = sha256_json([winner.rule_id, winner.action, action_input, target_resource])
                idempotency_key = sha256_json([agent_id, version, resolved["spec_hash"], request_id, action_id])
                if not self.registry.claim_idempotency(
                    key=idempotency_key, agent_id=agent_id, version=version, spec_hash=resolved["spec_hash"],
                    request_id=request_id, action_id=action_id,
                ):
                    cached = self.registry.lookup_request_result(agent_id, version, resolved["spec_hash"], request_id)
                    outcome = cached.get("result") if cached and cached.get("result") else self._result(
                        "escalated", "IDEMPOTENCY_CONFLICT", "logical request was concurrently claimed",
                        request_id=request_id, version=version,
                    )
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome

                gateway = self.gateway.authorize(
                    agent_id=agent_id, version=version, environment=environment,
                    tool_name=winner.action, action=winner.action, target_resource=target_resource,
                )
                policy_diff_hash = sha256_json({
                    "policy_hash": gateway.policy_hash,
                    "catalog_hash": self.gateway.catalog.hash,
                    "tool": winner.action,
                    "action": winner.action,
                    "target_resource": target_resource,
                })
                decision_id = sha256_json(["decision", agent_id, version, resolved["spec_hash"], request_id, action_id])
                decision_record = {
                    "decision_id": decision_id,
                    "request_id": request_id,
                    "agent_id": agent_id,
                    "version": version,
                    "environment": environment,
                    "spec_hash": resolved["spec_hash"],
                    "policy_version": gateway.policy_version or "",
                    "state_version": state_version,
                    "reference_data_version": reference_data_version,
                    "policy_diff_hash": policy_diff_hash,
                    "idempotency_key": idempotency_key,
                    "decision": {
                        "rule_id": winner.rule_id,
                        "matched_rule_ids": list(candidates),
                        "action_id": action_id,
                        "tool_name": winner.action,
                        "action_input": action_input,
                        "target_resource": target_resource,
                        "expected_result": winner.metadata.get("expected_result", {}),
                        "new_state": _render(winner.metadata.get("new_state", state), context),
                        "mode": gateway.mode,
                        "gateway_decision": gateway.decision,
                        "policy_id": gateway.policy_id,
                        "policy_version": gateway.policy_version,
                        "policy_hash": gateway.policy_hash,
                        "policy_diff_hash": policy_diff_hash,
                        "catalog_hash": self.gateway.catalog.hash,
                        "requester": job.get("requested_by", "unknown"),
                    },
                    "created_at": time.time(),
                }

                if gateway.decision == "require_approval":
                    self.registry.append_frozen_decision(decision_record)
                    outcome = self._result(
                        "approval_pending", "APPROVAL_REQUIRED", gateway.reason,
                        request_id=request_id, version=version, spec_hash=resolved["spec_hash"],
                        decision_id=decision_id, approval_scope=gateway.approval_scope,
                        policy_diff_hash=policy_diff_hash,
                    )
                    self.registry.finish_idempotency(idempotency_key, "approval_pending", outcome)
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome

                if gateway.decision == "deny":
                    outcome = self._result(
                        "rejected", gateway.reason_code, gateway.reason, request_id=request_id,
                        version=version, spec_hash=resolved["spec_hash"], rule_id=winner.rule_id,
                    )
                    self.registry.finish_idempotency(idempotency_key, "rejected", outcome)
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome

                tool = self.gateway.catalog.get(winner.action)
                if tool is None:
                    outcome = self._result("rejected", "UNAUTHORIZED_TOOL_ATTEMPT", "action missing from catalog", request_id=request_id, version=version)
                    self.registry.finish_idempotency(idempotency_key, "rejected", outcome)
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome

                tool_result = self._execute_tool(tool.name, action_input, idempotency_key, gateway)
                expected = winner.metadata.get("expected_result")
                try:
                    tool_result = normalize_and_validate(tool_result, spec["output_schema"])
                except SchemaValidationError:
                    outcome = self._result("failed", "SCHEMA_VALIDATION_FAILED", "tool result violates the registered output schema", request_id=request_id, version=version, rule_id=winner.rule_id)
                    self.registry.finish_idempotency(idempotency_key, "failed", outcome)
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome
                if expected and not self._contains_expected(tool_result, expected):
                    outcome = self._result("failed", "VERIFICATION_FAILED", "tool result did not satisfy expected result", request_id=request_id, version=version, rule_id=winner.rule_id)
                    self.registry.finish_idempotency(idempotency_key, "failed", outcome)
                    self.registry.release_state_claim(agent_id, request_id, claim_token)
                    claim_active = False
                    return outcome
                new_state = _render(winner.metadata.get("new_state", state), context)
                if isinstance(tool_result, dict) and isinstance(tool_result.get("new_state"), dict):
                    new_state = tool_result["new_state"]
                try:
                    next_state_version = self.registry.commit_state_claim(
                        agent_id, request_id, claim_token, state_version, new_state
                    )
                    claim_active = False
                except RegistryConflict:
                    outcome = self._result("escalated", "STATE_VERSION_CONFLICT", "state compare-and-swap failed after execution", request_id=request_id, version=version, rule_id=winner.rule_id)
                    self.registry.finish_idempotency(idempotency_key, "escalated", outcome)
                    claim_active = False
                    return outcome
                outcome = self._result(
                    "completed", "ACTION_COMPLETED", "deterministic action completed and verified",
                    request_id=request_id, version=version, spec_hash=resolved["spec_hash"],
                    rule_id=winner.rule_id, action_id=action_id, decision_id=decision_id,
                    result=tool_result, state_version=next_state_version,
                )
                self.registry.finish_idempotency(idempotency_key, "completed", outcome)
                return outcome
            except (SchemaValidationError, ValueError, RegistryNotFound, RegistryError) as exc:
                outcome = self._result("rejected", "INPUT_OR_REGISTRY_VALIDATION_FAILED", str(exc), request_id=request_id, version=version)
                if idempotency_key:
                    try:
                        self.registry.finish_idempotency(idempotency_key, "rejected", outcome)
                    except Exception:
                        pass
                return outcome
            except Exception as exc:
                outcome = self._result("failed", "RUNTIME_ERROR", type(exc).__name__, request_id=request_id, version=version)
                if idempotency_key:
                    try:
                        self.registry.finish_idempotency(idempotency_key, "failed", outcome)
                    except Exception:
                        pass
                return outcome
        finally:
            if claim_active and claim_token:
                self.registry.release_state_claim(agent_id, request_id, claim_token)
            if outcome is None:
                outcome = self._result("failed", "RUNTIME_NO_OUTCOME", "execution exited without an outcome", request_id=request_id)
            self._metric("runs")
            self._metric(outcome.get("status", "failed"))
            details = {
                "trace_id": trace_id,
                "status": outcome.get("status"),
                "reason_code": outcome.get("reason_code"),
                "decision_id": decision_id,
                "spec_hash": resolved.get("spec_hash") if resolved else None,
                "input_hash": sha256_json(normalized_input) if normalized_input is not None else None,
                "engine_version": self.engine_version,
                "gateway": self.gateway.audit_summary(),
            }
            self._write_trace(trace_id, request_id, agent_id, version, environment, outcome, details)

    def _execute_tool(self, tool_name: str, action_input: Any, idempotency_key: str, gateway: GatewayDecision) -> Any:
        if gateway.decision == "mock_only" or gateway.mode == "mock":
            return {"mocked": True, "tool_name": tool_name, "accepted": True}
        definition = self.gateway.catalog.get(tool_name)
        handler = self.handlers.get(tool_name)
        if handler is None:
            raise RuntimeError(f"no handler configured for {tool_name}")
        attempts = 2 if definition and definition.idempotent and definition.supports_idempotency_key else 1
        for attempt in range(attempts):
            try:
                signature = inspect.signature(handler)
                if "idempotency_key" in signature.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
                ):
                    return handler(action_input, idempotency_key=idempotency_key)
                return handler(action_input)
            except TimeoutError:
                if attempt + 1 >= attempts:
                    raise
        raise RuntimeError("retry loop exited unexpectedly")

    @staticmethod
    def _contains_expected(actual: Any, expected: Any) -> bool:
        if isinstance(expected, dict) and isinstance(actual, dict):
            return all(key in actual and RuntimeEngine._contains_expected(actual[key], value) for key, value in expected.items())
        if isinstance(expected, list) and isinstance(actual, list):
            return len(expected) == len(actual) and all(RuntimeEngine._contains_expected(a,b) for a,b in zip(actual,expected))
        return actual == expected

    @staticmethod
    def _result(status: str, reason_code: str, reason: str, **values: Any) -> dict[str, Any]:
        return {"status": status, "reason_code": reason_code, "reason": reason, **values}

    def _write_trace(self, trace_id, request_id, agent_id, version, environment, outcome, details):
        env = environment if environment in ALLOWED_ENVIRONMENTS else "invalid"
        try:
            self.registry.record_trace(
                trace_id=trace_id, request_id=request_id, agent_id=agent_id, version=version,
                environment=env, status=outcome.get("status", "failed"),
                details={**(details or {}), "reason_code": outcome.get("reason_code")},
            )
        except Exception:
            self._metric("trace_write_failure")

    def resume_approved(self, decision_id: str, approval_id: str) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        frozen = None
        result = None
        token = None
        claim_active = False
        resume_claimed = False
        idempotency_key = None
        try:
            frozen = self.registry.get_frozen_decision(decision_id)
            idempotency_key = frozen["idempotency_key"]
            request_row = self.registry.lookup_request_result(
                frozen["agent_id"], frozen["version"], frozen["spec_hash"], frozen["request_id"]
            )
            if not request_row:
                result = self._result("rejected", "IDEMPOTENCY_RECORD_MISSING", "pending action has no idempotency record", decision_id=decision_id)
                return result
            if request_row["status"] == "in_progress":
                result = self._result("escalated", "DUPLICATE_RESUME_IN_PROGRESS", "another resume attempt owns this logical action", decision_id=decision_id)
                return result
            if request_row["status"] in {"completed", "failed", "rejected", "escalated"} and request_row.get("result") is not None:
                result = request_row["result"]
                return result
            if request_row["status"] != "approval_pending":
                result = self._result("escalated", "IDEMPOTENCY_RECORD_INCOMPLETE", "approval record is not resumable", decision_id=decision_id)
                return result
            approval = self.registry.get_approval(approval_id)
            decision = frozen["decision"]
            if not (
                approval["target_type"] == "runtime_action"
                and approval["target_id"] == decision_id
                and approval["decision"] == "approved"
                and approval["agent_id"] == frozen["agent_id"]
                and approval["version"] == frozen["version"]
                and approval["target_environment"] == frozen["environment"]
                and approval["spec_hash"] == frozen["spec_hash"]
                and approval["policy_diff_hash"] == frozen["policy_diff_hash"]
                and approval["eval_run_id"] is None
                and approval["expires_at"] > time.time()
                and approval["approver"] != approval["requested_by"]
                and self._scope_covers(approval["scope"], decision)
            ):
                return self._result("rejected", "APPROVAL_MISMATCH", "approval does not bind to this frozen decision")
            current = self.registry.resolve_version(frozen["agent_id"], frozen["version"], frozen["environment"])
            current_policy = current.get("environment_policy")
            if not current_policy or current_policy["policy_hash"] != decision["policy_hash"]:
                return self._result("rejected", "POLICY_VERSION_MISMATCH", "the policy changed while approval was pending")
            if self.gateway.catalog.hash != decision["catalog_hash"]:
                return self._result("rejected", "TOOL_CATALOG_MISMATCH", "tool catalogue changed while approval was pending")
            state, state_version = self.registry.load_state(frozen["agent_id"], frozen["request_id"])
            if state_version != frozen["state_version"]:
                return self._result("rejected", "STATE_VERSION_CONFLICT", "state changed while approval was pending")
            token = str(uuid.uuid4())
            if not self.registry.claim_state(frozen["agent_id"], frozen["request_id"], state_version, token, lease_seconds=self.claim_lease_seconds):
                return self._result("escalated", "STATE_VERSION_CONFLICT", "state is currently claimed")
            claim_active = True
            if not self.registry.claim_approval_resume(idempotency_key):
                latest = self.registry.lookup_request_result(
                    frozen["agent_id"], frozen["version"], frozen["spec_hash"], frozen["request_id"]
                )
                if latest and latest.get("result") is not None and latest["status"] in {"completed", "failed", "rejected", "escalated"}:
                    result = latest["result"]
                else:
                    result = self._result(
                        "escalated", "DUPLICATE_RESUME_IN_PROGRESS",
                        "another resume attempt claimed or completed this logical action",
                        decision_id=decision_id,
                    )
                return result
            resume_claimed = True
            tool = self.gateway.catalog.get(decision["tool_name"])
            if not tool:
                result = self._result("rejected", "UNAUTHORIZED_TOOL_ATTEMPT", "approved tool is no longer in the catalogue")
                self.registry.finish_idempotency(idempotency_key, "rejected", result)
                self.registry.release_state_claim(frozen["agent_id"], frozen["request_id"], token)
                claim_active = False
                return result
            gateway_decision = GatewayDecision(
                "mock_only" if decision["mode"] == "mock" else "allow", "APPROVAL_RESUMED",
                "resuming frozen approved decision", decision["tool_name"], frozen["environment"],
                decision["policy_id"], decision["policy_version"], decision["policy_hash"], decision["policy_diff_hash"],
                tool.data_class, tool.risk_level, tool.idempotent, tool.supports_idempotency_key,
                mode=decision["mode"], approval_scope=approval["scope"],
            )
            tool_result = self._execute_tool(decision["tool_name"], decision["action_input"], frozen["idempotency_key"], gateway_decision)
            target_spec = self.registry.get_version(frozen["agent_id"], frozen["version"])["spec"]
            try:
                tool_result = normalize_and_validate(tool_result, target_spec["output_schema"])
            except SchemaValidationError:
                result = self._result("failed", "SCHEMA_VALIDATION_FAILED", "tool result violates registered output schema", decision_id=decision_id)
                self.registry.finish_idempotency(frozen["idempotency_key"], "failed", result)
                self.registry.release_state_claim(frozen["agent_id"], frozen["request_id"], token)
                claim_active = False
                return result
            expected = decision.get("expected_result", {})
            if expected and not self._contains_expected(tool_result, expected):
                result = self._result("failed", "VERIFICATION_FAILED", "tool result did not satisfy expected result", decision_id=decision_id)
                self.registry.finish_idempotency(frozen["idempotency_key"], "failed", result)
                self.registry.release_state_claim(frozen["agent_id"], frozen["request_id"], token)
                claim_active = False
                return result
            next_state = decision.get("new_state", state)
            if isinstance(tool_result, dict) and isinstance(tool_result.get("new_state"), dict):
                next_state = tool_result["new_state"]
            next_version = self.registry.commit_state_claim(
                frozen["agent_id"], frozen["request_id"], token, state_version, next_state
            )
            claim_active = False
            result = self._result(
                "completed", "ACTION_COMPLETED", "frozen approved action executed without re-decision",
                decision_id=decision_id, result=tool_result, state_version=next_version,
                request_id=frozen["request_id"], version=frozen["version"], spec_hash=frozen["spec_hash"],
            )
            self.registry.finish_idempotency(frozen["idempotency_key"], "completed", result)
            return result
        except (RegistryError, RegistryNotFound, ValueError) as exc:
            status = "escalated" if resume_claimed else "rejected"
            result = self._result(status, "APPROVAL_RESUME_FAILED", str(exc), decision_id=decision_id)
            if resume_claimed and idempotency_key:
                try:
                    self.registry.finish_idempotency(idempotency_key, "escalated", result)
                except Exception:
                    pass
            return result
        except Exception as exc:
            result = self._result("failed", "RUNTIME_ERROR", type(exc).__name__, decision_id=decision_id)
            if resume_claimed and idempotency_key:
                try:
                    self.registry.finish_idempotency(idempotency_key, "failed", result)
                except Exception:
                    pass
            return result
        finally:
            if claim_active and token and frozen:
                self.registry.release_state_claim(frozen["agent_id"], frozen["request_id"], token)
            if frozen:
                self._metric("runs")
                self._metric((result or {}).get("status", "failed"))
                self._write_trace(
                    trace_id, frozen["request_id"], frozen["agent_id"], frozen["version"], frozen["environment"],
                    result or self._result("failed", "RUNTIME_NO_OUTCOME", "resume exited without result"),
                    {"decision_id": decision_id, "spec_hash": frozen["spec_hash"], "resume": True},
                )

    @staticmethod
    def _scope_covers(scope: Any, decision: dict[str, Any]) -> bool:
        if not isinstance(scope, dict):
            return False
        tools = scope.get("tools", [])
        actions = scope.get("actions", [])
        resources = scope.get("resources", [])
        return (
            decision["tool_name"] in tools
            and decision["tool_name"] in actions
            and (decision.get("target_resource") is None or decision.get("target_resource") in resources)
        )
