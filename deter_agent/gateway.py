"""Default-deny tool gateway with catalogue-derived risk and data classification."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .canonical import sha256_json
from .registry import Registry, RegistryError

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
READ_OPERATIONS = {"read", "list", "fetch", "search"}
WRITE_OPERATIONS = {"write", "create", "update", "delete", "send", "execute", "deploy"}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    environments: tuple[str, ...]
    data_class: str
    risk_level: str
    idempotent: bool
    supports_idempotency_key: bool
    resource_operation: str = "write"
    side_effect: bool = True
    catalog_version: str = "1"

    def __post_init__(self):
        if not self.name:
            raise ValueError("tool name is required")
        if not self.environments or any(e not in {"sandbox", "staging", "production"} for e in self.environments):
            raise ValueError("tool environments must be explicit supported environments")
        if self.risk_level not in RISK_ORDER:
            raise ValueError("invalid catalog risk level")
        if self.resource_operation not in READ_OPERATIONS | WRITE_OPERATIONS | {"none"}:
            raise ValueError("resource_operation must be read, write, or none")


class ToolCatalog:
    def __init__(self, definitions: list[ToolDefinition] | tuple[ToolDefinition, ...], *, version: str = "1"):
        self.version = version
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"duplicate tool definition {definition.name!r}")
            self._definitions[definition.name] = definition
        self.hash = sha256_json({
            "version": version,
            "tools": [
                {
                    "name": d.name, "environments": list(d.environments), "data_class": d.data_class,
                    "risk_level": d.risk_level, "idempotent": d.idempotent,
                    "supports_idempotency_key": d.supports_idempotency_key,
                    "resource_operation": d.resource_operation, "side_effect": d.side_effect,
                    "catalog_version": d.catalog_version,
                }
                for d in sorted(self._definitions.values(), key=lambda item: item.name)
            ],
        })

    def get(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def all(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))


@dataclass(frozen=True)
class GatewayDecision:
    decision: str
    reason_code: str
    reason: str
    tool_name: str
    environment: str
    policy_id: str | None
    policy_version: str | None
    policy_hash: str | None
    policy_diff_hash: str | None
    data_class: str | None
    risk_level: str | None
    idempotent: bool = False
    supports_idempotency_key: bool = False
    mode: str = "live"
    approval_scope: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision in {"allow", "mock_only", "sandbox_only"}


class PermissionGateway:
    """Enforces versioned policy. Caller-provided risk and data-class values are not accepted."""

    def __init__(self, registry: Registry, catalog: ToolCatalog):
        self.registry = registry
        self.catalog = catalog
        self.unauthorized_tool_attempt_count = 0

    def policy_identity(self, agent_id: str, version: str, environment: str) -> dict[str, Any] | None:
        policy_row = self.registry.get_version_policy(agent_id, version, environment)
        if not policy_row:
            return None
        return {
            "policy_id": policy_row["policy_id"],
            "policy_version": policy_row["policy_version"],
            "policy_hash": policy_row["policy_hash"],
        }

    def authorize(
        self,
        *,
        agent_id: str,
        version: str,
        environment: str,
        tool_name: str,
        action: str,
        target_resource: str | None,
    ) -> GatewayDecision:
        def deny(code: str, reason: str, definition: ToolDefinition | None = None, identity=None):
            if code == "UNAUTHORIZED_TOOL_ATTEMPT":
                self.unauthorized_tool_attempt_count += 1
            return GatewayDecision(
                "deny", code, reason, tool_name, environment,
                identity.get("policy_id") if identity else None,
                identity.get("policy_version") if identity else None,
                identity.get("policy_hash") if identity else None,
                identity.get("policy_hash") if identity else None,
                definition.data_class if definition else None,
                definition.risk_level if definition else None,
                definition.idempotent if definition else False,
                definition.supports_idempotency_key if definition else False,
            )

        definition = self.catalog.get(tool_name)
        if definition is None:
            return deny("UNAUTHORIZED_TOOL_ATTEMPT", "tool is not in the versioned catalogue")
        if environment not in {"sandbox", "staging", "production"}:
            return deny("POLICY_DENIED", "unknown execution environment", definition)
        policy_row = self.registry.get_version_policy(agent_id, version, environment)
        if not policy_row:
            return deny("POLICY_DENIED", "environment-specific policy is missing", definition)
        policy = policy_row["policy"]
        identity = {
            "policy_id": policy_row["policy_id"],
            "policy_version": policy_row["policy_version"],
            "policy_hash": policy_row["policy_hash"],
        }
        base = dict(
            policy_id=identity["policy_id"], policy_version=identity["policy_version"],
            policy_hash=identity["policy_hash"], policy_diff_hash=identity["policy_hash"],
            data_class=definition.data_class, risk_level=definition.risk_level,
            idempotent=definition.idempotent,
            supports_idempotency_key=definition.supports_idempotency_key,
        )

        if environment not in definition.environments:
            decision = "sandbox_only" if "sandbox" in definition.environments else "deny"
            return GatewayDecision(
                decision, "POLICY_DENIED", "tool is not enabled in this environment",
                tool_name, environment, **identity, policy_diff_hash=identity["policy_hash"],
                data_class=definition.data_class, risk_level=definition.risk_level,
                idempotent=definition.idempotent, supports_idempotency_key=definition.supports_idempotency_key,
                mode="sandbox" if decision == "sandbox_only" else "live"
            )
        if tool_name in policy.get("blocked_tools", []):
            return GatewayDecision("deny", "POLICY_DENIED", "tool is explicitly blocked", tool_name, environment, **base)
        if tool_name not in policy.get("allowed_tools", []):
            return deny("UNAUTHORIZED_TOOL_ATTEMPT", "tool is not explicitly allowed by this environment policy", definition, identity)
        if definition.data_class == "secrets" or definition.data_class in policy.get("data_classes_blocked", []):
            return GatewayDecision("deny", "POLICY_DENIED", "catalogue data class is blocked", tool_name, environment, **base)
        allowed_classes = policy.get("data_classes_allowed")
        if allowed_classes and definition.data_class not in allowed_classes:
            return GatewayDecision("deny", "POLICY_DENIED", "catalogue data class is not allowed", tool_name, environment, **base)
        max_risk = policy.get("max_risk_level", "critical")
        if RISK_ORDER[definition.risk_level] > RISK_ORDER[max_risk]:
            return GatewayDecision("deny", "POLICY_DENIED", "catalogue risk exceeds policy maximum", tool_name, environment, **base)

        if definition.resource_operation != "none":
            if target_resource:
                if definition.resource_operation in READ_OPERATIONS:
                    resource_allowed = target_resource in policy.get("allowed_reads", [])
                else:
                    resource_allowed = target_resource in policy.get("allowed_writes", [])
                if not resource_allowed:
                    return GatewayDecision("deny", "POLICY_DENIED", "target resource is not allowed for this operation", tool_name, environment, **base)
            else:
                return GatewayDecision("deny", "POLICY_DENIED", "target resource is required by the tool catalogue", tool_name, environment, **base)

        mode = policy.get("tool_modes", {}).get(tool_name, "live")
        if mode == "sandbox_only" and environment != "sandbox":
            return GatewayDecision("deny", "POLICY_DENIED", "policy restricts tool to sandbox", tool_name, environment, **base)
        if mode == "mock_only":
            return GatewayDecision("mock_only", "MOCK_ONLY", "policy requires mock/dry-run adapter", tool_name, environment, mode="mock", **base)
        if environment == "sandbox" and definition.side_effect and policy.get("sandbox_side_effects_allowed") is not True:
            # Sandbox should be mock-only by default, not a route to a live side effect.
            return GatewayDecision("mock_only", "MOCK_ONLY", "sandbox side effects default to a mock adapter", tool_name, environment, mode="mock", **base)

        required = set(policy.get("approval_required_for", []))
        trigger_values = {action, tool_name}
        if target_resource:
            trigger_values.add(f"{target_resource}:{action}")
        if required & trigger_values:
            return GatewayDecision(
                "require_approval", "APPROVAL_REQUIRED", "action requires an independent approval",
                tool_name, environment, **base, mode="live",
                approval_scope={"tools": [tool_name], "actions": [action], "resources": [target_resource] if target_resource else []}
            )
        return GatewayDecision("allow", "ALLOWED", "explicit tool/resource authorization passed", tool_name, environment, mode="live", **base)

    def audit_summary(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog.version,
            "catalog_hash": self.catalog.hash,
            "unauthorized_tool_attempt_count": self.unauthorized_tool_attempt_count,
        }
