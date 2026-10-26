import copy
import random
import unittest

from deter_agent.canonical import normalize_json
from deter_agent.mutations import MutationHarness, change_action, change_condition, shift_priority
from deter_agent.evaluation import EvaluationHarness
from deter_agent.registry import Registry
from deter_agent.rules import Rule, RuleEngine, RuleSet
from tests.helpers import make_spec


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
