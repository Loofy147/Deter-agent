import sqlite3
import threading
import time
import unittest

from deter_agent.gateway import PermissionGateway, ToolCatalog, ToolDefinition
from deter_agent.evaluation_contract import HARD_COMPONENTS, REQUIRED_TEST_TYPES, TEST_COMPONENT
from deter_agent.registry import Registry, RegistryConflict, RegistryError
from deter_agent.runtime import RuntimeEngine
from tests.helpers import make_gateway, make_policy, make_spec, make_tool_catalog, register_version_everywhere


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec = make_spec()
        self.version = register_version_everywhere(self.registry, self.spec)

    def tearDown(self):
        self.registry.close()

    def test_version_is_content_addressed_and_immutable(self):
        row = self.registry.get_version("agent-a", "v1.0.0")
        self.assertEqual(row["spec_hash"], self.version["spec_hash"])
        reordered = dict(reversed(list(self.spec.items())))
        self.assertEqual(self.registry.register_version("agent-a", "v1.0.0", reordered, created_by="builder", change_summary="same spec")["spec_hash"], row["spec_hash"])
        changed = make_spec()
        changed["purpose"] = "Different immutable content"
        with self.assertRaises(RegistryConflict):
            self.registry.register_version("agent-a", "v1.0.0", changed, created_by="builder", change_summary="illegal rewrite")

    def test_environment_policy_binding_is_per_version_and_environment(self):
        resolved = self.registry.resolve_version("agent-a", "v1.0.0", "staging")
        self.assertEqual(resolved["version"], "v1.0.0")
        self.assertEqual(resolved["environment_policy"]["environment"], "staging")
        self.assertNotEqual(
            self.registry.get_version_policy("agent-a", "v1.0.0", "staging")["policy_hash"],
            self.registry.get_version_policy("agent-a", "v1.0.0", "production")["policy_hash"],
        )

    def test_append_only_version(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute("UPDATE versions SET change_summary='rewrite' WHERE version_id='agent-a:v1.0.0'")

    def test_suite_author_must_differ_from_target_author(self):
        with self.assertRaises(RegistryError):
            self.registry.record_evaluation_suite("suite-bad", "agent-a", "v1.0.0", {"tests":[{"test_type":"regression"}]}, created_by="builder")

    def test_approval_separation_of_duties(self):
        with self.assertRaises(RegistryError):
            self.registry.record_approval(
                target_type="promotion", target_id="agent-a:v1.0.0", agent_id="agent-a", version="v1.0.0",
                target_environment="staging", requested_by="same", approver="same", decision="approved",
                spec_hash=self.version["spec_hash"], eval_run_id="e1", expires_at=time.time()+30,
                policy_diff_hash="d"*64, scope=["permission_change"],
            )

    def test_claim_state_rejects_invalid_lease_and_version_inputs(self):
        for lease in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(lease=lease):
                with self.assertRaises(RegistryError):
                    self.registry.claim_state("agent-a", "bad-lease", 0, "token", lease_seconds=lease)
        for version in (-1, True, 1.5):
            with self.subTest(version=version):
                with self.assertRaises(RegistryError):
                    self.registry.claim_state("agent-a", "bad-version", version, "token")
        with self.assertRaises(RegistryError):
            self.registry.claim_state("agent-a", "empty-token", 0, "")

    def test_all_evidence_tables_enforce_append_only_updates_and_deletes(self):
        suite = self.registry.record_evaluation_suite(
            "suite-append-only", "agent-a", "v1.0.0",
            {"tests": [
                {"test_id":f"T-{kind.upper()}","test_type":kind,"repeat_count":3 if kind=="determinism" else 1}
                for kind in REQUIRED_TEST_TYPES
            ], "required_test_types":list(REQUIRED_TEST_TYPES), "thresholds":{"maximum_latency_ms":10000.0}},
            created_by="independent-qa",
        )
        self.registry.record_evaluation(
            run_id="eval-append-only", agent_id="agent-a", version="v1.0.0",
            spec_hash=self.version["spec_hash"], suite_id=suite["suite_id"],
            policy_version="v1", engine_version="test-engine", status="passed",
            floors_met=True, coverage_complete=True,
            component_scores={**{name:1.0 for name in HARD_COMPONENTS},"performance_score":1.0},
            score=1.0,
            results=[
                {"test_id":f"T-{kind.upper()}","test_type":kind,"component":TEST_COMPONENT.get(kind,kind),
                 "passed":True,"required":True,"elapsed_ms":1.0}
                for kind in REQUIRED_TEST_TYPES
            ], created_by="independent-qa",
            started_at=100.0, completed_at=101.0,
        )
        self.registry.record_approval(
            approval_id="approval-append-only", target_type="promotion",
            target_id="agent-a:v1.0.0", agent_id="agent-a", version="v1.0.0",
            target_environment="staging", requested_by="release-requester",
            approver="independent-approver", decision="approved",
            spec_hash=self.version["spec_hash"], eval_run_id="eval-append-only",
            expires_at=time.time() + 600, policy_diff_hash="d" * 64, scope=["permission_change"],
        )
        self.registry.commit_promotion(
            binding={
                "agent_id": "agent-a", "version": "v1.0.0", "target_environment": "staging",
                "spec_hash": self.version["spec_hash"], "eval_run_id": "eval-append-only",
                "approval_event_id": "approval-append-only", "policy_diff_hash": "d" * 64,
            },
            binding_hash="b" * 64, promotion_id="promotion-append-only",
            deployed_by="release-operator", expected_previous_version_id=None,
        )
        self.registry.record_trace(
            trace_id="trace-append-only", request_id="evidence-request", agent_id="agent-a",
            version="v1.0.0", environment="staging", status="completed", details={"ok": True},
        )
        self.registry.append_frozen_decision({
            "decision_id": "frozen-append-only", "request_id": "frozen-request",
            "agent_id": "agent-a", "version": "v1.0.0", "environment": "staging",
            "spec_hash": self.version["spec_hash"], "policy_version": "v1",
            "state_version": 0, "reference_data_version": "refs-v1",
            "policy_diff_hash": "d" * 64, "idempotency_key": "idempotency-frozen",
            "decision": {"tool_name": "create_ticket"},
        })
        tables = [
            ("versions", "version_id='agent-a:v1.0.0'", "created_at"),
            ("policies", "policy_id='test-policy' AND policy_version='v1' AND environment='staging'", "created_at"),
            ("evaluation_suites", "suite_id='suite-append-only'", "created_at"),
            ("evaluation_runs", "run_id='eval-append-only'", "completed_at"),
            ("approval_events", "approval_id='approval-append-only'", "created_at"),
            ("promotion_records", "promotion_id='promotion-append-only'", "created_at"),
            ("traces", "trace_id='trace-append-only'", "created_at"),
            ("frozen_decisions", "decision_id='frozen-append-only'", "created_at"),
        ]
        for table, predicate, mutable_column in tables:
            with self.subTest(table=table, operation="UPDATE"):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.registry._connection.execute(
                        f"UPDATE {table} SET {mutable_column}={mutable_column} WHERE {predicate}"
                    )
            with self.subTest(table=table, operation="DELETE"):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.registry._connection.execute(f"DELETE FROM {table} WHERE {predicate}")

    def test_registry_rejects_passed_evaluation_with_missing_or_failing_floors(self):
        incomplete = self.registry.record_evaluation_suite(
            "suite-incomplete-pass", "agent-a", "v1.0.0",
            {"tests":[{"test_id":"ONLY-REG","test_type":"regression"}]},
            created_by="independent-qa",
        )
        with self.assertRaises(RegistryError):
            self.registry.record_evaluation(
                run_id="forged-missing-floors", agent_id="agent-a", version="v1.0.0",
                spec_hash=self.version["spec_hash"], suite_id=incomplete["suite_id"],
                policy_version="v1", engine_version="test-engine", status="passed",
                floors_met=True, coverage_complete=True, component_scores={"regression_score":1.0},
                score=1.0, results=[], created_by="independent-qa",
            )

        full_tests = [
            {"test_id":f"T-{kind.upper()}","test_type":kind,"repeat_count":3 if kind=="determinism" else 1}
            for kind in REQUIRED_TEST_TYPES
        ]
        full_suite = self.registry.record_evaluation_suite(
            "suite-failing-floor", "agent-a", "v1.0.0",
            {"tests":full_tests,"required_test_types":list(REQUIRED_TEST_TYPES),
             "thresholds":{"minimum_performance_score":0.95}},
            created_by="independent-qa",
        )
        passing_results = [
            {"test_id":f"T-{kind.upper()}","test_type":kind,"component":TEST_COMPONENT.get(kind,kind),
             "passed":True,"required":True}
            for kind in REQUIRED_TEST_TYPES
        ]
        scores = {name:1.0 for name in HARD_COMPONENTS}
        scores["performance_score"] = 1.0
        scores["policy_score"] = 0.5
        failing_results = [dict(result, passed=(result["test_type"] != "policy")) for result in passing_results]
        with self.assertRaises(RegistryError):
            self.registry.record_evaluation(
                run_id="forged-failing-floor", agent_id="agent-a", version="v1.0.0",
                spec_hash=self.version["spec_hash"], suite_id=full_suite["suite_id"],
                policy_version="v1", engine_version="test-engine", status="passed",
                floors_met=True, coverage_complete=True, component_scores=scores,
                score=1.0, results=failing_results, created_by="independent-qa",
            )

        scores["policy_score"] = 1.0
        with self.assertRaises(RegistryError):
            self.registry.record_evaluation(
                run_id="forged-inconsistent-evidence", agent_id="agent-a", version="v1.0.0",
                spec_hash=self.version["spec_hash"], suite_id=full_suite["suite_id"],
                policy_version="v1", engine_version="test-engine", status="passed",
                floors_met=True, coverage_complete=True, component_scores=scores,
                score=1.0, results=failing_results, created_by="independent-qa",
            )

    def test_promotion_transaction_rolls_back_on_duplicate_record(self):
        binding = {
            "agent_id": "agent-a", "version": "v1.0.0", "target_environment": "staging",
            "spec_hash": self.version["spec_hash"], "eval_run_id": "eval-v1",
            "policy_diff_hash": "d" * 64,
        }
        self.registry.commit_promotion(
            binding=binding, binding_hash="b" * 64, promotion_id="promotion-unique",
            deployed_by="operator", expected_previous_version_id=None,
        )
        count_before = self.registry._connection.execute(
            "SELECT COUNT(*) FROM promotion_records"
        ).fetchone()[0]
        conflicting = dict(binding, version="v9.9.9", spec_hash="x" * 64)
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.commit_promotion(
                binding=conflicting, binding_hash="c" * 64, promotion_id="promotion-unique",
                deployed_by="operator", expected_previous_version_id="agent-a:v1.0.0",
            )
        count_after = self.registry._connection.execute(
            "SELECT COUNT(*) FROM promotion_records"
        ).fetchone()[0]
        self.assertEqual(count_after, count_before)
        self.assertEqual(
            self.registry.environment_pointer("agent-a", "staging")["version"], "v1.0.0"
        )

    def test_claim_cas_prevents_concurrent_claims(self):
        barrier = threading.Barrier(3)
        result = []
        def attempt(token):
            barrier.wait()
            result.append(self.registry.claim_state("agent-a", "request-1", 0, token, lease_seconds=30))
        threads = [threading.Thread(target=attempt, args=(f"token-{n}",)) for n in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join()
        self.assertEqual(sorted(result), [False, True])

    def test_claim_released_then_reclaimed_and_cas_commits(self):
        self.assertTrue(self.registry.claim_state("agent-a", "r", 0, "one"))
        self.assertFalse(self.registry.claim_state("agent-a", "r", 0, "two"))
        self.registry.release_state_claim("agent-a", "r", "one")
        self.assertTrue(self.registry.claim_state("agent-a", "r", 0, "two"))
        self.assertEqual(self.registry.commit_state_claim("agent-a", "r", "two", 0, {"n":1}), 1)
        self.assertEqual(self.registry.load_state("agent-a", "r"), ({"n":1}, 1))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec = make_spec()
        register_version_everywhere(self.registry, self.spec)
        self.gateway = make_gateway(self.registry)

    def tearDown(self):
        self.registry.close()

    def test_explicit_tool_and_resource_allow(self):
        decision = self.gateway.authorize(
            agent_id="agent-a", version="v1.0.0", environment="staging",
            tool_name="create_ticket", action="create_ticket", target_resource="ticket_queue",
        )
        self.assertEqual(decision.decision, "allow")
        self.assertEqual(decision.data_class, "internal")
        self.assertEqual(decision.risk_level, "low")

    def test_unknown_tool_default_denies_and_counts(self):
        decision = self.gateway.authorize(
            agent_id="agent-a", version="v1.0.0", environment="staging",
            tool_name="ghost", action="execute", target_resource="ticket_queue",
        )
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(self.gateway.unauthorized_tool_attempt_count, 1)

    def test_missing_resource_denied(self):
        decision = self.gateway.authorize(
            agent_id="agent-a", version="v1.0.0", environment="staging",
            tool_name="create_ticket", action="create_ticket", target_resource=None,
        )
        self.assertEqual(decision.decision, "deny")

    def test_blocked_tool_overrides_allow(self):
        blocked_spec = make_spec(agent_id="agent-blocked", version="v1.0.1")
        self.registry.register_agent("agent-blocked")
        self.registry.register_version("agent-blocked", "v1.0.1", blocked_spec, created_by="builder", change_summary="blocked policy test")
        policy = make_policy("staging", tools=["create_ticket", "send_message"], policy_id="blocked")
        policy["blocked_tools"] = ["send_message"]
        self.registry.register_policy("blocked", "v1", "staging", policy)
        self.registry.bind_policy("agent-blocked", "v1.0.1", "staging", "blocked", "v1")
        decision = self.gateway.authorize(
            agent_id="agent-blocked", version="v1.0.1", environment="staging",
            tool_name="send_message", action="send_message", target_resource="outbound_messages",
        )
        self.assertEqual(decision.decision, "deny")

    def test_approval_required_for_sensitive_action(self):
        decision = self.gateway.authorize(
            agent_id="agent-a", version="v1.0.0", environment="production",
            tool_name="send_message", action="send_message", target_resource="outbound_messages",
        )
        self.assertEqual(decision.decision, "require_approval")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec = make_spec()
        register_version_everywhere(self.registry, self.spec)
        self.catalog = make_tool_catalog()
        self.gateway = PermissionGateway(self.registry, self.catalog)
        self.calls = []

    def tearDown(self):
        self.registry.close()

    def job(self, request_id="req-1", intent="do", environment="staging"):
        return {
            "request_id": request_id, "agent_id": "agent-a", "agent_version": "v1.0.0",
            "environment": environment, "requested_by": "requester",
            "input": {"received_at": "2026-10-26T12:00:00Z", "intent": intent},
        }

    def test_success_then_deduplicated_resubmission(self):
        def handler(action_input, idempotency_key=None):
            self.calls.append((action_input, idempotency_key))
            return {"ok":True, "ticket_id":"T-1", "new_state":{"last_intent":"do"}}
        runtime = RuntimeEngine(self.registry, self.gateway, {"create_ticket": handler})
        first = runtime.run(self.job())
        second = runtime.run(self.job())
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second, first)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.registry.load_state("agent-a", "req-1"), ({"last_intent":"do"}, 1))

    def test_timeout_retries_once_with_same_idempotency_key(self):
        keys = []
        def handler(action_input, idempotency_key=None):
            keys.append(idempotency_key)
            if len(keys) == 1:
                raise TimeoutError("injected timeout")
            return {"ok":True, "ticket_id":"T-2"}
        runtime = RuntimeEngine(self.registry, self.gateway, {"create_ticket": handler})
        result = runtime.run(self.job("retry-req"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])

    def test_non_idempotent_action_is_never_retried(self):
        catalog = make_tool_catalog(idempotent=False, supports_key=False)
        gateway = PermissionGateway(self.registry, catalog)
        calls = []
        def handler(action_input):
            calls.append(action_input)
            raise TimeoutError("injected timeout")
        runtime = RuntimeEngine(self.registry, gateway, {"create_ticket": handler})
        result = runtime.run(self.job("non-idempotent"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)

    def test_approval_pause_resumes_frozen_decision_without_redecision(self):
        calls = []
        def send(action_input, idempotency_key=None):
            calls.append((action_input, idempotency_key))
            return {"ok":True, "message_id":"M-1", "new_state":{"last_intent":"protected"}}
        runtime = RuntimeEngine(self.registry, self.gateway, {"send_message": send})
        pending = runtime.run(self.job("approve-me", "protected", "production"))
        self.assertEqual(pending["status"], "approval_pending")
        self.assertEqual(calls, [])
        frozen = self.registry.get_frozen_decision(pending["decision_id"])
        approval = self.registry.record_approval(
            target_type="runtime_action", target_id=pending["decision_id"], agent_id="agent-a",
            version="v1.0.0", target_environment="production", requested_by="requester",
            approver="independent-reviewer", decision="approved", spec_hash=frozen["spec_hash"],
            eval_run_id=None, expires_at=time.time()+600, policy_diff_hash=pending["policy_diff_hash"],
            scope=pending["approval_scope"],
        )
        completed = runtime.resume_approved(pending["decision_id"], approval["approval_id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], {"message":"pre-approved-template"})
        self.assertEqual(self.registry.load_state("agent-a", "approve-me"), ({"last_intent":"protected"}, 1))

    def test_unknown_action_is_denied_without_handler_execution(self):
        spec = make_spec(agent_id="agent-a2", action_override="not_in_catalog")
        register_version_everywhere(self.registry, spec, created_by="builder2")
        calls = []
        runtime = RuntimeEngine(self.registry, self.gateway, {"not_in_catalog": lambda payload: calls.append(payload)})
        job = self.job("unknown-action")
        job["agent_id"] = "agent-a2"
        job["agent_version"] = "v1.0.0"
        result = runtime.run(job)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(calls, [])
        self.assertGreaterEqual(self.gateway.unauthorized_tool_attempt_count, 1)

    def test_missing_received_at_is_rejected_and_traced(self):
        runtime = RuntimeEngine(self.registry, self.gateway, {"create_ticket": lambda payload: {"ok":True}})
        job = self.job("no-timestamp")
        job["input"] = {"intent":"do"}
        result = runtime.run(job)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("received_at", result["reason"])
        count = self.registry._connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        self.assertEqual(count, 1)
