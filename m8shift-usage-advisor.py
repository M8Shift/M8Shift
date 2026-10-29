#!/usr/bin/env python3
"""Read-only checkpoint advice from an existing M8Shift usage guard JSON result.

This optional companion does not claim the pen, choose a replacement agent,
apply a hold, launch a model, or write any persistent state.
"""
import argparse
import hashlib
import json
import re
import sys

MAX_INPUT_BYTES = 1024 * 1024
AGENT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


def advice(report):
    if not isinstance(report, dict) or not isinstance(report.get("agents"), list):
        raise ValueError("invalid_usage_guard_report")
    if len(report["agents"]) > 128:
        raise ValueError("too_many_agents")
    if report.get("verdict") not in ("ok", "near_limit", "limit_hit", "unknown"):
        raise ValueError("invalid_verdict")
    result = []
    seen = set()
    for row in report["agents"]:
        if not isinstance(row, dict):
            raise ValueError("invalid_agent_row")
        agent = row.get("agent")
        state = row.get("classification")
        if not isinstance(agent, str) or not AGENT.fullmatch(agent) or agent in seen:
            raise ValueError("invalid_or_duplicate_agent")
        seen.add(agent)
        if state not in ("ok", "near_limit", "limit_hit", "unknown"):
            raise ValueError("invalid_classification")
        if state != "near_limit":
            continue
        if row.get("stale") is not False:
            continue
        ratio = row.get("decision_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
            continue
        key = hashlib.sha256(f"{agent}:near_limit".encode("ascii")).hexdigest()
        result.append({
            "schema": "m8shift.usage.checkpoint-advice.v1",
            "authority": "advisory",
            "action": "checkpoint_or_cooldown",
            "source_agent": agent,
            "target_agent": None,
            "task_type": None,
            "decision_ratio": ratio,
            "recommendation_key": key,
            "message": "Usage near limit: checkpoint the current work unit or plan a cooldown. No alternate agent was selected."
        })
    return {"schema": "m8shift.usage.checkpoint-report.v1",
            "authority": "advisory", "launch": False, "write_authorized": False,
            "advisories": result}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="-", help="Usage guard JSON file, or - for stdin")
    args = p.parse_args(argv)
    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            with open(args.input, "rb") as f:
                raw = f.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("input_too_large")
        report = json.loads(raw)
        output = advice(report)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "refused", "reason": type(exc).__name__}),
              file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
