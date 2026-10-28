#!/usr/bin/env python3
"""Compose native routing with an offline, read-only risk policy.

No provider is launched and no pen or approval is granted. Model capabilities
are checked against the selected instance's local catalog, not guessed from
vendor names. Live provider availability and applied effort remain unverified.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

VERSION = "4.2.0"
HERE = Path(__file__).resolve().parent
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
TIER_ORDER = ("economy", "balanced", "flagship")
POLICY_TIERS = {"economy": "economy", "balanced": "balanced", "advanced": "flagship"}
CONTEXT_ORDER = ("small", "large", "xlarge")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/+~-]{0,127}\Z")
MAX_JSON_BYTES = 1024 * 1024
MAX_MODELS = 512


def load_decision(path=None):
    """Load the co-shipped policy without creating a bytecode sidecar."""
    path = Path(path or HERE / "m8shift-decision.py")
    spec = importlib.util.spec_from_file_location("m8shift_decision", path)
    if spec is None or spec.loader is None:
        raise ValueError("decision_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    # Executing the trusted sibling's source avoids importlib's pycache write.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def _safe_id(value):
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _ids(values, limit=128):
    return (isinstance(values, list) and len(values) <= limit
            and all(_safe_id(value) for value in values)
            and len(values) == len(set(values)))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("nonfinite_json_number")


def _decode_json(data):
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("json_size_limit")
    try:
        value = json.loads(data, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_json_object") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid_json_object")
    return value


def _catalog(manifest):
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != "m8shift.routing.models.v1"
            or manifest.get("authority", "advisory") != "advisory"
            or manifest.get("enabled") is not True):
        raise ValueError("model_catalog_not_enabled_or_invalid")
    tiers = manifest.get("tiers", list(TIER_ORDER))
    if not isinstance(tiers, list) or tuple(tiers) != TIER_ORDER:
        raise ValueError("unsupported_tier_order")
    contexts = manifest.get("context_classes", list(CONTEXT_ORDER))
    if not _ids(contexts) or not contexts:
        raise ValueError("invalid_context_order")
    rows = manifest.get("models")
    if not isinstance(rows, list) or len(rows) > MAX_MODELS:
        raise ValueError("invalid_model_catalog")
    catalog = {}
    for row in rows:
        if (not isinstance(row, dict) or not _safe_id(row.get("id"))
                or not _safe_id(row.get("provider"))
                or row.get("tier") not in TIER_ORDER
                or row.get("context_class") not in contexts
                or not _ids(row.get("capabilities"))
                or row["id"] in catalog):
            raise ValueError("invalid_model_catalog")
        catalog[row["id"]] = row
    return catalog, contexts


def merge_recommendations(policy, runtime, *, models_manifest=None):
    """Return a plan, never launch authority; invalid evidence fails closed."""
    if not isinstance(runtime, dict) or not isinstance(policy, dict):
        raise ValueError("recommendations_must_be_objects")
    if (runtime.get("authority") != "advisory" or runtime.get("launch") is not False
            or runtime.get("route") != "recommend" or type(runtime.get("ok")) is not bool):
        raise ValueError("invalid_runtime_authority_or_schema")
    decision = policy.get("decision")
    if (policy.get("schema") != "m8shift.routing.v1"
            or policy.get("status") != "proposed" or not isinstance(decision, dict)
            or decision.get("effort") not in EFFORT_ORDER
            or not isinstance(decision.get("model_tier"), str)
            or decision["model_tier"] not in POLICY_TIERS
            or decision.get("strategy") not in ("direct", "delegate", "parallel")
            or any(type(decision.get(key)) is not bool
                   for key in ("advisor_required", "human_approval_required"))):
        raise ValueError("invalid_decision_policy")
    required_effort = decision["effort"]
    required_tier = POLICY_TIERS[decision["model_tier"]]
    blockers = []
    reviews = []
    ok = runtime["ok"]
    picked = runtime.get("picked") if ok else None
    picked = picked if _safe_id(picked) else None
    native_effort = runtime.get("effort", "") if ok else ""
    effective_effort = None
    if native_effort in EFFORT_ORDER:
        effective_effort = max((native_effort, required_effort), key=EFFORT_ORDER.index)
    else:
        blockers.append("invalid_or_missing_runtime_effort")
    findings = runtime.get("findings", [])
    if (not isinstance(findings, list)
            or any(not isinstance(row, dict) or row.get("severity") == "error"
                   for row in findings)):
        blockers.append("runtime_findings_error")
    if not ok:
        blockers.append("runtime_manifest_or_routing_error")
    if not picked:
        blockers.append("no_runtime_model")
    floor = runtime.get("floor")
    if floor in TIER_ORDER:
        required_tier = max((required_tier, floor), key=TIER_ORDER.index)
    else:
        blockers.append("invalid_runtime_floor")
    caps = runtime.get("required_capabilities")
    context = runtime.get("required_context_class")
    if not _ids(caps):
        blockers.append("invalid_capability_requirements")
    feasible = runtime.get("feasible")
    if not isinstance(feasible, list) or len(feasible) > MAX_MODELS:
        blockers.append("missing_or_invalid_feasible_evidence")
        feasible = []
    try:
        catalog, contexts = _catalog(models_manifest)
    except (TypeError, ValueError) as exc:
        blockers.append(str(exc) if isinstance(exc, ValueError) else "invalid_model_catalog")
        catalog, contexts = {}, []
    if context not in contexts:
        blockers.append("invalid_context_requirement")
    eligible = []
    seen = set()
    for row in feasible:
        if not isinstance(row, dict) or not _safe_id(row.get("id")):
            blockers.append("invalid_feasible_model")
            continue
        model_id = row["id"]
        model = catalog.get(model_id)
        if (model_id in seen or not model
                or any(row.get(key) != model.get(key) for key in
                       ("tier", "context_class", "cost_band", "latency"))):
            blockers.append("feasible_catalog_mismatch")
            continue
        seen.add(model_id)
        if (TIER_ORDER.index(model["tier"]) >= TIER_ORDER.index(required_tier)
                and _ids(caps) and set(caps).issubset(model["capabilities"])
                and context in contexts
                and contexts.index(model["context_class"]) >= contexts.index(context)):
            eligible.append(model)
    if picked and picked not in seen:
        blockers.append("runtime_pick_not_feasible")
    if not eligible:
        blockers.append("no_compatible_model")
    # A pinned native route cannot be weakened by a caller's low-risk hint.
    pinned = runtime.get("downgradable") is False
    if decision["advisor_required"] or pinned:
        reviews.append("advisor_required")
    if decision["human_approval_required"]:
        reviews.append("human_approval_required")
    selected = eligible[0] if eligible and not blockers else None
    blockers = list(dict.fromkeys(blockers))
    reasons = blockers + reviews
    return {
        "schema": "m8shift.routing.bridge.v1", "status": "proposed",
        "authority": "advisory", "launch": False, "execution_authorized": False,
        "resolution_status": "blocked" if blockers else "review_required" if reviews else "resolved",
        "runtime_ok": ok, "runtime_model": picked,
        "compatible_model": selected["id"] if selected else None,
        "required_tier": required_tier,
        "runtime_effort": native_effort if native_effort in EFFORT_ORDER else "",
        "effective_effort": effective_effort,
        "effort_source": "maximum_of_policies" if effective_effort else "unresolved",
        "effective_strategy": ("direct" if pinned or required_tier == "flagship"
                               else decision["strategy"]),
        "policy": copy.deepcopy(policy),
        "requires_manual_resolution": bool(reasons), "resolution_reasons": reasons,
        "compatibility_evidence": ({
            "source": "local_routing_manifest", "provider": selected["provider"],
            "tier": selected["tier"], "capabilities": list(selected["capabilities"]),
            "context_class": selected["context_class"],
            "provider_availability": "not_probed", "provider_effort": "not_applied",
        } if selected else None),
        "note": "A resolved advisory plan is not permission to launch, write, approve, or merge",
    }


def _project_root(value):
    env_defined = "M8SHIFT_ROOT" in os.environ
    env_root = os.environ.get("M8SHIFT_ROOT", "").strip()
    if env_defined and not env_root:
        raise ValueError("empty_environment_root")
    explicit = Path(value).expanduser().resolve() if value is not None else None
    inherited = Path(env_root).expanduser().resolve() if env_root else None
    if explicit and inherited and explicit != inherited:
        raise ValueError("conflicting_project_roots")
    root = explicit or inherited or Path.cwd().resolve()
    if not root.is_dir() or not all((root / name).is_file() for name in ("M8SHIFT.md", "m8shift.py")):
        raise ValueError("project_root_not_initialized")
    return root


def _read_manifest(root, name):
    path = root / ".m8shift" / "routing" / name
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("unsafe_manifest_path")
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    return _decode_json(data), hashlib.sha256(data).hexdigest()


def _run_runtime(command, root, timeout):
    # Scratch output is outside the relay; read size and process lifetime are bounded.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(command, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=errors, start_new_session=os.name != "nt")
        try:
            proc.wait(timeout=timeout)
        except BaseException:
            if os.name != "nt":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            proc.wait(timeout=5)
            raise
        output.seek(0)
        data = output.read(MAX_JSON_BYTES + 1)
    if proc.returncode not in (0, 1):
        raise RuntimeError("runtime_route_failed")
    result = _decode_json(data)
    if (proc.returncode == 0) != (result.get("ok") is True):
        raise RuntimeError("runtime_exit_status_mismatch")
    return result


def recommend(task, task_type, *, project_root=None, input_tokens=0,
              runtime_script=None, timeout=15, **policy_options):
    if not _safe_id(task_type):
        raise ValueError("invalid_task_type")
    if type(input_tokens) is not int or not 0 <= input_tokens <= 10000000:
        raise ValueError("invalid_input_tokens")
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 60):
        raise ValueError("invalid_timeout")
    policy = load_decision().decide(task, **policy_options)
    root = _project_root(project_root)
    models, model_digest = _read_manifest(root, "models.json")
    skills, skill_digest = _read_manifest(root, "skills.json")
    _catalog(models)
    if (skills.get("schema") != "m8shift.routing.skills.v1"
            or skills.get("authority", "advisory") != "advisory"
            or skills.get("enabled", True) is not True):
        raise ValueError("skills_manifest_disabled_or_invalid")
    runtime_script = Path(runtime_script or HERE / "m8shift-runtime.py").resolve()
    if not runtime_script.is_file():
        raise ValueError("runtime_script_missing")
    command = [sys.executable, "-B", str(runtime_script), "--project-root", str(root),
               "route", "recommend", "--task-type", task_type,
               "--input-tokens", str(input_tokens), "--json"]
    runtime = _run_runtime(command, root, timeout)
    if runtime.get("task_type") != task_type:
        raise RuntimeError("runtime_task_type_mismatch")
    if (_read_manifest(root, "models.json")[1] != model_digest
            or _read_manifest(root, "skills.json")[1] != skill_digest):
        raise RuntimeError("routing_manifest_changed_during_read")
    result = merge_recommendations(policy, runtime, models_manifest=models)
    result["manifest_digests"] = {"models": model_digest, "skills": skill_digest}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("task")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--input-tokens", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--risk", choices=("low", "moderate", "high", "critical"), default="low")
    parser.add_argument("--complexity", choices=("low", "moderate", "high", "critical"), default="low")
    parser.add_argument("--failures", type=int, default=0)
    parser.add_argument("--budget", choices=("economy", "balanced", "quality"), default="balanced")
    parser.add_argument("--has-tests", action="store_true")
    parser.add_argument("--independent-parts", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = recommend(args.task, args.task_type, project_root=args.project_root,
                           input_tokens=args.input_tokens, timeout=args.timeout,
                           risk=args.risk, complexity=args.complexity, failures=args.failures,
                           budget=args.budget, has_tests=args.has_tests,
                           independent_parts=args.independent_parts)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        # Do not echo filesystem locations, provider output or task content.
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        print(json.dumps({"schema": "m8shift.routing.bridge.v1", "status": "refused",
                          "authority": "advisory", "launch": False,
                          "execution_authorized": False, "reason": reason}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return {"resolved": 0, "blocked": 1, "review_required": 3}[result["resolution_status"]]


if __name__ == "__main__":
    sys.exit(main())
