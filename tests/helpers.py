from __future__ import annotations

from typing import Any

from deter_agent.gateway import PermissionGateway, ToolCatalog, ToolDefinition
from deter_agent.registry import Registry


def make_spec(agent_id="agent-a", version="v1.0.0", rollback_version=None, action_override=None):
    create_action = action_override or "create_ticket"
    spec = {
        "agent_id": agent_id,
        "version": version,
        "name": "Test agent",
        "purpose": "Exercise deterministic routing and controlled actions.",
        "owner": "platform-team",
        "framework": "decision_table",
        "input_schema": {
            "type": "object",
            "required": ["received_at", "intent"],
            "properties": {
                "received_at": {"type": "string", "minLength": 1},
                "intent": {"type": "string", "enum": ["do", "protected", "unknown"]},
            },
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "required": ["ok"],
            "properties": {
                "ok": {"type": "boolean"},
                "ticket_id": {"type": "string"},
                "message_id": {"type": "string"},
                "new_state": {"type": "object"},
                "tool_name": {"type": "string"},
                "mocked": {"type": "boolean"},
                "accepted": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "state_model": {"initial_state": {}, "state_versioned": True},
        "decision_rules": [
            {
                "rule_id": "ROUTE-DO",
                "priority": 10,
                "when": {"intent": {"eq": "do"}},
                "action": create_action,
                "risk_rank": "low",
                "metadata": {
                    "target_resource": "ticket_queue",
                    "action_input": {"intent": "do"},
                    "expected_result": {"ok": True},
                    "new_state": {"last_intent": "do"},
                },
            },
            {
                "rule_id": "SEND-PROTECTED",
                "priority": 10,
                "when": {"intent": {"eq": "protected"}},
                "action": "send_message",
                "risk_rank": "medium",
                "metadata": {
                    "target_resource": "outbound_messages",
                    "action_input": {"message": "pre-approved-template"},
                    "expected_result": {"ok": True},
                    "new_state": {"last_intent": "protected"},
                },
            },
            {
                "rule_id": "FALLBACK",
                "priority": 999,
                "when": {},
                "action": "reject",
                "fallback": True,
                "metadata": {"reason_code": "NO_RULE_MATCHED"},
            },
        ],
        "allowed_tools": [create_action, "send_message"],
        "reference_data_refs": [],
    }
    if rollback_version is not None:
        spec["rollback_version"] = rollback_version
    return spec


def make_policy(environment: str, *, tools=None, approvals=None, sandbox_side_effects=False, policy_id="test-policy"):
    return {
        "policy_id": policy_id,
        "version": "v1",
        "environment": environment,
        "allowed_reads": ["customer_tier_table"],
        "allowed_writes": ["ticket_queue", "outbound_messages"],
        "allowed_tools": list(tools or ["create_ticket", "send_message"]),
        "blocked_tools": [],
        "approval_required_for": list(approvals or ["send_message"]),
        "data_classes_allowed": ["internal", "customer_limited"],
        "data_classes_blocked": ["secrets", "payment_full"],
        "max_risk_level": "high",
        "tool_modes": {},
        "sandbox_side_effects_allowed": sandbox_side_effects,
    }


def make_tool_catalog(*, idempotent=True, supports_key=True):
    return ToolCatalog([
        ToolDefinition(
            name="create_ticket", environments=("sandbox", "staging", "production"),
            data_class="internal", risk_level="low", idempotent=idempotent,
            supports_idempotency_key=supports_key, resource_operation="write",
            side_effect=True, catalog_version="v1",
        ),
        ToolDefinition(
            name="send_message", environments=("staging", "production"),
            data_class="customer_limited", risk_level="medium", idempotent=True,
            supports_idempotency_key=True, resource_operation="write",
            side_effect=True, catalog_version="v1",
        ),
        ToolDefinition(
            name="read_customer_tier", environments=("sandbox", "staging", "production"),
            data_class="internal", risk_level="low", idempotent=True,
            supports_idempotency_key=True, resource_operation="read",
            side_effect=False, catalog_version="v1",
        ),
    ], version="v1")


def register_version_everywhere(registry: Registry, spec: dict[str, Any], *, created_by="builder", bind_environments=True):
    agent_id, version = spec["agent_id"], spec["version"]
    registry.register_agent(agent_id)
    version_row = registry.register_version(agent_id, version, spec, created_by=created_by, change_summary="test fixture")
    if bind_environments:
        for env in ("sandbox", "staging", "production"):
            policy = make_policy(env, sandbox_side_effects=(env == "sandbox"))
            registry.register_policy(policy["policy_id"], policy["version"], env, policy)
            registry.bind_policy(agent_id, version, env, policy["policy_id"], policy["version"])
    return version_row


def make_gateway(registry: Registry, *, catalog=None):
    return PermissionGateway(registry, catalog or make_tool_catalog())
