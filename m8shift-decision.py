#!/usr/bin/env python3
"""Optional, offline, read-only task routing for M8Shift.

This module makes recommendations. It never acquires the pen, launches a provider,
modifies project files, or changes the relay protocol.
"""
import argparse
import json
import sys

VERSION = "4.5.0"
SCHEMA = "m8shift.routing.v1"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
RISK_LEVELS = ("low", "moderate", "high", "critical")
STRATEGIES = ("direct", "delegate", "parallel")
MODEL_TIERS = ("economy", "balanced", "advanced")

def decide(task, *, risk="low", complexity="low", failures=0,
           independent_parts=False, has_tests=False, budget="balanced"):
    """Return a deterministic, provider-neutral routing recommendation."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be nonempty text")
    if risk not in RISK_LEVELS or complexity not in RISK_LEVELS:
        raise ValueError("invalid risk or complexity")
    if budget not in ("economy", "balanced", "quality"):
        raise ValueError("invalid budget policy")
    if type(failures) is not int or failures < 0:
        raise ValueError("failures must be a nonnegative integer")
    if type(independent_parts) is not bool or type(has_tests) is not bool:
        raise ValueError("boolean flags must be booleans")
    score = max(RISK_LEVELS.index(risk), RISK_LEVELS.index(complexity))
    # High-stakes operations are never downgraded for cost.
    if risk in ("high", "critical"):
        score = max(score, 2)
    if failures >= 2:
        score = max(score, 2)
    if failures >= 4:
        score = max(score, 3)
    if budget == "quality":
        score = max(score, 1)
    effort = ("low", "medium", "high", "xhigh")[score]
    if failures >= 4 or risk == "critical":
        effort = "max"
    tier = "advanced" if score >= 2 else ("balanced" if score == 1 else "economy")
    strategy = ("parallel" if independent_parts and score <= 1
                else "delegate" if score <= 1 and has_tests else "direct")
    advisor = risk in ("high", "critical") or complexity in ("high", "critical") or failures >= 2
    approval = risk == "critical"
    return {
        "schema": SCHEMA,
        "status": "proposed",
        "decision": {
            "model_tier": tier, "effort": effort, "strategy": strategy,
            "advisor_required": advisor, "human_approval_required": approval
        },
        "inputs": {
            "risk": risk, "complexity": complexity, "failures": failures,
            "independent_parts": independent_parts, "has_tests": has_tests,
            "budget": budget
        },
        "reason": "Deterministic policy; no external model was called"
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("task")
    p.add_argument("--risk", choices=RISK_LEVELS, default="low")
    p.add_argument("--complexity", choices=RISK_LEVELS, default="low")
    p.add_argument("--failures", type=int, default=0)
    p.add_argument("--independent-parts", action="store_true")
    p.add_argument("--has-tests", action="store_true")
    p.add_argument("--budget", choices=("economy", "balanced", "quality"), default="balanced")
    args = p.parse_args(argv)
    try:
        result = decide(args.task, risk=args.risk, complexity=args.complexity,
                        failures=args.failures, independent_parts=args.independent_parts,
                        has_tests=args.has_tests, budget=args.budget)
    except ValueError as exc:
        return p.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
