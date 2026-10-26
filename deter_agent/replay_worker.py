"""Subprocess entry point used to test rule engine determinism under hash-seed variation."""
from __future__ import annotations
import json
import sys
from .canonical import canonical_json
from .rules import Rule, RuleSet, RuleEngine


def main() -> int:
    request = json.load(sys.stdin)
    rules = []
    for raw in request["rules"]:
        rules.append(Rule(
            rule_id=raw["rule_id"], priority=raw["priority"], when=raw.get("when", {}),
            action=raw["action"], risk_rank=raw.get("risk_rank", "low"),
            operation=raw.get("operation"), fallback=raw.get("fallback", False),
            metadata=raw.get("metadata", {}),
        ))
    result = RuleEngine(RuleSet(tuple(rules))).decide(request["input"])
    sys.stdout.write(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
