import copy
import random
import unittest

import time

from deter_agent.canonical import normalize_json, sha256_json
from deter_agent.evaluation import EvaluationHarness
from deter_agent.evaluation_contract import HARD_COMPONENTS, REQUIRED_TEST_TYPES, TEST_COMPONENT
from deter_agent.mutations import MutationHarness, change_action, change_condition, change_field, shift_priority
from deter_agent.promotion import PromotionDenied, PromotionGate, policy_diff
from deter_agent.registry import Registry
from deter_agent.rules import Rule, RuleEngine, RuleSet
from deter_agent.runtime import RuntimeEngine
from tests.helpers import make_gateway, make_policy, make_spec, make_tool_catalog


def rule_from(raw):
    return Rule(raw["rule_id"],raw["priority"],raw.get("when",{}),raw["action"],raw.get("risk_rank","low"),
                fallback=raw.get("fallback",False),metadata=raw.get("metadata",{}))


class StressTests(unittest.TestCase):
    def test_normalization_idempotence_generated_values(self):
        randomizer=random.Random(20261026)
        alphabet=["a","e\u0301","\u212b","\U0001f680","0","Z"]
        for _ in range(200):
            value={"strings":["".join(randomizer.choice(alphabet) for _ in range(randomizer.randrange(1,8)) for _ in range(1))],
                   "nested":{"n":randomizer.randrange(1000),"flag":bool(randomizer.randrange(2))}}
            once=normalize_json(value)
            twice=normalize_json(once)
            self.assertEqual(once,twice)

    def test_mutation_campaign_uses_fresh_registries_and_kills_behavior_changes(self):
        spec=make_spec()
        case={"intent":"do"}
        created=[]
        def factory():
            registry=Registry()
            created.append(registry)
            return registry
        def prepare(registry, mutant_spec):
            registry.register_agent(mutant_spec["agent_id"])
            registry.register_version(mutant_spec["agent_id"],mutant_spec["version"],mutant_spec,created_by="builder",change_summary="mutation test")
            return RuleEngine(RuleSet(tuple(rule_from(x) for x in mutant_spec["decision_rules"])))
        def evaluate(engine, case):
            return engine.decide(case)
        campaign=MutationHarness(factory,prepare=prepare,execute_case=evaluate).run(
            spec,[case],[change_action("ROUTE-DO","reject"),change_condition("ROUTE-DO","intent","unknown"),shift_priority("ROUTE-DO",1000)]
        )
        self.assertEqual(campaign.killed,3)
        self.assertEqual(campaign.surviving_candidates,0)
        self.assertEqual(len(created),4)  # baseline plus one isolated registry per mutant
        self.assertEqual(campaign.mutation_score,1.0)

    def test_equivalent_mutant_is_reported_as_candidate_not_proof(self):
        spec=make_spec()
        def harmless(s):
            s["decision_rules"][0]["metadata"]["comment"]="non-semantic comment"
            return s
        from deter_agent.mutations import RuleMutant
        def factory(): return Registry()
        def prepare(registry, mutant_spec):
            registry.register_agent(mutant_spec["agent_id"])
            registry.register_version(mutant_spec["agent_id"],mutant_spec["version"],mutant_spec,created_by="builder",change_summary="mutation")
            return RuleEngine(RuleSet(tuple(rule_from(x) for x in mutant_spec["decision_rules"])))
        result=MutationHarness(factory,prepare=prepare,execute_case=lambda engine,case:engine.decide(case)).run(
            spec,[{"intent":"do"}],[RuleMutant("metadata-noop",harmless,"metadata_change")]
        )
        self.assertEqual(result.surviving_candidates,1)
        self.assertEqual(result.results[0].outcome,"equivalence_candidate")

    def test_policy_mutation_campaign_kills_permission_allowlist_expansion(self):
        spec = make_spec()
        spec["test_policy"] = make_policy(
            "staging", tools=["create_ticket"], approvals=["create_ticket"], policy_id="mutation-policy"
        )
        case = {"tool_name":"send_message","action":"send_message","resource":"outbound_messages"}

        def prepare(registry, mutant_spec):
            registry.register_agent(mutant_spec["agent_id"])
            registry.register_version(
                mutant_spec["agent_id"],mutant_spec["version"],mutant_spec,
                created_by="builder",change_summary="policy mutation",
            )
            policy = mutant_spec["test_policy"]
            registry.register_policy(policy["policy_id"],policy["version"],policy["environment"],policy)
            registry.bind_policy(mutant_spec["agent_id"],mutant_spec["version"],"staging",policy["policy_id"],policy["version"])
            return make_gateway(registry,catalog=make_tool_catalog())

        def execute(gateway, request):
            decision = gateway.authorize(
                agent_id="agent-a",version="v1.0.0",environment="staging",
                tool_name=request["tool_name"],action=request["action"],target_resource=request["resource"],
            )
            return {"decision":decision.decision,"reason_code":decision.reason_code}

        campaign=MutationHarness(Registry,prepare=prepare,execute_case=execute).run(
            spec,[case],[change_field(
                ("test_policy","allowed_tools"),["create_ticket","send_message"],
                operator="policy_allowlist_expansion",
            )]
        )
        self.assertEqual(campaign.killed,1)
        self.assertEqual(campaign.results[0].outcome,"killed")

    def test_runtime_mutation_campaign_kills_removed_approval_requirement(self):
        spec=make_spec()
        spec["test_policy"]=make_policy(
            "staging",tools=["create_ticket","send_message"],approvals=["send_message"],policy_id="runtime-policy"
        )
        case={"request_id":"mutation-runtime","intent":"protected"}

        def prepare(registry,mutant_spec):
            registry.register_agent(mutant_spec["agent_id"])
            registry.register_version(
                mutant_spec["agent_id"],mutant_spec["version"],mutant_spec,
                created_by="builder",change_summary="runtime mutation",
            )
            policy=mutant_spec["test_policy"]
            registry.register_policy(policy["policy_id"],policy["version"],policy["environment"],policy)
            registry.bind_policy(mutant_spec["agent_id"],mutant_spec["version"],"staging",policy["policy_id"],policy["version"])
            gateway=make_gateway(registry,catalog=make_tool_catalog())
            def send_message(action_input,idempotency_key=None):
                return {"ok":True,"message_id":"MUTATION-MSG"}
            return RuntimeEngine(registry,gateway,{"send_message":send_message})

        def execute(runtime,request):
            result=runtime.run({
                "request_id":request["request_id"],"agent_id":"agent-a","agent_version":"v1.0.0",
                "environment":"staging","requested_by":"operator",
                "input":{"received_at":"2026-10-26T00:00:00Z","intent":request["intent"]},
            })
            return {"status":result["status"],"reason_code":result.get("reason_code")}

        campaign=MutationHarness(Registry,prepare=prepare,execute_case=execute).run(
            spec,[case],[change_field(
                ("test_policy","approval_required_for"),["create_ticket"],
                operator="approval_requirement_removal",
            )]
        )
        self.assertEqual(campaign.killed,1)
        self.assertEqual(campaign.results[0].outcome,"killed")

    def test_mutation_campaign_kills_idempotency_metadata_loosening(self):
        spec=make_spec()
        spec["test_policy"]=make_policy(
            "staging",tools=["create_ticket","send_message"],approvals=["send_message"],policy_id="retry-policy"
        )
        spec["test_catalog"]={"idempotent":True,"supports_idempotency_key":True}
        case={"request_id":"mutation-retry","intent":"do"}

        def prepare(registry,mutant_spec):
            registry.register_agent(mutant_spec["agent_id"])
            registry.register_version(
                mutant_spec["agent_id"],mutant_spec["version"],mutant_spec,
                created_by="builder",change_summary="retry metadata mutation",
            )
            policy=mutant_spec["test_policy"]
            registry.register_policy(policy["policy_id"],policy["version"],policy["environment"],policy)
            registry.bind_policy(mutant_spec["agent_id"],mutant_spec["version"],"staging",policy["policy_id"],policy["version"])
            catalog_options=mutant_spec["test_catalog"]
            gateway=make_gateway(
                registry,catalog=make_tool_catalog(
                    idempotent=catalog_options["idempotent"],
                    supports_key=catalog_options["supports_idempotency_key"],
                )
            )
            attempts={"count":0}
            def create_ticket(action_input,idempotency_key=None):
                attempts["count"]+=1
                if attempts["count"]==1:
                    raise TimeoutError("temporary failure before side effect")
                return {"ok":True,"ticket_id":"TICKET-1"}
            runtime=RuntimeEngine(registry,gateway,{"create_ticket":create_ticket})
            return runtime

        def execute(runtime,request):
            result=runtime.run({
                "request_id":request["request_id"],"agent_id":"agent-a","agent_version":"v1.0.0",
                "environment":"staging","requested_by":"operator",
                "input":{"received_at":"2026-10-26T00:00:00Z","intent":request["intent"]},
            })
            return {"status":result["status"],"reason_code":result.get("reason_code")}

        campaign=MutationHarness(Registry,prepare=prepare,execute_case=execute).run(
            spec,[case],[change_field(
                ("test_catalog","supports_idempotency_key"),False,
                operator="idempotency_key_support_removed",
            )]
        )
        self.assertEqual(campaign.killed,1)
        self.assertEqual(campaign.results[0].outcome,"killed")

    def test_mutation_campaign_kills_approval_environment_binding_fault(self):
        spec=make_spec()
        spec["approval_descriptor"]={"target_environment":"staging"}

        def prepare(registry,mutant_spec):
            agent_id,version=mutant_spec["agent_id"],mutant_spec["version"]
            registry.register_agent(agent_id)
            version_row=registry.register_version(
                agent_id,version,mutant_spec,created_by="builder",change_summary="approval-binding mutation",
            )
            for environment in ("sandbox","staging","production"):
                policy=make_policy(
                    environment,sandbox_side_effects=(environment=="sandbox"),
                    policy_id=f"mutation-{environment}",
                )
                registry.register_policy(policy["policy_id"],policy["version"],environment,policy)
                registry.bind_policy(agent_id,version,environment,policy["policy_id"],policy["version"])
            tests=[
                {"test_id":f"T-{kind.upper()}","test_type":kind,"repeat_count":3 if kind=="determinism" else 1}
                for kind in REQUIRED_TEST_TYPES
            ]
            suite=registry.record_evaluation_suite(
                "suite-mutation-approval",agent_id,version,
                {"tests":tests,"required_test_types":list(REQUIRED_TEST_TYPES),
                 "thresholds":{"minimum_performance_score":0.95,"maximum_latency_ms":1000.0}},
                created_by="independent-qa",
            )
            registry.record_evaluation(
                run_id="eval-mutation-approval",agent_id=agent_id,version=version,
                spec_hash=version_row["spec_hash"],suite_id=suite["suite_id"],policy_version="v1",
                engine_version="mutation-test",status="passed",floors_met=True,coverage_complete=True,
                component_scores={**{name:1.0 for name in HARD_COMPONENTS},"performance_score":1.0},
                score=1.0,
                results=[
                    {"test_id":f"T-{kind.upper()}","test_type":kind,"component":TEST_COMPONENT.get(kind,kind),
                     "passed":True,"required":True,"elapsed_ms":1.0}
                    for kind in REQUIRED_TEST_TYPES
                ],
                created_by="independent-qa",started_at=1.0,completed_at=2.0,
            )
            gate=PromotionGate(registry)
            gate.promote(agent_id,version,"sandbox",requested_by="operator")
            staging_policy=registry.get_version_policy(agent_id,version,"staging")["policy"]
            diff_hash=sha256_json(policy_diff(None,staging_policy))
            descriptor=mutant_spec["approval_descriptor"]
            registry.record_approval(
                target_type="promotion",target_id=f"{agent_id}:{version}",agent_id=agent_id,version=version,
                target_environment=descriptor["target_environment"],requested_by="release-requester",
                approver="independent-approver",decision="approved",spec_hash=version_row["spec_hash"],
                eval_run_id="eval-mutation-approval",expires_at=time.time()+600,
                policy_diff_hash=diff_hash,scope=["permission_change"],
            )
            return gate

        def execute(gate,_case):
            try:
                result=gate.promote("agent-a","v1.0.0","staging",requested_by="operator")
                return {"status":result["status"]}
            except PromotionDenied as exc:
                return {"status":"denied","reason_code":exc.reason_code}

        campaign=MutationHarness(Registry,prepare=prepare,execute_case=execute).run(
            spec,[{"case":"approval-binding"}],[change_field(
                ("approval_descriptor","target_environment"),"production",
                operator="approval_environment_mismatch",
            )]
        )
        self.assertEqual(campaign.killed,1)
        self.assertEqual(campaign.results[0].outcome,"killed")

    def test_cross_process_replay_varied_hash_seed_and_key_order(self):
        spec = make_spec()
        replay_rules = [
            {
                "rule_id": rule["rule_id"], "priority": rule["priority"],
                "when": rule.get("when", {}), "action": rule["action"],
                "risk_rank": rule.get("risk_rank", "low"),
                "fallback": rule.get("fallback", False), "metadata": rule.get("metadata", {}),
            }
            for rule in spec["decision_rules"]
        ]
        result = EvaluationHarness.cross_process_rule_replay(replay_rules, {"intent": "do"}, processes=8)
        self.assertTrue(result["consistent"], result)
        self.assertEqual(result["processes"], 8)
        self.assertEqual(result["unique_outputs"], 1)

    def test_priority_permutations_are_invariant(self):
        spec=make_spec()
        rules=tuple(rule_from(raw) for raw in spec["decision_rules"])
        expected=RuleEngine(RuleSet(rules)).decide({"intent":"do"})
        randomizer=random.Random(42)
        for _ in range(100):
            shuffled=list(rules)
            randomizer.shuffle(shuffled)
            self.assertEqual(RuleEngine(RuleSet(tuple(shuffled))).decide({"intent":"do"}),expected)
