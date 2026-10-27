#!/usr/bin/env python3
"""Read-only bridge between existing M8Shift routing and decision policy.

Runs the existing runtime 'route recommend' command and combines its advisory
model selection with a deterministic risk/effort recommendation. Never launches
a provider, touches the pen, or writes an audit log.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent

def load_decision(path=None):
    path = path or HERE / "m8shift-decision.py"
    spec = importlib.util.spec_from_file_location("m8shift_decision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def merge_recommendations(policy, runtime):
    """Never convert a runtime fail-safe into an executable model choice."""
    if not isinstance(runtime, dict):
        raise ValueError("runtime result must be an object")
    if runtime.get("authority") != "advisory" or runtime.get("launch") is not False:
        raise ValueError("runtime recommendation has unexpected authority")
    ok = runtime.get("ok") is True
    picked = runtime.get("picked") if ok else None
    return {
        "schema": "m8shift.routing.bridge.v1",
        "status": "proposed",
        "authority": "advisory",
        "launch": False,
        "runtime_ok": ok,
        "runtime_model": picked if isinstance(picked, str) and picked.strip() else None,
        "runtime_reason": runtime.get("reason", ""),
        "runtime_effort": runtime.get("effort", "") if ok else "",
        "policy": policy,
        "requires_manual_resolution": not ok or not picked,
        "note": "No model launch or approval is authorized by this result"
    }

def recommend(task, task_type, *, runtime_script=None, timeout=15, **policy_options):
    policy = load_decision().decide(task, **policy_options)
    runtime_script = Path(runtime_script or HERE / "m8shift-runtime.py").resolve()
    if not runtime_script.is_file():
        raise ValueError("runtime script missing")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 60:
        raise ValueError("timeout must be between 0 and 60 seconds")
    command = [sys.executable, str(runtime_script), "route", "recommend",
               "--task-type", task_type, "--json"]
    proc = subprocess.run(command, cwd=str(runtime_script.parent), capture_output=True,
                          text=True, timeout=timeout, check=False)
    if proc.returncode not in (0, 1):
        raise RuntimeError("runtime route command failed")
    try:
        runtime = json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("runtime returned invalid JSON") from exc
    return merge_recommendations(policy, runtime)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task")
    p.add_argument("--task-type", required=True)
    p.add_argument("--risk", choices=("low", "moderate", "high", "critical"), default="low")
    p.add_argument("--complexity", choices=("low", "moderate", "high", "critical"), default="low")
    p.add_argument("--failures", type=int, default=0)
    p.add_argument("--budget", choices=("economy", "balanced", "quality"), default="balanced")
    p.add_argument("--has-tests", action="store_true")
    p.add_argument("--independent-parts", action="store_true")
    a = p.parse_args(argv)
    try:
        result = recommend(a.task, a.task_type, risk=a.risk, complexity=a.complexity,
                           failures=a.failures, budget=a.budget, has_tests=a.has_tests,
                           independent_parts=a.independent_parts)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("routing bridge refused: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["runtime_ok"] else 1

if __name__ == "__main__":
    sys.exit(main())
