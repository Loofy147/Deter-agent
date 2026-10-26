import time
import unittest

from deter_agent.evaluation import EvaluationHarness
from deter_agent.promotion import PromotionDenied, PromotionGate, policy_diff
from deter_agent.registry import Registry
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
        {"tests":[{"test_id":"T-REG","test_type":"regression"}], "thresholds":{}},
        created_by="independent-qa",
    )
    report = registry.record_evaluation(
        run_id=f"eval-{version}", agent_id="agent-a", version=version, spec_hash=version_row["spec_hash"],
        suite_id=suite["suite_id"], policy_version="v1", engine_version="test-engine",
        status="passed", floors_met=True, coverage_complete=True,
        component_scores={"regression_score":1.0}, score=0.99,
        results=[{"test_id":"T-REG","passed":True}], created_by="independent-qa",
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


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.spec, self.eval_row = register_version(self.registry, "v1.0.0")

    def tearDown(self):
        self.registry.close()

    def test_evaluation_harness_requires_all_component_classes(self):
        suite = {
            "required_test_types": ["determinism","regression","policy","schema","state_transition","tie_break","failure_path"],
            "performance_score": 1.0,
            "thresholds": {"minimum_performance_score": 0.95},
            "tests": [
                {"test_id": kind, "test_type":kind, "repeat_count":3 if kind=="determinism" else 1,
                 "expected_output":{"status":"ok"}}
                for kind in ["determinism","regression","policy","schema","state_transition","tie_break","failure_path"]
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
