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
    if report["verdict"] == "ok" and any(isinstance(row, dict) and row.get("classification") in ("near_limit", "limit_hit") for row in report["agents"]):
        raise ValueError("inconsistent_guard_verdict")
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
        window = row.get("decision_window")
        if window is not None and not isinstance(window, dict):
            raise ValueError("invalid_decision_window")
        window = window or {}
        kind = window.get("kind", "unknown")
        resets_at = window.get("resets_at")
        if not isinstance(kind, str) or len(kind) > 64 or not re.fullmatch(r"[A-Za-z0-9_.-]+", kind):
            raise ValueError("invalid_window_kind")
        if resets_at is not None and (not isinstance(resets_at, str) or len(resets_at) > 64):
            raise ValueError("invalid_window_reset")
        binding = json.dumps([agent, kind, resets_at], separators=(",", ":"), ensure_ascii=True)
        key = hashlib.sha256(binding.encode("ascii")).hexdigest()
        result.append({
            "schema": "m8shift.usage.checkpoint-advice.v1",
            "authority": "advisory",
            "action": "checkpoint_or_cooldown",
            "source_agent": agent,
            "target_agent": None,
            "task_type": None,
            "decision_ratio": ratio,
            "recommendation_key": key,
            "window_kind": kind,
            "resets_at": resets_at,
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
