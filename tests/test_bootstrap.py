import hashlib
import hmac
import sqlite3
import unittest

from deter_agent.bootstrap import BOOTSTRAP_SCOPE, BootstrapError, seed_initial_evaluation_agent, signature_message
from deter_agent.canonical import sha256_json
from deter_agent.evaluation_contract import REQUIRED_TEST_TYPES
from deter_agent.registry import Registry
from tests.helpers import make_policy, make_spec

TEST_PUBLIC_KEY = b"test-operator-public-key-material-0000"[:32]
TEST_KEY_ID = "test-operator-key-2026"


def fake_verify(public_key, message, signature):
    # Test-only signature adapter, not production cryptography.
    return hmac.compare_digest(hashlib.sha512(public_key + message).digest(), signature)


def make_seed(*, build_step=1, scope=BOOTSTRAP_SCOPE, mutate_policy=False):
    agent_id, version = "initial-evaluation-agent", "v1.0.0"
    spec = make_spec(agent_id=agent_id, version=version)
    policies = []
    for environment in ("sandbox", "staging", "production"):
        policy = make_policy(environment, sandbox_side_effects=(environment == "sandbox"),
                             policy_id=f"bootstrap-policy-{environment}")
        if mutate_policy and environment == "production":
            policy["unknown_policy_flag"] = True
        policies.append({"policy_id":policy["policy_id"],"policy_version":policy["version"],
                         "environment":environment,"policy":policy})
    suite = {
        "tests":[{"test_id":f"T-{kind.upper()}","test_type":kind,
                  "repeat_count":3 if kind=="determinism" else 1} for kind in REQUIRED_TEST_TYPES],
        "required_test_types":list(REQUIRED_TEST_TYPES),
        "thresholds":{"minimum_performance_score":0.95,"maximum_latency_ms":1000.0},
    }
    payload = {
        "created_by":"bootstrap","scope":scope,"build_step":build_step,"expires_after_step":8,
        "agent_role":"evaluation_agent","agent_id":agent_id,"version":version,"spec":spec,
        "change_summary":"Seed the initial evaluation agent from the operator trust root",
        "policies":policies,
        "evaluation_suite":{"suite_id":"initial-evaluation-suite","suite":suite},
        "evaluation_suite_created_by":"bootstrap-evaluation-qa",
    }
    payload_hash=sha256_json(payload)
    envelope={"seed_id":"bootstrap-seed-initial-evaluation-001","key_id":TEST_KEY_ID,
              "payload_hash":payload_hash,"payload":payload}
    message=signature_message(seed_id=envelope["seed_id"],key_id=TEST_KEY_ID,payload_hash=payload_hash)
    envelope["signature"]=hashlib.sha512(TEST_PUBLIC_KEY+message).hexdigest()
    return envelope


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.registry=Registry()
        self.keys={TEST_KEY_ID:TEST_PUBLIC_KEY}

    def tearDown(self):
        self.registry.close()

    def seed(self,envelope,current_step=1):
        return seed_initial_evaluation_agent(
            self.registry,envelope,trusted_public_keys=self.keys,verify_signature=fake_verify,
            current_build_step=current_step,now=100.0,
        )

    def test_verified_seed_registers_agent_policies_suite_and_immutable_receipt(self):
        result=self.seed(make_seed())
        self.assertEqual(result["status"],"seeded")
        version=self.registry.get_version("initial-evaluation-agent","v1.0.0")
        self.assertEqual(version["created_by"],"bootstrap")
        for environment in ("sandbox","staging","production"):
            self.assertIsNotNone(self.registry.get_version_policy("initial-evaluation-agent","v1.0.0",environment))
        self.assertEqual(self.registry.get_evaluation_suite("initial-evaluation-suite")["created_by"],"bootstrap-evaluation-qa")
        receipt=self.registry._connection.execute(
            "SELECT seed_id,payload_hash,expires_after_step FROM bootstrap_receipts"
        ).fetchone()
        self.assertEqual(tuple(receipt),(result["seed_id"],result["payload_hash"],8))
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry._connection.execute(
                "UPDATE bootstrap_receipts SET created_at=created_at WHERE seed_id=?",(result["seed_id"],)
            )

    def test_invalid_signature_or_payload_hash_does_not_write(self):
        invalid=make_seed()
        invalid["signature"]="00"*64
        with self.assertRaises(BootstrapError):
            self.seed(invalid)
        self.assertEqual(self.registry._connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0],0)
        wrong_hash=make_seed()
        wrong_hash["payload"]["purpose"]="tampered after signing"
        with self.assertRaises(BootstrapError):
            self.seed(wrong_hash)
        self.assertEqual(self.registry._connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0],0)

    def test_scope_expiry_and_prior_registration_are_denied(self):
        with self.assertRaises(BootstrapError):
            self.seed(make_seed(scope="all_agents"))
        with self.assertRaises(BootstrapError):
            self.seed(make_seed(),current_step=9)
        self.registry.register_agent("initial-evaluation-agent")
        with self.assertRaises(BootstrapError):
            self.seed(make_seed())
        self.assertEqual(self.registry._connection.execute("SELECT COUNT(*) FROM versions").fetchone()[0],0)

    def test_seed_application_failure_rolls_back_all_records(self):
        with self.assertRaises(BootstrapError):
            self.seed(make_seed(mutate_policy=True))
        for table in ("agents","versions","policies","version_policies","evaluation_suites","bootstrap_receipts"):
            self.assertEqual(self.registry._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0,table)

    def test_seed_replay_is_rejected_after_first_consumption(self):
        seed=make_seed()
        self.seed(seed)
        with self.assertRaises(BootstrapError):
            self.seed(seed)
        self.assertEqual(self.registry._connection.execute("SELECT COUNT(*) FROM bootstrap_receipts").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
