"""Promotion gate binding immutable spec/evaluation/approval/policy evidence."""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from .canonical import sha256_json
from .gateway import RISK_ORDER
from .registry import Registry, RegistryConflict, RegistryError, RegistryNotFound


class PromotionDenied(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(message)


def _set(value: dict[str, Any], key: str) -> set[str]:
    raw = value.get(key, [])
    return set(raw) if isinstance(raw, list) else set()


def policy_diff(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    old = previous or {}
    expansions = {}
    restrictions = {}
    for field in ("allowed_reads", "allowed_writes", "allowed_tools"):
        added = sorted(_set(candidate, field) - _set(old, field))
        removed = sorted(_set(old, field) - _set(candidate, field))
        if added: expansions[field] = added
        if removed: restrictions[field] = removed

    # An empty data_classes_allowed list means "no additional restriction" in the
    # gateway, unlike the other allowlists where an empty list denies all.
    old_classes = _set(old, "data_classes_allowed")
    new_classes = _set(candidate, "data_classes_allowed")
    if old_classes and new_classes:
        added_classes = sorted(new_classes - old_classes)
        removed_classes = sorted(old_classes - new_classes)
        if added_classes: expansions["data_classes_allowed"] = added_classes
        if removed_classes: restrictions["data_classes_allowed"] = removed_classes
    elif old_classes and not new_classes:
        expansions["data_classes_allowed"] = sorted(old_classes)
    elif new_classes and not old_classes:
        restrictions["data_classes_allowed"] = sorted(new_classes)

    old_blocked = _set(old, "blocked_tools")
    new_blocked = _set(candidate, "blocked_tools")
    unblocked = sorted(old_blocked - new_blocked)
    blocked = sorted(new_blocked - old_blocked)
    if unblocked: expansions["unblocked_tools"] = unblocked
    if blocked: restrictions["blocked_tools"] = blocked

    old_blocked_classes = _set(old, "data_classes_blocked")
    new_blocked_classes = _set(candidate, "data_classes_blocked")
    unblocked_classes = sorted(old_blocked_classes - new_blocked_classes)
    blocked_classes = sorted(new_blocked_classes - old_blocked_classes)
    if unblocked_classes: expansions["unblocked_data_classes"] = unblocked_classes
    if blocked_classes: restrictions["blocked_data_classes"] = blocked_classes

    old_modes = old.get("tool_modes", {}) if isinstance(old.get("tool_modes", {}), dict) else {}
    new_modes = candidate.get("tool_modes", {}) if isinstance(candidate.get("tool_modes", {}), dict) else {}
    mode_rank = {"live": 0, "sandbox_only": 1, "mock_only": 2}
    loosened_modes = {}
    tightened_modes = {}
    for tool_name in sorted(set(old_modes) | set(new_modes)):
        old_mode = old_modes.get(tool_name, "live")
        new_mode = new_modes.get(tool_name, "live")
        old_rank = mode_rank.get(old_mode, 0)
        new_rank = mode_rank.get(new_mode, 0)
        if new_rank < old_rank:
            loosened_modes[tool_name] = {"from": old_mode, "to": new_mode}
        elif new_rank > old_rank:
            tightened_modes[tool_name] = {"from": old_mode, "to": new_mode}
    if loosened_modes: expansions["tool_modes"] = loosened_modes
    if tightened_modes: restrictions["tool_modes"] = tightened_modes

    old_sandbox_side_effects = old.get("sandbox_side_effects_allowed") is True
    new_sandbox_side_effects = candidate.get("sandbox_side_effects_allowed") is True
    if old_sandbox_side_effects != new_sandbox_side_effects:
        change = {"from": old_sandbox_side_effects, "to": new_sandbox_side_effects}
        if new_sandbox_side_effects:
            expansions["sandbox_side_effects_allowed"] = change
        else:
            restrictions["sandbox_side_effects_allowed"] = change

    old_approval = _set(old, "approval_required_for")
    new_approval = _set(candidate, "approval_required_for")
    no_longer_approval = sorted(old_approval - new_approval)
    new_approval_required = sorted(new_approval - old_approval)
    if no_longer_approval: expansions["removed_approval_requirements"] = no_longer_approval
    if new_approval_required: restrictions["added_approval_requirements"] = new_approval_required
    old_max = old.get("max_risk_level", "critical")
    new_max = candidate.get("max_risk_level", "critical")
    if RISK_ORDER.get(new_max, 3) > RISK_ORDER.get(old_max, 3):
        expansions["max_risk_level"] = {"from": old_max, "to": new_max}
    return {
        "previous_policy_hash": sha256_json(previous) if previous is not None else None,
        "candidate_policy_hash": sha256_json(candidate),
        "expansions": expansions,
        "restrictions": restrictions,
    }


def policy_expands(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    return bool(policy_diff(previous, candidate)["expansions"])


def canary_bucket(request_id: str) -> int:
    """Assign a logical request to a stable 0-99 cohort using the normative contract formula."""
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be a non-empty string")
    digest = hashlib.sha256(request_id.encode("utf-8", "strict")).hexdigest()
    return int(digest, 16) % 100


def is_canary_request(request_id: str, percentage: int) -> bool:
    """Return whether a request is in a deterministic canary cohort of size percentage."""
    if isinstance(percentage, bool) or not isinstance(percentage, int) or not 0 <= percentage <= 100:
        raise ValueError("percentage must be an integer between 0 and 100")
    return canary_bucket(request_id) < percentage


class PromotionGate:
    """Atomic pointer promotion with stage order and independently approved evidence."""

    def __init__(self, registry: Registry, *, clock=time.time):
        self.registry = registry
        self.clock = clock

    def promote(self, agent_id: str, version: str, environment: str, *, requested_by: str) -> dict[str, Any]:
        if environment not in {"sandbox", "staging", "production"}:
            raise PromotionDenied("STAGE_SKIPPED", "unknown target environment")
        target = self.registry.get_version(agent_id, version)
        policy_row = self.registry.get_version_policy(agent_id, version, environment)
        if not policy_row:
            raise PromotionDenied("POLICY_DENIED", "target environment policy is missing")

        previous_pointer = self.registry.environment_pointer(agent_id, environment)
        previous_version_id = previous_pointer["version_id"] if previous_pointer else None
        previous_policy = None
        if previous_pointer:
            previous_policy_row = self.registry.get_version_policy(agent_id, previous_pointer["version"], environment)
            if previous_policy_row:
                previous_policy = previous_policy_row["policy"]
        diff = policy_diff(previous_policy, policy_row["policy"])
        diff_hash = sha256_json(diff)

        # Stage order is checked before evidence and approval lookup; approval cannot authorize skipping a stage.
        if environment == "staging":
            sandbox = self.registry.environment_pointer(agent_id, "sandbox")
            if not sandbox or sandbox["version_id"] != f"{agent_id}:{version}":
                raise PromotionDenied("STAGE_SKIPPED", "target version must first be promoted to sandbox")
        elif environment == "production":
            staging = self.registry.environment_pointer(agent_id, "staging")
            if not staging or staging["version_id"] != f"{agent_id}:{version}":
                raise PromotionDenied("STAGE_SKIPPED", "target version must first be promoted to staging")
            if not self.registry.has_successful_staging(agent_id, version, target["spec_hash"]):
                raise PromotionDenied("STAGING_NOT_VERIFIED", "staging promotion evidence for this exact spec is missing")
            if previous_pointer:
                rollback_version = target.get("rollback_version")
                if not rollback_version or not self.registry.was_previously_approved_for_production(agent_id, rollback_version):
                    raise PromotionDenied("ROLLBACK_TARGET_MISSING", "subsequent production promotion requires a previously approved rollback target")

        evaluation = self.registry.latest_evaluation(agent_id, version, target["spec_hash"])
        if environment == "sandbox":
            eval_run_id = evaluation["run_id"] if evaluation else "sandbox-entry"
            approval = None
        else:
            if not evaluation or not evaluation["passed"] or not evaluation["floors_met"] or not evaluation["coverage_complete"]:
                raise PromotionDenied("EVALUATION_FLOOR_FAILED", "exact-spec evaluation evidence is absent or failed")
            eval_run_id = evaluation["run_id"]
            approval = self.registry.find_promotion_approval(
                agent_id=agent_id, version=version, environment=environment,
                spec_hash=target["spec_hash"], eval_run_id=eval_run_id,
                policy_diff_hash=diff_hash, now=self.clock(),
            )
            if not approval:
                raise PromotionDenied("APPROVAL_REQUIRED", "no approved unexpired independent approval binds to this spec, evaluation and policy diff")
            if diff["expansions"] and "permission_change" not in self._scope_values(approval["scope"]):
                raise PromotionDenied("PERMISSION_EXPANSION_NOT_APPROVED", "approval scope does not cover permission expansion")

        binding = {
            "agent_id": agent_id, "version": version, "target_environment": environment,
            "spec_hash": target["spec_hash"], "eval_run_id": eval_run_id,
            "approval_event_id": approval["approval_id"] if approval else None,
            "policy_diff_hash": diff_hash,
        }
        binding_hash = sha256_json(binding)
        try:
            self.registry.commit_promotion(
                binding=binding, binding_hash=binding_hash, promotion_id=str(uuid.uuid4()),
                deployed_by=requested_by, expected_previous_version_id=previous_version_id,
            )
        except RegistryConflict as exc:
            raise PromotionDenied("STATE_VERSION_CONFLICT", "environment pointer changed during promotion; retry with fresh evidence") from exc
        return {"status": "promoted", "binding": binding, "binding_hash": binding_hash}

    @staticmethod
    def _scope_values(scope: Any) -> set[str]:
        if isinstance(scope, str):
            return {scope}
        if isinstance(scope, list):
            return set(str(item) for item in scope)
        if isinstance(scope, dict):
            values = set()
            for key, items in scope.items():
                values.add(key)
                if isinstance(items, list): values.update(str(item) for item in items)
                elif isinstance(items, str): values.add(items)
            return values
        return set()

    def rollback_production(self, agent_id: str, target_version: str, *, approval_id: str, requested_by: str) -> dict[str, Any]:
        target = self.registry.get_version(agent_id, target_version)
        approval = self.registry.get_approval(approval_id)
        current = self.registry.environment_pointer(agent_id, "production")
        if not current:
            raise PromotionDenied("ROLLBACK_TARGET_MISSING", "there is no current production pointer to roll back")
        if not self.registry.was_previously_approved_for_production(agent_id, target_version):
            raise PromotionDenied("ROLLBACK_TARGET_MISSING", "rollback target was never previously approved for production")
        eval_record = self.registry.latest_evaluation(agent_id, target_version, target["spec_hash"])
        if not eval_record or not eval_record["passed"]:
            raise PromotionDenied("EVALUATION_FLOOR_FAILED", "rollback target's exact-spec evaluation is unavailable")
        if not (
            approval["target_type"] == "rollback" and approval["target_id"] == target_version
            and approval["agent_id"] == agent_id and approval["version"] == target_version
            and approval["target_environment"] == "production" and approval["decision"] == "approved"
            and approval["spec_hash"] == target["spec_hash"] and approval["eval_run_id"] == eval_record["run_id"]
            and approval["expires_at"] > self.clock() and approval["approver"] != approval["requested_by"]
        ):
            raise PromotionDenied("APPROVAL_REQUIRED", "rollback approval is missing, expired or mismatched")
        current_version = self.registry.get_version(agent_id, current["version"])
        current_policy_row = self.registry.get_version_policy(agent_id, current["version"], "production")
        target_policy_row = self.registry.get_version_policy(agent_id, target_version, "production")
        if not target_policy_row:
            raise PromotionDenied("POLICY_DENIED", "rollback target has no production policy")
        diff = policy_diff(current_policy_row["policy"] if current_policy_row else None, target_policy_row["policy"])
        diff_hash = sha256_json(diff)
        if approval["policy_diff_hash"] != diff_hash:
            raise PromotionDenied("APPROVAL_REQUIRED", "rollback approval does not bind to the policy diff")
        if diff["expansions"] and "permission_change" not in self._scope_values(approval["scope"]):
            raise PromotionDenied("PERMISSION_EXPANSION_NOT_APPROVED", "rollback expands permissions without approval scope")
        binding = {
            "agent_id": agent_id, "version": target_version, "target_environment": "production",
            "spec_hash": target["spec_hash"], "eval_run_id": eval_record["run_id"],
            "approval_event_id": approval_id, "policy_diff_hash": diff_hash,
        }
        binding_hash = sha256_json(binding)
        self.registry.commit_promotion(
            binding=binding, binding_hash=binding_hash, promotion_id=str(uuid.uuid4()),
            deployed_by=requested_by, expected_previous_version_id=current["version_id"], rollback=True,
        )
        return {"status": "rolled_back", "binding": binding, "binding_hash": binding_hash}
