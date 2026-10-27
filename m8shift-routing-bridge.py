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

EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
TIER_ORDER = ("economy", "balanced", "flagship")
POLICY_TIERS = {"economy": "economy", "balanced": "balanced", "advanced": "flagship"}

def merge_recommendations(policy, runtime):
    """Conservatively arbitrate two advisory policies; never authorize execution."""
    if not isinstance(runtime, dict) or not isinstance(policy, dict):
        raise ValueError("recommendations must be objects")
    if runtime.get("authority") != "advisory" or runtime.get("launch") is not False:
        raise ValueError("runtime recommendation has unexpected authority")
    decision = policy.get("decision")
    if policy.get("schema") != "m8shift.routing.v1" or not isinstance(decision, dict):
        raise ValueError("invalid decision policy schema")
    required_effort = decision.get("effort")
    if required_effort not in EFFORT_ORDER:
        raise ValueError("invalid policy effort")
    ok = runtime.get("ok") is True
    picked = runtime.get("picked") if ok else None
    picked = picked.strip() if isinstance(picked, str) and picked.strip() else None
    runtime_effort = runtime.get("effort") if ok else None
    if runtime_effort in (None, ""):
        effective_effort = required_effort
        effort_source = "policy_only"
    elif runtime_effort in EFFORT_ORDER:
        effective_effort = max((runtime_effort, required_effort), key=EFFORT_ORDER.index)
        effort_source = "maximum_of_policies"
    else:
        effective_effort = None
        effort_source = "invalid_runtime_effort"
    required_tier = POLICY_TIERS.get(decision.get("model_tier"))
    feasible = runtime.get("feasible") if ok else None
    eligible = []
    if required_tier is not None and isinstance(feasible, list):
        for row in feasible:
            if not isinstance(row, dict):
                continue
            model_id, tier = row.get("id"), row.get("tier")
            if (isinstance(model_id, str) and model_id.strip()
                    and tier in TIER_ORDER
                    and TIER_ORDER.index(tier) >= TIER_ORDER.index(required_tier)):
                eligible.append(model_id)
    compatible_model = eligible[0] if eligible else None
    reasons = []
    if not ok: reasons.append("runtime_manifest_or_routing_error")
    if not picked: reasons.append("no_runtime_model")
    if effective_effort is None: reasons.append("invalid_runtime_effort")
    if decision.get("human_approval_required"): reasons.append("human_approval_required")
    if decision.get("advisor_required"): reasons.append("advisor_required")
    if required_tier is None: reasons.append("invalid_policy_tier")
    if not compatible_model: reasons.append("no_compatible_model")
    if not isinstance(feasible, list): reasons.append("missing_feasible_evidence")
    return {
        "schema": "m8shift.routing.bridge.v1",
        "status": "proposed", "authority": "advisory", "launch": False,
        "runtime_ok": ok, "runtime_model": picked,
        "compatible_model": compatible_model, "required_tier": required_tier,
        "runtime_reason": runtime.get("reason", ""),
        "runtime_effort": runtime_effort or "",
        "effective_effort": effective_effort,
        "effort_source": effort_source,
        "policy": policy,
        "requires_manual_resolution": bool(reasons),
        "resolution_reasons": reasons,
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
