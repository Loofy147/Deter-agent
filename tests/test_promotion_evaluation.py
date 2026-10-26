import threading
import time
import unittest

from deter_agent.evaluation import EvaluationHarness
from deter_agent.promotion import PromotionDenied, PromotionGate, canary_bucket, is_canary_request, policy_diff
from deter_agent.canonical import sha256_json
from deter_agent.evaluation_contract import HARD_COMPONENTS, REQUIRED_TEST_TYPES, TEST_COMPONENT
from deter_agent.registry import Registry, RegistryConflict
from tests.helpers import make_policy, make_spec


def register_version(registry, version, rollback=None, created_by="builder"):
    spec = make_spec(version=version, rollback_version=rollback)
    registry.register_agent("agent-a")
    version_row = registry.register_version(
        "agent-a", version, spec, created_by=created_by, change_summary=f"register {version}"
    )
    for env in ("sandbox", "staging", "production"):
        registry.register_policy("policy-a", "v1", env, make_policy(env, sandbox_side_effects=(env == "sandbox"), policy_id="policy-a"))
        registry.bind_policy("agent-a", version, env, "policy-a", "v1")
    suite = registry.record_evaluation_suite(
        f"suite-{version}", "agent-a", version,
        {
            "tests":[
                {"test_id":f"T-{kind.upper()}","test_type":kind,"repeat_count":3 if kind=="determinism" else 1}
                for kind in REQUIRED_TEST_TYPES
            ],
            "required_test_types":list(REQUIRED_TEST_TYPES),
            "thresholds":{"minimum_performance_score":0.0,"maximum_latency_ms":10000.0},
        },
        created_by="independent-qa",
    )
    report = registry.record_evaluation(
        run_id=f"eval-{version}", agent_id="agent-a", version=version, spec_hash=version_row["spec_hash"],
        suite_id=suite["suite_id"], policy_version="v1", engine_version="test-engine",
        status="passed", floors_met=True, coverage_complete=True,
        component_scores={**{name:1.0 for name in HARD_COMPONENTS},"performance_score":1.0}, score=0.99,
        results=[
            {"test_id":f"T-{kind.upper()}","test_type":kind,"component":TEST_COMPONENT.get(kind,kind),
             "passed":True,"required":True,"elapsed_ms":1.0}
            for kind in REQUIRED_TEST_TYPES
        ], created_by="independent-qa",
        started_at=100.0, completed_at=101.0,
    )
    return version_row, report


def approve(registry, version_row, eval_run_id, environment, policy, *, target_type="promotion", target_id=None, scope=None):
    diff_hash = __import__("deter_agent.canonical", fromlist=["sha256_json"]).sha256_json(policy_diff(None, policy))
    return registry.record_approval(
        target_type=target_type,
        target_id=target_id if target_id is not None else f"agent-a:{version_row['version']}",
        agent_id="agent-a", version=version_row["version"], target_environment=environment,
        requested_by="release-requester", approver="independent-approver", decision="approved",
        spec_hash=version_row["spec_hash"], eval_run_id=eval_run_id, expires_at=time.time()+600,
        policy_diff_hash=diff_hash, scope=scope or ["permission_change"],
    )


class CanaryAssignmentTests(unittest.TestCase):
    def test_bucket_matches_normative_sha256_utf8_modulo_formula(self):
        import hashlib
        for request_id in ("request-1", "alpha", "é", "e\u0301", "请求-42"):
            with self.subTest(request_id=request_id):
                expected = int(hashlib.sha256(request_id.encode("utf-8")).hexdigest(), 16) % 100
                self.assertEqual(canary_bucket(request_id), expected)
                self.assertEqual(canary_bucket(request_id), canary_bucket(request_id))

    def test_percent_boundaries_and_deterministic_membership(self):
        bucket = canary_bucket("canary-request")
        self.assertFalse(is_canary_request("canary-request", 0))
        self.assertTrue(is_canary_request("canary-request", 100))
        self.assertEqual(is_canary_request("canary-request", bucket), bucket > 0)
        self.assertEqual(is_canary_request("canary-request", bucket + 1), True)

    def test_invalid_canary_inputs_are_rejected(self):
        for request_id in ("", None, 7):
            with self.subTest(request_id=request_id):
                with self.assertRaises(ValueError):
                    canary_bucket(request_id)
        for percentage in (-1, 101, True, 10.0, "10"):
            with self.subTest(percentage=percentage):
                with self.assertRaises(ValueError):
                    is_canary_request("request", percentage)


class PolicyDiffAdversarialTests(unittest.TestCase):
    def test_unblocking_data_classes_is_a_permission_expansion(self):
        previous = make_policy("production", policy_id="policy-old")
        candidate = dict(previous)
        candidate["data_classes_blocked"] = ["secrets"]
        diff = policy_diff(previous, candidate)
        self.assertEqual(diff["expansions"]["unblocked_data_classes"], ["payment_full"])
        self.assertTrue(diff["expansions"])

    def test_sandbox_side_effect_enablement_and_tool_mode_loosening_expand(self):
        previous = make_policy("sandbox", policy_id="policy-old", sandbox_side_effects=False)
        previous["tool_modes"] = {"create_ticket": "mock_only", "send_message": "sandbox_only"}
        candidate = dict(previous)
        candidate["sandbox_side_effects_allowed"] = True
        candidate["tool_modes"] = {"create_ticket": "sandbox_only", "send_message": "live"}
        diff = policy_diff(previous, candidate)
        self.assertTrue(diff["expansions"]["sandbox_side_effects_allowed"]["to"])
        self.assertIn("create_ticket", diff["expansions"]["tool_modes"])
        self.assertIn("send_message", diff["expansions"]["tool_modes"])
        self.assertNotIn("tool_modes", diff["restrictions"])

    def test_empty_data_class_allowlist_is_unrestricted(self):
        unrestricted = make_policy("production", policy_id="policy-unrestricted")
        unrestricted["data_classes_allowed"] = []
        restricted = dict(unrestricted)
        restricted["data_classes_allowed"] = ["internal"]
        restrict_diff = policy_diff(unrestricted, restricted)
        self.assertEqual(restrict_diff["restrictions"]["data_classes_allowed"], ["internal"])
        self.assertNotIn("data_classes_allowed", restrict_diff["expansions"])
        loosen_diff = policy_diff(restricted, unrestricted)
        self.assertEqual(loosen_diff["expansions"]["data_classes_allowed"], ["internal"])
        self.assertNotIn("data_classes_allowed", loosen_diff["restrictions"])


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec, self.eval_row = register_version(self.registry, "v1.0.0")

    def tearDown(self):
        self.registry.close()

    def test_evaluation_harness_requires_all_component_classes(self):
        suite = {
            "required_test_types": list(REQUIRED_TEST_TYPES),
            "performance_score": 1.0,
            "thresholds": {"minimum_performance_score": 0.95, "maximum_latency_ms": 1000.0},
            "tests": [
                {"test_id": kind, "test_type":kind, "repeat_count":3 if kind=="determinism" else 1,
                 "expected_output":{"status":"ok"}}
                for kind in REQUIRED_TEST_TYPES
            ],
        }
        self.registry.record_evaluation_suite("suite-harness", "agent-a", "v1.0.0", suite, created_by="qa-user")
        harness = EvaluationHarness(self.registry)
        report = harness.evaluate(
            suite_id="suite-harness", agent_id="agent-a", version="v1.0.0", policy_version="v1",
            execute=lambda case: {"status":"ok"}, created_by="qa-user", now=200.0,
        )
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["floors_met"])
        self.assertTrue(report["coverage_complete"])

    def test_performance_score_cannot_be_self_reported_by_suite(self):
        suite = {
            "required_test_types": list(REQUIRED_TEST_TYPES),
            "performance_score": 1.0,
            "thresholds": {"minimum_performance_score": 0.95, "maximum_latency_ms": 1.0},
            "tests": [
                {"test_id": kind, "test_type":kind, "repeat_count":3 if kind=="determinism" else 1,
                 "expected_output":{"status":"slow"}}
                for kind in REQUIRED_TEST_TYPES
            ],
        }
        self.registry.record_evaluation_suite("suite-slow", "agent-a", "v1.0.0", suite, created_by="qa-user")
        def slow_execute(case):
            time.sleep(0.01)
            return {"status":"slow"}
        report = EvaluationHarness(self.registry).evaluate(
            suite_id="suite-slow", agent_id="agent-a", version="v1.0.0", policy_version="v1",
            execute=slow_execute, created_by="qa-user",
        )
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["floors_met"])
        self.assertLess(report["component_scores"]["performance_score"], 0.95)

    def test_missing_component_tests_fail_coverage(self):
        suite = {"tests":[{"test_id":"R","test_type":"regression"}], "thresholds":{}}
        self.registry.record_evaluation_suite("suite-incomplete", "agent-a", "v1.0.0", suite, created_by="qa-user")
        report = EvaluationHarness(self.registry).evaluate(
            suite_id="suite-incomplete", agent_id="agent-a", version="v1.0.0", policy_version="v1",
            execute=lambda case: {"ok":True}, created_by="qa-user", now=300.0,
        )
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["coverage_complete"])


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.v1, self.e1 = register_version(self.registry, "v1.0.0")
        self.gate = PromotionGate(self.registry)

    def tearDown(self):
        self.registry.close()

    def _approve_stage(self, version, eval_run, environment):
        row = self.registry.get_version("agent-a", version)
        policy = self.registry.get_version_policy("agent-a", version, environment)["policy"]
        pointer = self.registry.environment_pointer("agent-a", environment)
        previous_policy = None
        if pointer:
            previous_row = self.registry.get_version_policy("agent-a", pointer["version"], environment)
            previous_policy = previous_row["policy"] if previous_row else None
        from deter_agent.canonical import sha256_json
        diff_hash = sha256_json(policy_diff(previous_policy, policy))
        return self.registry.record_approval(
            target_type="promotion", target_id=f"agent-a:{version}", agent_id="agent-a",
            version=version, target_environment=environment, requested_by="release-requester",
            approver="independent-approver", decision="approved", spec_hash=row["spec_hash"],
            eval_run_id=eval_run, expires_at=time.time()+600, policy_diff_hash=diff_hash,
            scope=["permission_change"],
        )

    def test_stage_order_and_exact_promotion_binding(self):
        sandbox = self.gate.promote("agent-a", "v1.0.0", "sandbox", requested_by="operator")
        self.assertEqual(sandbox["status"], "promoted")
        self._approve_stage("v1.0.0", "eval-v1.0.0", "staging")
        staging = self.gate.promote("agent-a", "v1.0.0", "staging", requested_by="operator")
        self.assertEqual(staging["binding"]["eval_run_id"], "eval-v1.0.0")
        self.assertIsNotNone(staging["binding"]["approval_event_id"])
        self._approve_stage("v1.0.0", "eval-v1.0.0", "production")
        production = self.gate.promote("agent-a", "v1.0.0", "production", requested_by="operator")
        self.assertEqual(production["binding"]["spec_hash"], self.v1["spec_hash"])
        pointer = self.registry.environment_pointer("agent-a", "production")
        self.assertEqual(pointer["version"], "v1.0.0")

    def test_expired_exact_stage_approval_is_denied(self):
        self.gate.promote("agent-a", "v1.0.0", "sandbox", requested_by="operator")
        policy = self.registry.get_version_policy("agent-a", "v1.0.0", "staging")["policy"]
        diff_hash = sha256_json(policy_diff(None, policy))
        self.registry.record_approval(
            target_type="promotion", target_id="agent-a:v1.0.0", agent_id="agent-a",
            version="v1.0.0", target_environment="staging", requested_by="release-requester",
            approver="independent-approver", decision="approved", spec_hash=self.v1["spec_hash"],
            eval_run_id="eval-v1.0.0", expires_at=self.gate.clock() - 1,
            policy_diff_hash=diff_hash, scope=["permission_change"],
        )
        with self.assertRaises(PromotionDenied) as context:
            self.gate.promote("agent-a", "v1.0.0", "staging", requested_by="operator")
        self.assertEqual(context.exception.reason_code, "APPROVAL_REQUIRED")
        self.assertIsNone(self.registry.environment_pointer("agent-a", "staging"))

    def test_concurrent_environment_pointer_cas_allows_only_one_writer(self):
        second, _ = register_version(self.registry, "v2.0.0", created_by="builder-two")
        barrier = threading.Barrier(3)
        outcomes = []
        outcome_lock = threading.Lock()

        def commit(version_row, run_id, promotion_id):
            binding = {
                "agent_id": "agent-a", "version": version_row["version"],
                "target_environment": "sandbox", "spec_hash": version_row["spec_hash"],
                "eval_run_id": run_id, "approval_event_id": None,
                "policy_diff_hash": "d" * 64,
            }
            barrier.wait()
            try:
                self.registry.commit_promotion(
                    binding=binding, binding_hash=sha256_json(binding), promotion_id=promotion_id,
                    deployed_by="operator", expected_previous_version_id=None,
                )
                result = "committed"
            except RegistryConflict:
                result = "conflict"
            with outcome_lock:
                outcomes.append(result)

        threads = [
            threading.Thread(target=commit, args=(self.v1, "eval-v1.0.0", "concurrent-promo-one")),
            threading.Thread(target=commit, args=(second, "eval-v2.0.0", "concurrent-promo-two")),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads), "promotion CAS worker hung")
        self.assertCountEqual(outcomes, ["committed", "conflict"])
        pointer = self.registry.environment_pointer("agent-a", "sandbox")
        self.assertIn(pointer["version"], {"v1.0.0", "v2.0.0"})
        self.assertEqual(
            self.registry._connection.execute(
                "SELECT COUNT(*) FROM promotion_records WHERE target_environment='sandbox'"
            ).fetchone()[0],
            1,
        )

    def test_stage_skip_denied(self):
        with self.assertRaises(PromotionDenied) as context:
            self.gate.promote("agent-a", "v1.0.0", "production", requested_by="operator")
        self.assertEqual(context.exception.reason_code, "STAGE_SKIPPED")

    def test_bad_approval_spec_hash_does_not_promote(self):
        self.gate.promote("agent-a", "v1.0.0", "sandbox", requested_by="operator")
        self.registry.record_approval(
            target_type="promotion", target_id="agent-a:v1.0.0", agent_id="agent-a",
            version="v1.0.0", target_environment="staging", requested_by="release-requester",
            approver="independent-approver", decision="approved", spec_hash="0"*64,
            eval_run_id="eval-v1.0.0", expires_at=time.time()+600,
            policy_diff_hash=__import__("deter_agent.canonical", fromlist=["sha256_json"]).sha256_json(
                policy_diff(None, self.registry.get_version_policy("agent-a","v1.0.0","staging")["policy"])
            ), scope=["permission_change"],
        )
        with self.assertRaises(PromotionDenied):
            self.gate.promote("agent-a", "v1.0.0", "staging", requested_by="operator")

    def test_second_production_release_requires_previously_approved_rollback_target(self):
        self.gate.promote("agent-a", "v1.0.0", "sandbox", requested_by="operator")
        self._approve_stage("v1.0.0","eval-v1.0.0","staging")
        self.gate.promote("agent-a","v1.0.0","staging",requested_by="operator")
        self._approve_stage("v1.0.0","eval-v1.0.0","production")
        self.gate.promote("agent-a","v1.0.0","production",requested_by="operator")

        v2, e2=register_version(self.registry,"v2.0.0",rollback="v1.0.0",created_by="builder-2")
        self.gate.promote("agent-a","v2.0.0","sandbox",requested_by="operator")
        self._approve_stage("v2.0.0","eval-v2.0.0","staging")
        self.gate.promote("agent-a","v2.0.0","staging",requested_by="operator")
        self._approve_stage("v2.0.0","eval-v2.0.0","production")
        prod=self.gate.promote("agent-a","v2.0.0","production",requested_by="operator")
        self.assertEqual(prod["status"],"promoted")

    def test_rollback_requires_separate_exact_approval(self):
        self.gate.promote("agent-a", "v1.0.0", "sandbox", requested_by="operator")
        self._approve_stage("v1.0.0","eval-v1.0.0","staging")
        self.gate.promote("agent-a","v1.0.0","staging",requested_by="operator")
        self._approve_stage("v1.0.0","eval-v1.0.0","production")
        self.gate.promote("agent-a","v1.0.0","production",requested_by="operator")

        register_version(self.registry,"v2.0.0",rollback="v1.0.0",created_by="builder-2")
        self.gate.promote("agent-a","v2.0.0","sandbox",requested_by="operator")
        self._approve_stage("v2.0.0","eval-v2.0.0","staging")
        self.gate.promote("agent-a","v2.0.0","staging",requested_by="operator")
        self._approve_stage("v2.0.0","eval-v2.0.0","production")
        self.gate.promote("agent-a","v2.0.0","production",requested_by="operator")

        from deter_agent.canonical import sha256_json
        current_policy=self.registry.get_version_policy("agent-a","v2.0.0","production")["policy"]
        target_policy=self.registry.get_version_policy("agent-a","v1.0.0","production")["policy"]
        diff_hash=sha256_json(policy_diff(current_policy,target_policy))
        approval=self.registry.record_approval(
            target_type="rollback",target_id="v1.0.0",agent_id="agent-a",version="v1.0.0",
            target_environment="production",requested_by="operator",approver="independent-approver",
            decision="approved",spec_hash=self.v1["spec_hash"],eval_run_id="eval-v1.0.0",
            expires_at=time.time()+600,policy_diff_hash=diff_hash,scope=["permission_change"],
        )
        result=self.gate.rollback_production("agent-a","v1.0.0",approval_id=approval["approval_id"],requested_by="operator")
        self.assertEqual(result["status"],"rolled_back")
        self.assertEqual(self.registry.environment_pointer("agent-a","production")["version"],"v1.0.0")
