#!/usr/bin/env python3
"""Generate or verify framework enum projections from the canonical JSON contract."""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "deterministic-control-contract.json"
REGISTRY = ROOT / "agent-registry-schema.md"
MANIFEST = ROOT / "agentic-system-manifest.yaml"

DESCRIPTIONS = {
    "rule_based": "Simple explicit business logic.",
    "decision_table": "Many condition and action combinations.",
    "finite_state_machine": "Strict lifecycle control.",
    "workflow_engine": "Multi-step operational orchestration.",
    "constraint_based": "Hard policy and safety boundaries.",
    "deterministic_scoring": "Ranking and prioritization.",
    "hybrid_rule_workflow": "Production operational automation.",
}

def generated_files() -> dict[Path, str]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    frameworks = contract["enums"]["framework"]
    if set(frameworks) != set(DESCRIPTIONS) or len(frameworks) != len(set(frameworks)):
        raise ValueError("Canonical framework enum and descriptions disagree.")
    registry = REGISTRY.read_text(encoding="utf-8")
    registry_new, count = re.subn(
        r"(?m)^framework: [a-z_]+(?:\|[a-z_]+)*$",
        "framework: " + "|".join(frameworks),
        registry, count=1,
    )
    if count != 1:
        raise ValueError("Could not locate exactly one registry framework enum.")
    manifest = MANIFEST.read_text(encoding="utf-8")
    start = manifest.find("frameworks:\n")
    end = manifest.find("\nimprovement_loop:\n", start)
    if start < 0 or end < 0:
        raise ValueError("Could not locate manifest frameworks section.")
    block = "frameworks:\n" + "".join(
        f"  {name}:\n    best_for: {DESCRIPTIONS[name]}\n"
        for name in frameworks
    )
    manifest_new = manifest[:start] + block.rstrip("\n") + "\n" + manifest[end:]
    return {REGISTRY: registry_new, MANIFEST: manifest_new}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail on drift instead of writing")
    args = parser.parse_args()
    try:
        outputs = generated_files()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    drift = []
    for path, wanted in outputs.items():
        if path.read_text(encoding="utf-8") != wanted:
            drift.append(path.relative_to(ROOT).as_posix())
            if not args.check:
                path.write_text(wanted, encoding="utf-8")
    if drift and args.check:
        print("FAIL: generated framework enum drift: " + ", ".join(drift), file=sys.stderr)
        return 1
    print(("UPDATED: " + ", ".join(drift)) if drift else "PASS: canonical framework enums match generated projections.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
