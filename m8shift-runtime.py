#!/usr/bin/env python3
"""m8shift-runtime.py — optional local runtime companion for M8Shift.

The companion records local presence, operator messages, progress, and run lifecycle
sidecars under `.m8shift/runtime/`. It never edits `M8SHIFT.md` directly and never becomes
an authority for the pen; all routing remains owned by `m8shift.py`.
"""
import argparse
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import math
import os
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

VERSION = "3.52.0"
RUNTIME_EVENT_SCHEMA = "m8shift.runtime.event.v1"
PRESENCE_SCHEMA = "m8shift.runtime.presence.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
CORE_PATH = os.path.join(HERE, "m8shift.py")
RUNTIME_DIR = os.path.join(HERE, ".m8shift", "runtime")
PROJECT_DIR = os.path.join(HERE, ".m8shift")
CONTEXT_DIR = os.path.join(PROJECT_DIR, "context")
CONTEXT_ADAPTERS_DIR = os.path.join(CONTEXT_DIR, "adapters")
CONTEXT_RTK_ADAPTER = os.path.join(CONTEXT_ADAPTERS_DIR, "rtk-shell-output.json")
CONTEXT_METRICS = os.path.join(CONTEXT_DIR, "metrics.jsonl")
PROVIDERS = os.path.join(PROJECT_DIR, "providers.json")
ROUTING_DIR = os.path.join(PROJECT_DIR, "routing")
ROUTING_SKILLS = os.path.join(ROUTING_DIR, "skills.json")
ROUTING_MODELS = os.path.join(ROUTING_DIR, "models.json")
ROUTING_SKILLS_SCHEMA = "m8shift.routing.skills.v1"
ROUTING_MODELS_SCHEMA = "m8shift.routing.models.v1"
ROLES_DIR = os.path.join(PROJECT_DIR, "roles")
WORKFLOWS_DIR = os.path.join(PROJECT_DIR, "workflows")
POLICIES_DIR = os.path.join(PROJECT_DIR, "policies")
RUN_REPORTS_DIR = os.path.join(PROJECT_DIR, "runs")
PRESENCE = os.path.join(RUNTIME_DIR, "presence.json")
RUNS = os.path.join(RUNTIME_DIR, "runs.jsonl")
PROGRESS = os.path.join(RUNTIME_DIR, "progress.jsonl")
IDEMPOTENCY = os.path.join(RUNTIME_DIR, "idempotency.jsonl")
APPROVALS = os.path.join(RUNTIME_DIR, "approvals.jsonl")
INBOX_DIR = os.path.join(RUNTIME_DIR, "inbox")
RETENTION_POLICY = os.path.join(RUNTIME_DIR, "retention.json")
RETENTION_ARCHIVE_INDEX = os.path.join(RUNTIME_DIR, "archive", "index.jsonl")
RETENTION_SCHEMA = "m8shift.runtime.retention.v1"
NOTIFY_DIR = os.path.join(RUNTIME_DIR, "notify")
NOTIFY_CONFIG = os.path.join(RUNTIME_DIR, "notify.config.json")
NOTIFY_LOG = os.path.join(NOTIFY_DIR, "log.jsonl")
NOTIFY_TIERS = {"stdout", "file", "bell", "os", "hook"}
NOTIFY_EVENTS = {"turn-ready", "stale", "blocked", "done"}
NOTIFY_PLACEHOLDERS = {"{agent}", "{event}", "{state}"}
NOTIFY_DEFAULT_DEDUP_S = 300
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
AGENT_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")
ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
PLATFORM_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
ROUTING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/+~-]{0,127}\Z")
PROVIDER_MODES = {"interactive", "headless", "hybrid", "local"}
DEFAULT_TIER_ORDER = ["economy", "balanced", "flagship"]
DEFAULT_COST_ORDER = ["$", "$$", "$$$", "$$$$"]
DEFAULT_LATENCY_ORDER = ["fast", "medium", "slow"]
DEFAULT_CONTEXT_ORDER = ["small", "large", "xlarge"]
HIGH_STAKES_TASK_TYPES = {"adversarial-verify", "security-review", "legal-compliance-review", "legal-review"}
DEFAULT_CAPABILITIES = {
    "claude": ["read_repo", "write_repo", "review", "long_context"],
    "codex": ["read_repo", "write_repo", "run_tests"],
    "gemini": ["read_repo", "review", "image_reasoning"],
    "vibe": ["read_repo", "write_repo", "review"],
}
DEFAULT_ANCHORS = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "vibe": "AGENTS.md",
}
HEADROOM_DEFAULTS = {
    "warn_after_turns_since_checkpoint": 8,
    "warn_after_handoff_body_bytes": 12000,
    "warn_after_relay_bytes": 250000,
    "pause_recommendation_after_turns_since_checkpoint": 15,
    "pause_recommendation_after_relay_bytes": 500000,
}
HEADROOM_LEVEL = {"ok": 0, "warning": 1, "high": 2}
MAX_HASH_BYTES = 512 * 1024 * 1024
# ── RFC 047 (Phases B–E) — listener lifecycle companion + OS backend adapters ──
SELF_PATH = os.path.abspath(__file__)
RELAY_PATH = os.path.join(HERE, "M8SHIFT.md")
RELAY_LOCK_BEGIN = "<!-- M8SHIFT:LOCK:BEGIN -->"
RELAY_LOCK_END = "<!-- M8SHIFT:LOCK:END -->"
LISTENERS_DIR = os.path.join(RUNTIME_DIR, "listeners")
LISTENER_LOGS_DIR = os.path.join(RUNTIME_DIR, "logs")
LISTENER_PROFILES_DIR = os.path.join(PROJECT_DIR, "providers")
DEFAULT_RUNNER_PATH = os.path.join(HERE, "examples", "headless_runner.py")
LISTENER_PROFILE_SCHEMA = "m8shift.listener.profile.v1"
LISTENER_STATE_SCHEMA = "m8shift.listener.state.v1"
LISTENER_PLAN_SCHEMA = "m8shift.listener.plan.v1"
LISTENER_BACKEND_SCHEMA = "m8shift.listener.backend.v1"
LISTENER_PHASES = ("polling", "backoff", "halted")
LISTENER_BACKENDS = ("auto", "local", "launchd", "systemd", "windows")
LISTENER_SERVICE_BACKENDS = ("launchd", "systemd", "windows")
LISTENER_BACKOFF_BASE_S = 20
LISTENER_MAX_BACKOFF_S = 300
LISTENER_DEFAULT_POLL_S = 20.0
LISTENER_DEFAULT_MAX_RETRIES = 3
LISTENER_DETACHED_ENV = "M8SHIFT_LISTENER_DETACHED"
# Injectable backend-probe seam (RFC 047 Phase D): a JSON object in this env var
# overrides any probed fact (platform/launchctl/systemctl/schtasks/gui_session/
# user_session/protected_folder), so tests and selection debugging never have to
# touch a real service manager.
LISTENER_BACKEND_PROBE_ENV = "M8SHIFT_LISTENER_BACKEND_PROBE"
# Writer-side log rotation (RFC 047): 5 MiB / keep 3 generations by default; the
# threshold is injectable so tests rotate at a tiny size. runs.jsonl is exempt
# (it is the runtime ledger, governed by `retention`, never by log rotation).
LISTENER_LOG_MAX_ENV = "M8SHIFT_LISTENER_LOG_MAX_BYTES"
LISTENER_LOG_MAX_BYTES = 5 * 1024 * 1024
LISTENER_LOG_KEEP = 3
LISTENER_REPEATED_NON_COMPLETION_N = 2
# macOS TCC-protected user folders (heuristic, RFC 047): launchd services often
# cannot read projects under these; paths are always derived from expanduser("~").
MACOS_PROTECTED_FOLDERS = ("Documents", "Desktop", "Downloads",
                           os.path.join("Library", "Mobile Documents"))
# Runner one-shot exit vocabulary (RFC 047 Phase A / examples/headless_runner.py):
# 0 success, 1 run failure, 2 infrastructure, 3 external_transition, 4 suspended.
LISTENER_RUNNER_EXITS = {
    0: "success",
    1: "run_failure",
    2: "infrastructure_failure",
    3: "external_transition",
    4: "suspended",
}
LISTENER_TURN_PROMPT = (
    "Apply M8SHIFT.protocol.md: you are {agent}; take exactly one relay turn "
    "(claim, work, append) and then exit."
)
LISTENER_RESUME_PROMPT = (
    "Apply M8SHIFT.protocol.md: you are {agent}; you ALREADY hold the pen "
    "(state WORKING_{agent_upper}) from an interrupted turn — do NOT claim again; "
    "finish the work, then append (or done) and exit."
)


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t=None):
    return (t or now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_core():
    if not os.path.exists(CORE_PATH):
        sys.exit(f"m8shift-runtime: missing core at {CORE_PATH}")
    spec = importlib.util.spec_from_file_location("m8shift_core", CORE_PATH)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


def ensure_runtime_dirs():
    os.makedirs(INBOX_DIR, exist_ok=True)


def ensure_notify_dir():
    os.makedirs(NOTIFY_DIR, exist_ok=True)


def ensure_project_dirs():
    os.makedirs(PROJECT_DIR, exist_ok=True)
    os.makedirs(ROUTING_DIR, exist_ok=True)
    os.makedirs(ROLES_DIR, exist_ok=True)
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)
    os.makedirs(POLICIES_DIR, exist_ok=True)


def write_text_if_missing(path, text, force=False):
    if os.path.exists(path) and not force:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def write_json_if_missing(path, data, force=False):
    if os.path.exists(path) and not force:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return True


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_agent_csv(raw):
    agents = []
    for token in (raw or "").split(","):
        name = token.strip().lower()
        if not name:
            continue
        if not AGENT_RE.fullmatch(name):
            sys.exit(f"m8shift-runtime: invalid agent name {name!r}")
        if name not in agents:
            agents.append(name)
    return agents


def active_roster_or_default(raw=""):
    explicit = parse_agent_csv(raw)
    if explicit:
        return explicit
    try:
        core = load_core()
        text = core.load_or_die()
        return list(core.active_agents(core.get_lock(text)))
    except SystemExit:
        return ["claude", "codex"]


def provider_template(agent):
    argv = []
    permissions = "human-driven"
    if agent == "codex":
        argv = ["codex", "exec", "$M8SHIFT_PROMPT"]
        permissions = "workspace-write"
    provider = {
        "name": agent,
        "provider": {
            "claude": "anthropic-claude",
            "codex": "openai-codex",
            "gemini": "google-gemini",
            "vibe": "vibe",
        }.get(agent, agent),
        "mode": "interactive" if agent in {"claude", "gemini", "vibe"} else "headless",
        "anchor": DEFAULT_ANCHORS.get(agent, "AGENTS.md"),
        "argv": argv,
        "capabilities": DEFAULT_CAPABILITIES.get(agent, ["read_repo", "review"]),
        "requires_env": [],
        "permissions": permissions,
    }
    return provider


def curated_provider_examples():
    common_env = [
        "HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER",
        "M8SHIFT_ROOT", "M8SHIFT_AGENT", "M8SHIFT_RUN_ID", "M8SHIFT_TURN",
    ]
    return [
        {
            "//": "Opt-in sample; copy into agents and adapt locally before running.",
            "name": "codex",
            "provider": "openai-codex",
            "mode": "headless",
            "anchor": "AGENTS.md",
            "argv": ["codex", "exec", "$M8SHIFT_PROMPT"],
            "argv_by_platform": {
                "default": ["codex", "exec", "$M8SHIFT_PROMPT"],
                "win32": ["codex.cmd", "exec", "$M8SHIFT_PROMPT"],
            },
            "env_allowlist": common_env,
            "capabilities": DEFAULT_CAPABILITIES.get("codex", ["read_repo", "write_repo", "run_tests"]),
            "requires_env": [],
            "permissions": "workspace-write",
        },
        {
            "//": "Opt-in sample; copy into agents and adapt locally before running.",
            "name": "claude",
            "provider": "anthropic-claude",
            "mode": "headless",
            "anchor": "CLAUDE.md",
            "argv": ["claude", "-p", "$M8SHIFT_PROMPT"],
            "argv_by_platform": {
                "default": ["claude", "-p", "$M8SHIFT_PROMPT"],
                "win32": ["claude.cmd", "-p", "$M8SHIFT_PROMPT"],
            },
            "env_allowlist": common_env,
            "capabilities": DEFAULT_CAPABILITIES.get("claude", ["read_repo", "write_repo", "review"]),
            "requires_env": [],
            "permissions": "workspace-write",
        },
    ]


def default_provider_registry(agents):
    return {
        "schema": "m8shift.providers.v1",
        "generated_by": f"m8shift-runtime.py {VERSION}",
        "agents": [provider_template(agent) for agent in agents],
        "examples": curated_provider_examples(),
    }


def default_routing_models_manifest():
    return {
        "schema": ROUTING_MODELS_SCHEMA,
        "authority": "advisory",
        "enabled": False,
        "cost_basis": "operator-supplied relative bands; NOT currency; no bundled vendor prices",
        "tiers": DEFAULT_TIER_ORDER,
        "cost_bands": DEFAULT_COST_ORDER,
        "latency_bands": DEFAULT_LATENCY_ORDER,
        "context_classes": DEFAULT_CONTEXT_ORDER,
        "models": [],
    }


def default_routing_skills_manifest():
    return {
        "schema": ROUTING_SKILLS_SCHEMA,
        "authority": "advisory",
        "enabled": False,
        "default_on_missing": "escalate_to_pen_holder",
        "defaults": {
            "min_model": "balanced",
            "optimum_model": "flagship",
            "downgradable": True,
            "required_capabilities": [],
            "required_context_class": "small",
            "verify": ["pen-holder verifies against source before integrate"],
        },
        "task_types": {},
    }


RUNTIME_README = """# M8Shift runtime companion

This directory is optional. It belongs to `m8shift-runtime.py`, not to the passive
core relay.

- `providers.json`: host-side agent/provider registry. Keep secrets out of it.
  Generated registries include opt-in `examples` for cooperative headless CLIs;
  copy/adapt them into active agents before use.
- `routing/`: optional advisory model/task routing manifests. Defaults are empty,
  provider-neutral, and contain no vendor prices.
- `roles/`: stable behavioral role contracts.
- `workflows/`: simple local workflow definitions.
- `policies/`: human approval and runtime policy notes.
- `runtime/`, `runs/`, `cache/`, `tmp/`: generated state; keep ignored.

Runtime JSONL sidecars use the `m8shift.runtime.event.v1` envelope. Invalid or
deleted sidecars are diagnostics, not core relay failures. The runtime companion
uses `presence.json` as one advisory lane per agent identity: a fresh lane blocks a
second managed runtime, and stale takeover must be explicit. Optional no-progress
thresholds warn or block only the companion loop when progress/run events stop. It
also provides `retention prune --keep N` for basic fixed-count JSONL pruning and
`retention apply` / `retention policy show` for an opt-in
`.m8shift/runtime/retention.json` policy. Older rows can be archived under
`.m8shift/runtime/archive/` with an audit index. It never edits `M8SHIFT.md`
directly and never owns the pen.
"""


DEFAULT_ROLES = {
    "coordinator": """# Coordinator role

Owns scope, sequencing, and handoff quality.

- Keep the M8Shift relay moving.
- Assign implementer/reviewer responsibilities explicitly.
- Escalate to the human when scope or authority is missing.
""",
    "implementer": """# Implementer role

Makes the requested change while holding the M8Shift pen.

- Claim before editing.
- Keep changes scoped.
- Run proportionate validation.
- Append with concrete files, tests, and next ask.
""",
    "reviewer": """# Reviewer role

Reviews a completed handoff without becoming the implementer by accident.

- Check the diff, tests, docs, and boundaries.
- Return `approve`, `revise`, or `reject` with evidence.
- Do not edit unless explicitly assigned implementation work.
""",
}


DEFAULT_WORKFLOW = {
    "schema": "m8shift.workflow.v1",
    "id": "default-code-review",
    "steps": [
        {"id": "plan", "role": "coordinator", "next": "implement"},
        {"id": "implement", "role": "implementer", "next": "review"},
        {"id": "review", "role": "reviewer", "next": "final"},
        {"id": "final", "role": "coordinator", "next": ""},
    ],
}


APPROVALS_POLICY = """# M8Shift approval policy

Require explicit human approval before:

- publishing, deployment, or pushes to protected branches;
- payments, account changes, or external messages;
- destructive filesystem cleanup;
- legal, medical, financial, or high-stakes claims;
- provider credential changes.

Record local approval evidence with:

```bash
python3 m8shift-runtime.py approve <run-id> <gate-id> --by <agent-or-human> --decision approved --reason "..."
```
"""


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"m8shift-runtime: cannot read {os.path.relpath(path, HERE)}: {e}")


def atomic_write_json(path, data):
    ensure_runtime_dirs()
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def append_jsonl(path, row):
    ensure_runtime_dirs()
    with open_append_jsonl_no_follow(path) as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl_rows(path, rows):
    if not rows:
        return
    with open_append_jsonl_no_follow(path) as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def reject_symlinked_runtime_path(path):
    runtime_abs = os.path.abspath(RUNTIME_DIR)
    candidate = os.path.abspath(path)
    try:
        if os.path.commonpath([runtime_abs, candidate]) != runtime_abs:
            return
    except ValueError:
        return
    current = runtime_abs
    if os.path.lexists(current) and os.path.islink(current):
        sys.exit(f"m8shift-runtime: refusing to append through symlink {os.path.relpath(current, HERE)}")
    relpath = os.path.relpath(candidate, runtime_abs)
    if relpath in ("", "."):
        return
    for part in relpath.split(os.sep):
        if not part or part == ".":
            continue
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            sys.exit(f"m8shift-runtime: refusing to append through symlink {os.path.relpath(current, HERE)}")
        if not os.path.exists(current):
            break


def open_append_jsonl_no_follow(path):
    reject_symlinked_runtime_path(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    reject_symlinked_runtime_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as e:
        sys.exit(f"m8shift-runtime: cannot append {os.path.relpath(path, HERE)}: {e}")
    return os.fdopen(fd, "a", encoding="utf-8")


def atomic_write_jsonl(path, rows):
    ensure_runtime_dirs()
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{n}: {e}") from e
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        return []
    return rows


def read_json_diagnostic(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return default, None
    except (OSError, json.JSONDecodeError) as e:
        return default, str(e)
    if not isinstance(data, type(default)):
        return default, f"expected {type(default).__name__}, got {type(data).__name__}"
    return data, None


def read_jsonl_diagnostic(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, RecursionError, ValueError) as e:
                    return rows, f"{path}:{n}: {e}"
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return [], str(e)
    return rows, None


def declared_rtk_state():
    raw = os.environ.get("M8SHIFT_RTK")
    if raw is None or raw.strip() == "":
        return {"self_declared": "off", "source": "default"}, None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on", "enabled", "rtk"}:
        return {"self_declared": "on", "source": "M8SHIFT_RTK"}, None
    if value in {"0", "false", "no", "off", "disabled", "native"}:
        return {"self_declared": "off", "source": "M8SHIFT_RTK"}, None
    return {
        "self_declared": "off",
        "source": "M8SHIFT_RTK",
        "raw": raw,
    }, {
        "severity": "warning",
        "check": "runtime.rtk_decl",
        "message": "M8SHIFT_RTK must be on/off; treating it as off",
    }


def sha256_file(path):
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("not a regular file")
    if st.st_size > MAX_HASH_BYTES:
        raise ValueError(f"file too large to hash ({st.st_size} bytes > {MAX_HASH_BYTES})")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_context_metrics():
    rows, err = read_jsonl_diagnostic(CONTEXT_METRICS)
    if err or not rows:
        return None
    row = rows[-1]
    return {
        "pack_id": row.get("pack_id", ""),
        "profile": row.get("profile", ""),
        "compression_ratio": row.get("compression_ratio"),
        "estimated_proxy_tokens_before": row.get("estimated_proxy_tokens_before"),
        "estimated_proxy_tokens_after": row.get("estimated_proxy_tokens_after"),
        "timestamp_utc": row.get("timestamp_utc", ""),
    }


def context_rtk_status():
    manifest, err = read_json_diagnostic(CONTEXT_RTK_ADAPTER, {})
    findings = []
    pinned = False
    reason = "adapter manifest missing; native context pack path"
    if err:
        findings.append({
            "severity": "warning",
            "check": "runtime.context_rtk",
            "message": f"{os.path.relpath(CONTEXT_RTK_ADAPTER, HERE)}: {err}",
        })
        reason = "adapter manifest unreadable; native context pack path"
    elif manifest:
        trusted = manifest.get("trusted_executable") if isinstance(manifest, dict) else None
        command = manifest.get("command") if isinstance(manifest, dict) else None
        program = command[0] if isinstance(command, list) and command else ""
        if program != "rtk":
            reason = "rtk adapter command is not rtk; native context pack path"
        elif not isinstance(trusted, dict):
            reason = "rtk adapter is not identity-pinned; native context pack path"
        else:
            path = trusted.get("path", "")
            expected = trusted.get("sha256", "")
            if not (isinstance(path, str) and os.path.isabs(path)):
                reason = "rtk trusted executable path is invalid; native context pack path"
            elif not (isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected)):
                reason = "rtk trusted executable hash is invalid; native context pack path"
            elif not os.path.exists(path):
                reason = "rtk trusted executable is absent; native context pack path"
            else:
                try:
                    actual = sha256_file(path)
                except (OSError, ValueError) as e:
                    reason = f"rtk trusted executable cannot be read: {e}; native context pack path"
                else:
                    if actual == expected:
                        pinned = True
                        reason = "pinned, compressing packs"
                    else:
                        reason = "rtk trusted executable hash mismatch; native context pack path"
    state = "on" if pinned else "off"
    return {
        "state": state,
        "pinned": pinned,
        "label": "RTK: ON (pinned, compressing packs)" if pinned else "RTK: OFF (native)",
        "reason": reason,
        "last_pack": latest_context_metrics(),
        "findings": findings,
    }


def presence_rtk_label(presence_row):
    if not isinstance(presence_row, dict):
        return "off"
    rtk = presence_row.get("rtk")
    if isinstance(rtk, dict):
        return rtk.get("self_declared", "off")
    if isinstance(rtk, str):
        return rtk if rtk in {"on", "off"} else "off"
    return "off"


def headless_runtime():
    return bool(os.environ.get("CI")) or not sys.stdout.isatty()


def default_notify_config():
    tiers = ["stdout", "file"]
    if not headless_runtime():
        tiers.append("bell")
    return {
        "tiers": tiers,
        "os_preset": "off",
        "hook": None,
        "dedup_window_seconds": NOTIFY_DEFAULT_DEDUP_S,
    }


def split_csv(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def normalize_notify_config(raw):
    cfg = default_notify_config()
    findings = []
    if not raw:
        return cfg, findings
    if not isinstance(raw, dict):
        return cfg, [{
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": "notify config must be a JSON object; using defaults",
        }]
    tiers = raw.get("tiers", cfg["tiers"])
    if not isinstance(tiers, list) or not all(isinstance(t, str) for t in tiers):
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": "notify tiers must be a list of strings; using defaults",
        })
    else:
        unknown = [t for t in tiers if t not in NOTIFY_TIERS]
        if unknown:
            findings.append({
                "severity": "warning",
                "check": "runtime.notify_config",
                "message": f"unknown notify tier(s): {', '.join(sorted(unknown))}",
            })
        known = [t for t in tiers if t in NOTIFY_TIERS]
        if known:
            cfg["tiers"] = known
    preset = raw.get("os_preset", cfg["os_preset"])
    if isinstance(preset, str) and preset.strip():
        cfg["os_preset"] = preset.strip()
    elif preset not in (None, ""):
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": "os_preset must be a string; using default",
        })
    hook = raw.get("hook", cfg["hook"])
    if hook is None:
        cfg["hook"] = None
    elif isinstance(hook, list) and all(isinstance(x, str) and x for x in hook):
        cfg["hook"] = hook
    else:
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_hook",
            "message": "hook must be an argv list of non-empty strings; hook tier disabled",
        })
        cfg["hook"] = None
    dedup = raw.get("dedup_window_seconds", cfg["dedup_window_seconds"])
    try:
        dedup = int(dedup)
        if dedup < 0:
            raise ValueError
        cfg["dedup_window_seconds"] = dedup
    except (TypeError, ValueError):
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": "dedup_window_seconds must be a non-negative integer; using default",
        })
    findings.extend(notify_hook_findings(cfg.get("hook")))
    return cfg, findings


def load_notify_config():
    raw, err = read_json_diagnostic(NOTIFY_CONFIG, {})
    cfg, findings = normalize_notify_config(raw)
    if err:
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": f"{os.path.relpath(NOTIFY_CONFIG, HERE)}: {err}",
        })
    return cfg, findings


def notify_hook_findings(hook):
    if not hook:
        return []
    findings = []
    if len(hook) == 1 and re.search(r"[;&|`$<>]", hook[0]):
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_hook",
            "message": "hook looks like a shell string; configure argv items instead",
        })
    for arg in hook:
        if any(ph in arg for ph in NOTIFY_PLACEHOLDERS) and arg not in NOTIFY_PLACEHOLDERS:
            findings.append({
                "severity": "warning",
                "check": "runtime.notify_hook",
                "message": f"placeholder in hook arg {arg!r} is not a literal argv item",
            })
    return findings


def notify_prompt_path(agent):
    return os.path.join(NOTIFY_DIR, f"{agent}.prompt")


def notify_event_path(agent):
    return os.path.join(NOTIFY_DIR, f"{agent}.event.json")


def write_notify_text(path, text):
    ensure_notify_dir()
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_notify_json(path, data):
    ensure_notify_dir()
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def append_notify_log(row):
    ensure_notify_dir()
    with open(NOTIFY_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def latest_notify_delivered(agent, event):
    rows, err = read_jsonl_diagnostic(NOTIFY_LOG)
    if err:
        return None
    for row in reversed(rows):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if (row.get("type") == "notify.delivered"
                and payload.get("agent") == agent
                and payload.get("event") == event):
            return row
    return None


def notify_duplicate(agent, event, window_seconds):
    if window_seconds <= 0:
        return False
    last = latest_notify_delivered(agent, event)
    if not last:
        return False
    ts = parse_utc(last.get("ts", ""))
    return bool(ts and (now() - ts).total_seconds() < window_seconds)


def default_resume_prompt(agent, event):
    if event == "turn-ready":
        return f"python3 m8shift.py next {agent}"
    return f"python3 m8shift-runtime.py status-runtime {agent}"


def read_prompt_source(path):
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().rstrip("\n")
    except OSError as e:
        sys.exit(f"m8shift-runtime: cannot read --prompt-file: {e}")


def os_notify_argv(preset, event, message):
    preset = (preset or "off").strip().lower()
    if preset in {"", "off", "none"}:
        return None, ""
    if preset == "auto":
        if sys.platform == "darwin":
            preset = "osascript"
        elif os.name == "nt":
            preset = "powershell"
        else:
            preset = "notify-send"
    if preset == "osascript":
        title = f"M8Shift {event}".replace("\\", "\\\\").replace('"', '\\"')
        body = (message or event).replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'display notification "{body}" with title "{title}"'], "osascript"
    if preset == "notify-send":
        return ["notify-send", f"M8Shift {event}", message or event], "notify-send"
    if preset in {"powershell", "pwsh"}:
        exe = "pwsh" if preset == "pwsh" else "powershell"
        # Local one-shot best-effort toast fallback: no shell=True; message is passed as argv.
        return [exe, "-NoProfile", "-Command", "Write-Output $args[0]", message or event], exe
    return [preset, f"M8Shift {event}", message or event], preset


def render_hook_argv(hook, *, agent, event, state):
    values = {"{agent}": agent, "{event}": event, "{state}": state}
    return [values.get(arg, arg) for arg in hook]


def run_argv(argv, tier, findings):
    if not argv:
        return False
    exe = argv[0]
    if os.path.isabs(exe):
        exists = os.path.exists(exe)
    else:
        exists = shutil.which(exe) is not None
    if not exists:
        findings.append({
            "severity": "warning",
            "check": f"runtime.notify_{tier}",
            "message": f"{tier} notifier executable {exe!r} not found; degraded to stdout/file",
        })
        return False
    try:
        r = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=10, shell=False)
    except Exception as e:  # noqa: BLE001 - notification must never block the relay
        findings.append({
            "severity": "warning",
            "check": f"runtime.notify_{tier}",
            "message": f"{tier} notifier failed: {e}",
        })
        return False
    if r.returncode != 0:
        findings.append({
            "severity": "warning",
            "check": f"runtime.notify_{tier}",
            "message": f"{tier} notifier exited {r.returncode}: {(r.stderr or r.stdout).strip()}",
        })
        return False
    return True


def emit_notification(agent, event, message, *, prompt="", config=None, state="", holder="", json_output=False):
    cfg_findings = []
    if config is None:
        config, cfg_findings = load_notify_config()
    findings = list(cfg_findings)
    tiers = list(config.get("tiers", []))
    if notify_duplicate(agent, event, safe_int(config.get("dedup_window_seconds"), NOTIFY_DEFAULT_DEDUP_S)):
        row = runtime_event(
            "notify.suppressed",
            agent=agent,
            payload={"agent": agent, "event": event, "reason": "dedup", "state": state},
        )
        append_notify_log(row)
        return {
            "ok": True,
            "delivered": False,
            "suppressed": "dedup",
            "tiers": [],
            "findings": findings,
        }

    prompt = prompt or default_resume_prompt(agent, event)
    payload = {
        "schema": "m8shift.runtime.notify.event.v1",
        "agent": agent,
        "event": event,
        "message": message,
        "prompt": prompt,
        "state": state,
        "holder": holder,
        "ts": iso(),
        "source": {"tool": "m8shift-runtime.py", "version": VERSION},
    }
    delivered = []
    skipped = []

    if "stdout" in tiers:
        delivered.append("stdout")
        if not json_output:
            print(f"notify {event} {agent}: {message}")
            if prompt:
                print(f"prompt: {prompt}")

    if "file" in tiers:
        try:
            write_notify_text(notify_prompt_path(agent), prompt + "\n")
            write_notify_json(notify_event_path(agent), payload)
            delivered.append("file")
        except OSError as e:
            findings.append({
                "severity": "warning",
                "check": "runtime.notify_file",
                "message": f"cannot write notification sidecar: {e}; degraded to stdout",
            })

    if "bell" in tiers:
        if os.environ.get("CI") or not sys.stdout.isatty():
            skipped.append("bell")
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
            delivered.append("bell")

    if "os" in tiers:
        if os.environ.get("CI"):
            skipped.append("os")
        else:
            argv, preset = os_notify_argv(config.get("os_preset", "auto"), event, message)
            if argv and run_argv(argv, "os", findings):
                delivered.append(f"os:{preset}")

    if "hook" in tiers:
        if os.environ.get("CI"):
            skipped.append("hook")
        elif config.get("hook"):
            argv = render_hook_argv(config["hook"], agent=agent, event=event, state=state)
            if run_argv(argv, "hook", findings):
                delivered.append("hook")
        else:
            findings.append({
                "severity": "warning",
                "check": "runtime.notify_hook",
                "message": "hook tier enabled but no hook argv configured",
            })

    if set(tiers) - {"stdout"}:
        append_notify_log(runtime_event(
            "notify.delivered",
            agent=agent,
            payload={
                "agent": agent,
                "event": event,
                "message": message,
                "prompt": prompt,
                "state": state,
                "holder": holder,
                "tiers": delivered,
                "skipped": skipped,
                "findings": findings,
            },
        ))
    return {
        "ok": True,
        "delivered": bool(delivered),
        "suppressed": "",
        "tiers": delivered,
        "skipped": skipped,
        "findings": findings,
        "event": payload,
    }


def validate_session_id(session_id):
    if not SESSION_RE.fullmatch(session_id):
        sys.exit("m8shift-runtime: unsafe --session value")
    return session_id


def validate_run_id(run_id):
    if (not SESSION_RE.fullmatch(run_id)
            or run_id in {".", ".."}
            or "/" in run_id
            or "\\" in run_id
            or ":" in run_id):
        sys.exit("m8shift-runtime: unsafe run id")
    return run_id


def load_status(core):
    text = core.load_or_die()
    lk = core.get_lock(text)
    return text, lk


def safe_relay_snapshot():
    try:
        core = load_core()
        _, lk = load_status(core)
    except (SystemExit, Exception):
        return {}
    return {
        "state": lk.get("state", ""),
        "holder": lk.get("holder", ""),
        "turn": lk.get("turn", ""),
    }


def runtime_event(event_type, *, agent="", session_id="", run_id="", idempotency_key="",
                  payload=None, **legacy_fields):
    row = {
        "schema": RUNTIME_EVENT_SCHEMA,
        "type": event_type,
        "ts": iso(),
        "source": {"tool": "m8shift-runtime.py", "version": VERSION},
        "relay": safe_relay_snapshot(),
        "idempotency_key": idempotency_key or "",
        "payload": payload or {},
    }
    if agent:
        row["agent"] = agent
    if session_id:
        row["session_id"] = session_id
    if run_id:
        row["run_id"] = run_id
    row.update({k: v for k, v in legacy_fields.items() if v is not None})
    return row


def validate_agent(core, agent):
    load_status(core)  # sets the active roster in the imported core module
    return core.need_agent(agent)


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_utc(value):
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def fresh_presence(row, stale_after):
    last = parse_utc(row.get("last_seen", ""))
    if not last:
        return False
    if (now() - last).total_seconds() > stale_after:
        return False
    pid = row.get("pid")
    return pid_alive(pid) or not isinstance(pid, int)


def relay_runtime_state(lk, agent):
    st = lk.get("state", "")
    if st in ("IDLE", f"AWAITING_{agent.upper()}"):
        return "blocked"
    if st == f"WORKING_{agent.upper()}":
        return "working"
    if st == "DONE":
        return "stale"
    return "waiting"


def iso_from_dt(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def latest_runtime_activity(agent, run_id):
    findings = []
    latest = None
    for path in (RUNS, PROGRESS):
        rows, err = read_jsonl_diagnostic(path)
        if err:
            findings.append({"severity": "warning", "check": "runtime.jsonl", "message": err})
            continue
        for row in rows:
            if row.get("agent") != agent:
                continue
            if run_id and row.get("run_id") != run_id:
                continue
            ts = parse_utc(row.get("ts", ""))
            if ts and (latest is None or ts > latest):
                latest = ts
    return latest, findings


def no_progress_hint(agent, run_id):
    target = f"{agent}/{run_id}" if run_id else agent
    return (
        f"Record progress for {target}, inspect status-runtime/doctor, or ask the "
        "operator for a handoff decision; no automatic force recovery is performed."
    )


def no_progress_finding(agent, row):
    status = row.get("no_progress_status")
    if status not in {"warning", "blocked"}:
        return None
    severity = "error" if status == "blocked" else "warning"
    return {
        "severity": severity,
        "check": "runtime.no_progress",
        "message": (
            f"{agent} runtime has no progress for "
            f"{row.get('no_progress_elapsed_seconds', 0)}s"
        ),
        "hint": row.get("no_progress_hint", ""),
    }


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def bytes_len(text):
    return len((text or "").encode("utf-8"))


def latest_headroom_checkpoint(session_id):
    rows, err = read_jsonl_diagnostic(RUNS)
    if err:
        return None, {"severity": "warning", "check": "runtime.jsonl", "message": err}
    best = None
    for row in rows:
        event = row.get("event") or row.get("type")
        if event != "headroom.checkpoint":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        row_session = row.get("session_id") or payload.get("session_id")
        if session_id and row_session and row_session != session_id:
            continue
        turn = safe_int(payload.get("turn", row.get("turn", 0)), 0)
        ts = parse_utc(row.get("ts", ""))
        candidate = {
            "turn": turn,
            "ts": row.get("ts", ""),
            "path": payload.get("path", row.get("path", "")),
        }
        if best is None:
            best = candidate
            continue
        best_ts = parse_utc(best.get("ts", ""))
        if turn > best.get("turn", 0) or (turn == best.get("turn", 0) and ts and (not best_ts or ts > best_ts)):
            best = candidate
    return best, None


def runtime_ledgers_bytes():
    total = 0
    for path in runtime_ledger_paths():
        try:
            total += os.path.getsize(path)
        except OSError:
            continue
    return total


def headroom_status_from_signals(warnings, highs, harness_status=""):
    if harness_status == "high" or highs:
        return "high"
    if harness_status == "warning" or warnings:
        return "warning"
    return "ok"


def headroom_next_action(status):
    if status == "high":
        return "checkpoint + pause recommended before more implementation"
    if status == "warning":
        return "write a checkpoint soon; pause if no immediate safe handoff exists"
    return "continue; checkpoint optional"


def compute_headroom(agent="", *, warn_turns=None, warn_body_bytes=None,
                     warn_relay_bytes=None, high_turns=None, high_relay_bytes=None,
                     harness_status="", harness_reason=""):
    core = load_core()
    if agent:
        validate_agent(core, agent)
    text, lk = load_status(core)
    turns = core.parse_turns(text)
    current_turn = safe_int(lk.get("turn", ""), max([t["n"] for t in turns], default=0))
    session_id = lk.get("session", "")
    checkpoint, checkpoint_finding = latest_headroom_checkpoint(session_id)
    checkpoint_turn = safe_int((checkpoint or {}).get("turn", 0), 0)
    turns_since_checkpoint = max(0, current_turn - checkpoint_turn)
    body_sizes = [bytes_len(t.get("body", "")) for t in turns]
    max_body_bytes = max(body_sizes, default=0)
    last_body_bytes = body_sizes[-1] if body_sizes else 0
    relay_bytes = bytes_len(text)
    runtime_bytes = runtime_ledgers_bytes()

    warn_turns = HEADROOM_DEFAULTS["warn_after_turns_since_checkpoint"] if warn_turns is None else warn_turns
    warn_body_bytes = HEADROOM_DEFAULTS["warn_after_handoff_body_bytes"] if warn_body_bytes is None else warn_body_bytes
    warn_relay_bytes = HEADROOM_DEFAULTS["warn_after_relay_bytes"] if warn_relay_bytes is None else warn_relay_bytes
    high_turns = HEADROOM_DEFAULTS["pause_recommendation_after_turns_since_checkpoint"] if high_turns is None else high_turns
    high_relay_bytes = HEADROOM_DEFAULTS["pause_recommendation_after_relay_bytes"] if high_relay_bytes is None else high_relay_bytes

    warnings = []
    highs = []
    if high_turns and turns_since_checkpoint >= high_turns:
        highs.append(f"{turns_since_checkpoint} turns since checkpoint")
    elif warn_turns and turns_since_checkpoint >= warn_turns:
        warnings.append(f"{turns_since_checkpoint} turns since checkpoint")
    if high_relay_bytes and relay_bytes >= high_relay_bytes:
        highs.append(f"relay is {relay_bytes} bytes")
    elif warn_relay_bytes and relay_bytes >= warn_relay_bytes:
        warnings.append(f"relay is {relay_bytes} bytes")
    if warn_body_bytes and max_body_bytes >= warn_body_bytes:
        warnings.append(f"largest handoff body is {max_body_bytes} bytes")
    if harness_status and harness_reason:
        (highs if harness_status == "high" else warnings).append(harness_reason)

    status = headroom_status_from_signals(warnings, highs, harness_status=harness_status)
    findings = [checkpoint_finding] if checkpoint_finding else []
    payload = {
        "status": status,
        "reasons": highs + warnings,
        "next": headroom_next_action(status),
        "metrics": {
            "turn": current_turn,
            "turns_total": len(turns),
            "turns_since_checkpoint": turns_since_checkpoint,
            "relay_bytes": relay_bytes,
            "runtime_ledger_bytes": runtime_bytes,
            "last_handoff_body_bytes": last_body_bytes,
            "max_handoff_body_bytes": max_body_bytes,
        },
        "thresholds": {
            "warn_after_turns_since_checkpoint": warn_turns,
            "warn_after_handoff_body_bytes": warn_body_bytes,
            "warn_after_relay_bytes": warn_relay_bytes,
            "pause_recommendation_after_turns_since_checkpoint": high_turns,
            "pause_recommendation_after_relay_bytes": high_relay_bytes,
        },
        "checkpoint": checkpoint or {},
        "relay": {"state": lk.get("state", ""), "holder": lk.get("holder", ""), "session": session_id},
        "agent": agent,
        "runtime_findings": findings,
        "runtime_version": VERSION,
    }
    return payload


def headroom_finding(headroom):
    status = headroom.get("status")
    if status not in {"warning", "high"}:
        return None
    severity = "error" if status == "high" else "warning"
    reasons = "; ".join(headroom.get("reasons") or ["headroom risk"])
    return {
        "severity": severity,
        "check": "runtime.headroom",
        "message": reasons,
        "hint": headroom.get("next", ""),
    }


def headroom_checkpoint_path(session_id, turn):
    safe_session = re.sub(r"[^A-Za-z0-9_.:@-]+", "-", session_id or "current").strip("-") or "current"
    name = f"headroom-{safe_session}-turn-{turn}-{uuid.uuid4().hex[:8]}.md"
    return os.path.join(".m8shift", "runs", name).replace(os.sep, "/")


def write_headroom_checkpoint(agent, headroom, reason):
    ensure_runtime_dirs()
    session_id = headroom.get("relay", {}).get("session", "")
    turn = headroom.get("metrics", {}).get("turn", 0)
    rel = headroom_checkpoint_path(session_id, turn)
    result = subprocess.run(
        [sys.executable, CORE_PATH, "session", "report", "current", "--write", "--output", rel],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    run_id = f"headroom-{uuid.uuid4().hex[:8]}"
    row = runtime_event(
        "headroom.checkpoint",
        agent=agent,
        session_id=session_id,
        run_id=run_id,
        payload={
            "path": rel,
            "turn": turn,
            "reason": reason,
            "session_id": session_id,
            "headroom_status": headroom.get("status"),
            "metrics": headroom.get("metrics", {}),
        },
        event="headroom.checkpoint",
        path=rel,
        turn=turn,
        reason=reason,
    )
    append_jsonl(RUNS, row)
    return rel


def evaluate_no_progress(agent, run_id, previous, warn_after=0, block_after=0):
    fields = {}
    if not warn_after and not block_after:
        return fields, []
    latest, findings = latest_runtime_activity(agent, run_id)
    latest_iso = iso_from_dt(latest)

    current = now()
    previous_activity = previous.get("last_activity_at", "") if isinstance(previous, dict) else ""
    if latest_iso and latest_iso != previous_activity:
        since = iso_from_dt(current)
    elif isinstance(previous, dict) and previous.get("no_progress_since"):
        since = previous["no_progress_since"]
    else:
        since = iso_from_dt(current)
    since_dt = parse_utc(since) or current
    elapsed = max(0, int((current - since_dt).total_seconds()))
    status = "ok"
    if block_after and elapsed >= block_after:
        status = "blocked"
    elif warn_after and elapsed >= warn_after:
        status = "warning"
    fields.update({
        "last_activity_at": latest_iso,
        "no_progress_since": since,
        "no_progress_elapsed_seconds": elapsed,
        "no_progress_warn_after_seconds": warn_after,
        "no_progress_block_after_seconds": block_after,
        "no_progress_status": status,
        "no_progress_hint": no_progress_hint(agent, run_id),
    })
    finding = no_progress_finding(agent, fields)
    if finding:
        findings.append(finding)
    return fields, findings


def update_presence(core, agent, session_id, mode, state, run_id="", stale_after=300,
                    takeover_stale=False, no_progress_warn_after=0, no_progress_block_after=0):
    validate_agent(core, agent)
    presence = read_json(PRESENCE, {})
    existing = presence.get(agent)
    findings = []
    takeover_from = ""
    if existing and existing.get("session_id") != session_id:
        owner = existing.get("session_id") or "<unknown>"
        is_fresh = fresh_presence(existing, stale_after)
        if not takeover_stale:
            sys.exit(
                f"m8shift-runtime: lane {agent!r} is already owned by session "
                f"{owner!r}; rerun with --takeover-stale only after it is stale"
            )
        if is_fresh:
            sys.exit(
                f"m8shift-runtime: lane {agent!r} is still fresh for session "
                f"{owner!r}; takeover refused"
            )
        takeover_from = owner
    _, lk = load_status(core)
    row = {
        "schema": PRESENCE_SCHEMA,
        "session_id": session_id,
        "run_id": run_id,
        "mode": mode,
        "state": state,
        "stale_after_seconds": stale_after,
        "relay_state": lk.get("state", ""),
        "holder": lk.get("holder", ""),
        "turn": lk.get("turn", ""),
        "last_seen": iso(),
        "cwd": HERE,
        "pid": os.getpid(),
        "m8shift_version": getattr(core, "VERSION", ""),
        "runtime_version": VERSION,
    }
    rtk, rtk_finding = declared_rtk_state()
    row["rtk"] = rtk
    if rtk_finding:
        findings.append(rtk_finding)
    if takeover_from:
        row["takeover_from"] = takeover_from
        row["takeover_at"] = row["last_seen"]
    previous = existing if existing and existing.get("session_id") == session_id else {}
    no_progress_fields, no_progress_findings = evaluate_no_progress(
        agent, run_id, previous,
        warn_after=no_progress_warn_after,
        block_after=no_progress_block_after,
    )
    row.update(no_progress_fields)
    findings.extend(no_progress_findings)
    presence[agent] = row
    atomic_write_json(PRESENCE, presence)
    return presence[agent], findings


def run_core_json(*args):
    r = subprocess.run([sys.executable, CORE_PATH, *args], cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return json.loads(r.stdout)


def watch_notification_event(lk, agent, prompt, blocked):
    state = lk.get("state", "")
    if blocked:
        return "blocked"
    if state == "DONE":
        return "done"
    if prompt and state == f"AWAITING_{agent.upper()}":
        return "turn-ready"
    if state.startswith("WORKING_"):
        expires = parse_utc(lk.get("expires", ""))
        if expires and now() > expires:
            return "stale"
    return ""


def cmd_watch(args):
    if args.interval < 1:
        sys.exit("m8shift-runtime: --interval must be >= 1")
    if args.no_progress_warn_after < 0 or args.no_progress_block_after < 0:
        sys.exit("m8shift-runtime: no-progress thresholds must be >= 0")
    if (args.no_progress_warn_after and args.no_progress_block_after
            and args.no_progress_block_after < args.no_progress_warn_after):
        sys.exit("m8shift-runtime: --no-progress-block-after must be >= --no-progress-warn-after")
    core = load_core()
    agent = validate_agent(core, args.agent)
    session_id = validate_session_id(args.session or f"{agent}-{uuid.uuid4().hex[:8]}")
    run_id = args.run or f"{iso().replace('-', '').replace(':', '')}-{agent}-{uuid.uuid4().hex[:6]}"
    while True:
        _, lk = load_status(core)
        state = relay_runtime_state(lk, agent)
        row, findings = update_presence(
            core, agent, session_id, "ui-watch", state,
            run_id=run_id, stale_after=args.stale_after,
            takeover_stale=args.takeover_stale or args.force,
            no_progress_warn_after=args.no_progress_warn_after,
            no_progress_block_after=args.no_progress_block_after,
        )
        prompt = ""
        if lk.get("state") in ("IDLE", f"AWAITING_{agent.upper()}"):
            prompt = f"python3 m8shift.py next {agent}"
        blocked = row.get("no_progress_status") == "blocked"
        notify_result = None
        event = watch_notification_event(lk, agent, prompt, blocked)
        if event and not args.json and not args.no_notify:
            notify_result = emit_notification(
                agent, event,
                row.get("no_progress_hint") if event == "blocked" else (prompt or lk.get("state", "")),
                prompt=prompt,
                state=lk.get("state", ""),
                holder=lk.get("holder", ""),
            )
        if args.json:
            print(json.dumps({
                "presence": row,
                "resume_prompt": prompt,
                "runtime_findings": findings,
            }, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{iso()} {agent} runtime={state} relay={lk.get('state')} holder={lk.get('holder')}")
            if prompt:
                print(f"resume: {prompt}")
            for finding in findings:
                print(f"{finding['severity']} {finding['check']}: {finding['message']}")
                if finding.get("hint"):
                    print(f"hint: {finding['hint']}")
            if notify_result:
                for finding in notify_result.get("findings", []):
                    print(f"{finding['severity']} {finding['check']}: {finding['message']}")
        if blocked:
            return 2
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_notify(args):
    if args.target == "config":
        return cmd_notify_config(args)
    return cmd_notify_event(args)


def cmd_notify_config(args):
    raw, err = read_json_diagnostic(NOTIFY_CONFIG, {})
    config, findings = normalize_notify_config(raw)
    if err:
        findings.append({
            "severity": "warning",
            "check": "runtime.notify_config",
            "message": f"{os.path.relpath(NOTIFY_CONFIG, HERE)}: {err}",
        })
    changed = False
    if args.enable:
        tiers = split_csv(args.enable)
        unknown = [t for t in tiers if t not in NOTIFY_TIERS]
        if unknown:
            sys.exit(f"m8shift-runtime: unknown notify tier(s): {', '.join(sorted(unknown))}")
        if "stdout" not in tiers:
            tiers.insert(0, "stdout")
        config["tiers"] = tiers
        changed = True
    if args.os_preset:
        config["os_preset"] = args.os_preset
        changed = True
    if args.hook_argv is not None and args.hook_json:
        sys.exit("m8shift-runtime: use either --hook-argv or --hook-json, not both")
    if args.hook_argv is not None:
        if not args.hook_argv:
            sys.exit("m8shift-runtime: --hook-argv requires at least one argv item")
        config["hook"] = args.hook_argv
        changed = True
    if args.hook_json:
        try:
            hook = json.loads(args.hook_json)
        except json.JSONDecodeError as e:
            sys.exit(f"m8shift-runtime: invalid --hook-json: {e}")
        if not isinstance(hook, list) or not all(isinstance(item, str) and item for item in hook):
            sys.exit("m8shift-runtime: --hook-json must be a JSON array of non-empty strings")
        config["hook"] = hook
        changed = True
    if args.dedup_window_seconds is not None:
        if args.dedup_window_seconds < 0:
            sys.exit("m8shift-runtime: --dedup-window-seconds must be >= 0")
        config["dedup_window_seconds"] = args.dedup_window_seconds
        changed = True
    config, post_findings = normalize_notify_config(config)
    findings.extend(post_findings)
    if changed:
        ensure_runtime_dirs()
        atomic_write_json(NOTIFY_CONFIG, config)
        ensure_runtime_gitignore()
    payload = {
        "config": config,
        "config_path": os.path.relpath(NOTIFY_CONFIG, HERE),
        "findings": findings,
        "runtime_version": VERSION,
        "written": changed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    print(json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2))
    for finding in findings:
        print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0


def cmd_notify_event(args):
    core = load_core()
    agent = validate_agent(core, args.target)
    if not args.event:
        sys.exit("m8shift-runtime: notify requires --event")
    if args.event not in NOTIFY_EVENTS:
        sys.exit(f"m8shift-runtime: invalid notify event {args.event!r}")
    _, lk = load_status(core)
    prompt = read_prompt_source(args.prompt_file) or default_resume_prompt(agent, args.event)
    message = args.message or prompt or args.event
    result = emit_notification(
        agent, args.event, message,
        prompt=prompt,
        state=lk.get("state", ""),
        holder=lk.get("holder", ""),
        json_output=args.json,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        if result.get("suppressed"):
            print(f"notify suppressed: {result['suppressed']}")
        for finding in result.get("findings", []):
            print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0


def idempotency_seen(key):
    if not key:
        return False
    return any(row.get("key") == key for row in read_jsonl(IDEMPOTENCY))


def record_idempotency(key, action):
    if key:
        append_jsonl(IDEMPOTENCY, runtime_event(
            "idempotency.recorded",
            idempotency_key=key,
            payload={"action": action, "key": key},
            key=key,
            action=action,
        ))


def cmd_operator(args):
    core = load_core()
    agent = validate_agent(core, args.agent)
    if args.idempotency_key and idempotency_seen(args.idempotency_key):
        print(f"duplicate ignored: idempotency key {args.idempotency_key}")
        return 0
    behavior = {
        "status": "Ask for progress only; no scope change.",
        "followup": "Deliver after the current safe point.",
        "collect": "Accumulate notes before the next turn or summary.",
        "interrupt": "Ask the active runtime to summarize and hand off safely.",
    }[args.mode]
    row = runtime_event(
        "operator.message",
        agent=agent,
        idempotency_key=args.idempotency_key or "",
        payload={"mode": args.mode, "message": args.message, "required_behavior": behavior},
        mode=args.mode,
        message=args.message,
    )
    append_jsonl(os.path.join(INBOX_DIR, f"{agent}.jsonl"), row)
    record_idempotency(args.idempotency_key, "operator")
    print(f"✓ queued {args.mode} message for {agent}")
    return 0


def cmd_progress(args):
    core = load_core()
    agent = validate_agent(core, args.agent)
    run_id = validate_run_id(args.run)
    row = runtime_event(
        "progress",
        agent=agent,
        run_id=run_id,
        payload={"message": args.message},
        message=args.message,
    )
    append_jsonl(PROGRESS, row)
    print(f"✓ progress recorded for {agent}/{args.run}")
    return 0


def select_provider_argv(row, platform=None):
    platform = platform or sys.platform
    by_platform = row.get("argv_by_platform")
    if isinstance(by_platform, dict):
        keys = [platform]
        if platform.startswith("linux"):
            keys.append("linux")
        elif platform.startswith("darwin"):
            keys.append("darwin")
        elif platform.startswith(("win32", "cygwin", "msys")):
            keys.extend(["win32", "windows"])
        keys.append("default")
        for key in keys:
            value = by_platform.get(key)
            if value:
                return value, key
    return row.get("argv", []), ""


def render_argv_template(argv, *, agent, prompt, run_id=""):
    values = {
        "$M8SHIFT_PROMPT": prompt,
        "$M8SHIFT_AGENT": agent,
        "$M8SHIFT_RUN_ID": run_id,
    }
    out = []
    for arg in argv:
        value = arg
        for marker, replacement in values.items():
            value = value.replace(marker, replacement)
        out.append(value)
    return out


def provider_entry_findings(agent, prefix, seen=None):
    findings = []
    if not isinstance(agent, dict):
        return [{"severity": "error", "check": "providers.agent", "message": f"{prefix} is not an object"}]
    name = agent.get("name", "")
    if not isinstance(name, str) or not AGENT_RE.fullmatch(name):
        findings.append({"severity": "error", "check": "providers.name", "message": f"{prefix}.name is invalid"})
    elif seen is not None and name in seen:
        findings.append({"severity": "error", "check": "providers.name_duplicate", "message": f"duplicate agent {name}"})
    if seen is not None and isinstance(name, str):
        seen.add(name)
    label = name or prefix
    if not isinstance(agent.get("provider", ""), str) or not agent.get("provider", "").strip():
        findings.append({"severity": "error", "check": "providers.provider", "message": f"{label} provider is required"})
    mode = agent.get("mode", "")
    if mode not in PROVIDER_MODES:
        findings.append({"severity": "error", "check": "providers.mode", "message": f"{label} mode must be one of {', '.join(sorted(PROVIDER_MODES))}"})
    if not isinstance(agent.get("anchor", ""), str) or not agent.get("anchor", "").strip():
        findings.append({"severity": "warning", "check": "providers.anchor", "message": f"{label} anchor is missing"})
    argv = agent.get("argv", [])
    if isinstance(argv, str):
        findings.append({"severity": "error", "check": "providers.argv_string", "message": f"{label} argv must be an array, not a shell string"})
    elif not isinstance(argv, list) or not all(isinstance(v, str) and v for v in argv):
        findings.append({"severity": "error", "check": "providers.argv", "message": f"{label} argv must be a list of non-empty strings"})
    by_platform = agent.get("argv_by_platform", {})
    if by_platform in (None, ""):
        by_platform = {}
    if by_platform and not isinstance(by_platform, dict):
        findings.append({"severity": "error", "check": "providers.argv_by_platform", "message": f"{label} argv_by_platform must be an object"})
    elif isinstance(by_platform, dict):
        for platform, platform_argv in by_platform.items():
            if not isinstance(platform, str) or not PLATFORM_RE.fullmatch(platform):
                findings.append({"severity": "error", "check": "providers.platform", "message": f"{label} has invalid platform key {platform!r}"})
            if isinstance(platform_argv, str):
                findings.append({"severity": "error", "check": "providers.argv_by_platform_string", "message": f"{label} argv_by_platform[{platform!r}] must be an array, not a shell string"})
            elif not isinstance(platform_argv, list) or not all(isinstance(v, str) and v for v in platform_argv):
                findings.append({"severity": "error", "check": "providers.argv_by_platform", "message": f"{label} argv_by_platform[{platform!r}] must be a list of non-empty strings"})
    selected_argv, selected_key = select_provider_argv(agent)
    if mode in {"headless", "hybrid"} and not selected_argv:
        findings.append({"severity": "warning", "check": "providers.argv_missing", "message": f"{label} has mode={mode} but no argv"})
    elif isinstance(selected_argv, list) and selected_argv:
        exe = selected_argv[0]
        if os.path.isabs(exe):
            if not os.path.exists(exe):
                findings.append({"severity": "warning", "check": "providers.executable_missing", "message": f"{label} executable {exe!r} not found"})
        elif "/" in exe or "\\" in exe:
            findings.append({"severity": "error", "check": "providers.executable_path", "message": f"{label} argv[0] must be a bare PATH program or absolute path"})
        elif shutil.which(exe) is None:
            where = f" for platform {selected_key}" if selected_key else ""
            findings.append({"severity": "warning", "check": "providers.executable_missing", "message": f"{label} executable {exe!r}{where} not found on PATH"})
    for field in ("capabilities", "requires_env", "env_allowlist"):
        values = agent.get(field, [])
        if values in (None, "") and field == "env_allowlist":
            values = []
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            findings.append({"severity": "error", "check": f"providers.{field}", "message": f"{label} {field} must be a list of strings"})
    for env_name in agent.get("requires_env", []):
        if not ENV_RE.fullmatch(env_name):
            findings.append({"severity": "error", "check": "providers.env_name", "message": f"{label} has invalid env var name {env_name!r}"})
        elif env_name not in os.environ:
            findings.append({"severity": "error", "check": "providers.env_missing", "message": f"{label} requires missing environment variable {env_name}"})
    for env_name in agent.get("env_allowlist", []):
        if not ENV_RE.fullmatch(env_name):
            findings.append({"severity": "error", "check": "providers.env_allowlist_name", "message": f"{label} has invalid env allowlist name {env_name!r}"})
    return findings


def provider_findings(registry):
    findings = []
    if not isinstance(registry, dict):
        return [{"severity": "error", "check": "providers.schema", "message": "provider registry is not a JSON object"}]
    if registry.get("schema") != "m8shift.providers.v1":
        findings.append({"severity": "error", "check": "providers.schema", "message": "expected schema m8shift.providers.v1"})
    agents = registry.get("agents")
    if not isinstance(agents, list):
        return findings + [{"severity": "error", "check": "providers.agents", "message": "agents must be a list"}]
    seen = set()
    for idx, agent in enumerate(agents):
        findings.extend(provider_entry_findings(agent, f"agents[{idx}]", seen))
    examples = registry.get("examples", [])
    if examples in (None, ""):
        examples = []
    if not isinstance(examples, list):
        findings.append({"severity": "error", "check": "providers.examples", "message": "examples must be a list"})
    else:
        for idx, example in enumerate(examples):
            findings.extend(provider_entry_findings(example, f"examples[{idx}]", None))
    return findings


def load_provider_registry():
    return read_json(PROVIDERS, {"schema": "m8shift.providers.v1", "agents": []})


def provider_by_name(name):
    for agent in load_provider_registry().get("agents", []):
        if agent.get("name") == name:
            return agent
    return None


def cmd_runtime_init(args):
    agents = active_roster_or_default(args.agents)
    ensure_project_dirs()
    ensure_runtime_dirs()
    created = []
    if write_text_if_missing(os.path.join(PROJECT_DIR, "README.md"), RUNTIME_README, args.force):
        created.append(".m8shift/README.md")
    for name, text in DEFAULT_ROLES.items():
        if write_text_if_missing(os.path.join(ROLES_DIR, f"{name}.md"), text, args.force):
            created.append(f".m8shift/roles/{name}.md")
    if write_json_if_missing(os.path.join(WORKFLOWS_DIR, "default-code-review.json"), DEFAULT_WORKFLOW, args.force):
        created.append(".m8shift/workflows/default-code-review.json")
    if write_text_if_missing(os.path.join(POLICIES_DIR, "approvals.md"), APPROVALS_POLICY, args.force):
        created.append(".m8shift/policies/approvals.md")
    if write_json_if_missing(PROVIDERS, default_provider_registry(agents), args.force):
        created.append(".m8shift/providers.json")
    if write_json_if_missing(ROUTING_MODELS, default_routing_models_manifest(), args.force):
        created.append(".m8shift/routing/models.json")
    if write_json_if_missing(ROUTING_SKILLS, default_routing_skills_manifest(), args.force):
        created.append(".m8shift/routing/skills.json")
    if write_json_if_missing(PRESENCE, {}, args.force):
        created.append(".m8shift/runtime/presence.json")
    if write_json_if_missing(NOTIFY_CONFIG, default_notify_config(), args.force):
        created.append(".m8shift/runtime/notify.config.json")
    for path, label in (
        (RUNS, ".m8shift/runtime/runs.jsonl"),
        (PROGRESS, ".m8shift/runtime/progress.jsonl"),
        (IDEMPOTENCY, ".m8shift/runtime/idempotency.jsonl"),
        (APPROVALS, ".m8shift/runtime/approvals.jsonl"),
    ):
        if write_text_if_missing(path, "", args.force):
            created.append(label)
    ensure_runtime_gitignore()
    if args.json:
        print(json.dumps({"created": created, "agents": agents, "runtime_version": VERSION}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"✓ runtime companion scaffold ready ({len(created)} file(s) written).")
        for path in created:
            print(f"  {path}")
    return 0


def cmd_providers_init(args):
    agents = active_roster_or_default(args.agents)
    ensure_project_dirs()
    created = write_json_if_missing(PROVIDERS, default_provider_registry(agents), args.force)
    ensure_runtime_gitignore()
    print(("✓ wrote " if created else "✓ kept ") + ".m8shift/providers.json")
    return 0


def cmd_providers_list(args):
    registry = load_provider_registry()
    rows = registry.get("agents", [])
    if args.json:
        print(json.dumps({"agents": rows, "runtime_version": VERSION}, ensure_ascii=False, sort_keys=True))
        return 0
    for row in rows:
        caps = ",".join(row.get("capabilities", [])) or "-"
        print(f"{row.get('name')}  provider={row.get('provider')} mode={row.get('mode')} anchor={row.get('anchor')} caps={caps}")
    return 0


def cmd_providers_show(args):
    agent = parse_agent_csv(args.agent)
    if len(agent) != 1:
        sys.exit("m8shift-runtime: invalid agent")
    row = provider_by_name(agent[0])
    if not row:
        sys.exit(f"m8shift-runtime: no provider entry for {agent[0]}")
    print(json.dumps(row, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def cmd_providers_check(args):
    registry = load_provider_registry()
    findings = provider_findings(registry)
    if args.agent:
        names = parse_agent_csv(args.agent)
        findings = [f for f in findings if not names or any(name in f.get("message", "") for name in names)]
    ok = not any(f["severity"] == "error" for f in findings)
    if args.json:
        print(json.dumps({"ok": ok, "findings": findings, "runtime_version": VERSION}, ensure_ascii=False, sort_keys=True))
    else:
        if not findings:
            print("✓ provider registry OK")
        for f in findings:
            print(f"{f['severity']} {f['check']}: {f['message']}")
    return 0 if ok else 1


def render_provider_argv(row, prompt, run_id=""):
    argv, _platform = select_provider_argv(row)
    return render_argv_template(argv, agent=row.get("name", ""), prompt=prompt, run_id=run_id)


def cmd_providers_render(args):
    names = parse_agent_csv(args.agent)
    row = provider_by_name(names[0]) if names else None
    if not row:
        sys.exit(f"m8shift-runtime: no provider entry for {args.agent}")
    if any(f["severity"] == "error" for f in provider_findings({"schema": "m8shift.providers.v1", "agents": [row]})):
        sys.exit(f"m8shift-runtime: provider entry for {args.agent} is invalid")
    argv_template, platform_key = select_provider_argv(row)
    if not argv_template:
        sys.exit(f"m8shift-runtime: provider entry for {args.agent} has no argv")
    argv = render_provider_argv(row, args.prompt, args.run)
    payload = {
        "agent": row.get("name"),
        "argv": argv,
        "mode": row.get("mode"),
        "provider": row.get("provider"),
        "platform": platform_key or sys.platform,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(argv, ensure_ascii=False))
    return 0


def routing_order(manifest, key, default):
    value = manifest.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        return list(default)
    out = []
    for item in value:
        if item not in out:
            out.append(item)
    return out or list(default)


def order_index(order, value):
    try:
        return order.index(value)
    except ValueError:
        return len(order) + 1000


def order_max(order, left, right):
    return left if order_index(order, left) >= order_index(order, right) else right


def list_strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def load_routing_manifests():
    models, models_err = read_json_diagnostic(ROUTING_MODELS, default_routing_models_manifest())
    skills, skills_err = read_json_diagnostic(ROUTING_SKILLS, default_routing_skills_manifest())
    findings = []
    if models_err:
        findings.append({"severity": "error", "check": "routing.models",
                         "message": f"{os.path.relpath(ROUTING_MODELS, HERE)}: {models_err}"})
    if skills_err:
        findings.append({"severity": "error", "check": "routing.skills",
                         "message": f"{os.path.relpath(ROUTING_SKILLS, HERE)}: {skills_err}"})
    return models, skills, findings


def model_by_id(models_manifest):
    rows = models_manifest.get("models", [])
    if not isinstance(rows, list):
        return {}
    return {row["id"]: row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)}


def resolve_model_ref(value, models_manifest, tiers, *, label):
    if not isinstance(value, str) or not value:
        return "", {"severity": "error", "check": "routing.skill", "message": f"{label} must be a non-empty string"}
    if value in tiers:
        return value, None
    row = model_by_id(models_manifest).get(value)
    if row and row.get("tier") in tiers:
        return row["tier"], None
    return "", {"severity": "error", "check": "routing.model_ref",
                "message": f"{label} references unresolved tier/model {value!r}"}


def routing_model_findings(models_manifest):
    findings = []
    if not isinstance(models_manifest, dict):
        return [{"severity": "error", "check": "routing.models", "message": "models manifest is not an object"}]
    if models_manifest.get("schema") != ROUTING_MODELS_SCHEMA:
        findings.append({"severity": "error", "check": "routing.models.schema", "message": f"expected {ROUTING_MODELS_SCHEMA}"})
    tiers = routing_order(models_manifest, "tiers", DEFAULT_TIER_ORDER)
    costs = routing_order(models_manifest, "cost_bands", DEFAULT_COST_ORDER)
    latencies = routing_order(models_manifest, "latency_bands", DEFAULT_LATENCY_ORDER)
    contexts = routing_order(models_manifest, "context_classes", DEFAULT_CONTEXT_ORDER)
    for key in ("tiers", "cost_bands", "latency_bands", "context_classes"):
        value = models_manifest.get(key, [])
        if value not in (None, "") and not list_strings(value):
            findings.append({"severity": "error", "check": f"routing.models.{key}", "message": f"{key} must be a list of strings"})
    rows = models_manifest.get("models", [])
    if not isinstance(rows, list):
        return findings + [{"severity": "error", "check": "routing.models.models", "message": "models must be a list"}]
    seen = set()
    for idx, row in enumerate(rows):
        prefix = f"models[{idx}]"
        if not isinstance(row, dict):
            findings.append({"severity": "error", "check": "routing.model", "message": f"{prefix} is not an object"})
            continue
        model_id = row.get("id", "")
        if not isinstance(model_id, str) or not ROUTING_ID_RE.fullmatch(model_id):
            findings.append({"severity": "error", "check": "routing.model.id", "message": f"{prefix}.id is invalid"})
        elif model_id in seen:
            findings.append({"severity": "error", "check": "routing.model.id_duplicate", "message": f"duplicate model id {model_id}"})
        else:
            seen.add(model_id)
        if not isinstance(row.get("provider", ""), str):
            findings.append({"severity": "error", "check": "routing.model.provider", "message": f"{prefix}.provider must be a string"})
        if row.get("tier") not in tiers:
            findings.append({"severity": "error", "check": "routing.model.tier", "message": f"{model_id or prefix}: unknown tier {row.get('tier')!r}"})
        if row.get("cost_band") not in costs:
            findings.append({"severity": "error", "check": "routing.model.cost_band", "message": f"{model_id or prefix}: unknown cost_band {row.get('cost_band')!r}"})
        if row.get("latency") not in latencies:
            findings.append({"severity": "error", "check": "routing.model.latency", "message": f"{model_id or prefix}: unknown latency {row.get('latency')!r}"})
        if row.get("context_class") not in contexts:
            findings.append({"severity": "error", "check": "routing.model.context_class", "message": f"{model_id or prefix}: unknown context_class {row.get('context_class')!r}"})
        if not list_strings(row.get("capabilities", [])):
            findings.append({"severity": "error", "check": "routing.model.capabilities", "message": f"{model_id or prefix}: capabilities must be a list of strings"})
    return findings


def routing_skill_findings(skills_manifest, models_manifest):
    findings = []
    if not isinstance(skills_manifest, dict):
        return [{"severity": "error", "check": "routing.skills", "message": "skills manifest is not an object"}]
    if skills_manifest.get("schema") != ROUTING_SKILLS_SCHEMA:
        findings.append({"severity": "error", "check": "routing.skills.schema", "message": f"expected {ROUTING_SKILLS_SCHEMA}"})
    if skills_manifest.get("authority", "advisory") != "advisory":
        findings.append({"severity": "error", "check": "routing.skills.authority", "message": "routing skills authority must be advisory"})
    tiers = routing_order(models_manifest, "tiers", DEFAULT_TIER_ORDER)
    contexts = routing_order(models_manifest, "context_classes", DEFAULT_CONTEXT_ORDER)
    task_types = skills_manifest.get("task_types", {})
    if not isinstance(task_types, dict):
        return findings + [{"severity": "error", "check": "routing.skills.task_types", "message": "task_types must be an object"}]
    defaults = skills_manifest.get("defaults", {})
    if defaults not in ({}, None) and not isinstance(defaults, dict):
        findings.append({"severity": "error", "check": "routing.skills.defaults", "message": "defaults must be an object"})
        defaults = {}
    for task_type, raw_rule in task_types.items():
        if not isinstance(task_type, str) or not ROUTING_ID_RE.fullmatch(task_type):
            findings.append({"severity": "error", "check": "routing.skill.name", "message": f"invalid task-type {task_type!r}"})
            continue
        if not isinstance(raw_rule, dict):
            findings.append({"severity": "error", "check": "routing.skill", "message": f"{task_type}: rule must be an object"})
            continue
        rule = dict(defaults or {})
        rule.update(raw_rule)
        min_tier, finding = resolve_model_ref(rule.get("min_model", ""), models_manifest, tiers, label=f"{task_type}.min_model")
        if finding:
            findings.append(finding)
        optimum_tier, finding = resolve_model_ref(rule.get("optimum_model", rule.get("min_model", "")), models_manifest, tiers, label=f"{task_type}.optimum_model")
        if finding:
            findings.append(finding)
        if not isinstance(rule.get("downgradable", True), bool):
            findings.append({"severity": "error", "check": "routing.skill.downgradable", "message": f"{task_type}: downgradable must be boolean"})
        if not list_strings(rule.get("required_capabilities", [])):
            findings.append({"severity": "error", "check": "routing.skill.capabilities", "message": f"{task_type}: required_capabilities must be a list of strings"})
        if not list_strings(rule.get("verify", [])):
            findings.append({"severity": "error", "check": "routing.skill.verify", "message": f"{task_type}: verify must be a list of strings"})
        required_context = rule.get("required_context_class", "small")
        if required_context not in contexts:
            findings.append({"severity": "error", "check": "routing.skill.context", "message": f"{task_type}: unknown required_context_class {required_context!r}"})
        if task_type in HIGH_STAKES_TASK_TYPES:
            top_tier = tiers[-1] if tiers else "flagship"
            if rule.get("downgradable") is not False or min_tier != top_tier or optimum_tier != top_tier:
                findings.append({"severity": "error", "check": "routing.skill.pinned",
                                 "message": f"{task_type}: high-stakes routes must be pinned to {top_tier} and downgradable=false"})
    return findings


def routing_findings(models_manifest, skills_manifest):
    return routing_model_findings(models_manifest) + routing_skill_findings(skills_manifest, models_manifest)


def context_class_for_tokens(tokens, context_order):
    if tokens is None or tokens <= 0:
        return context_order[0] if context_order else "small"
    if "small" in context_order and tokens <= 8000:
        return "small"
    if "large" in context_order and tokens <= 64000:
        return "large"
    if "xlarge" in context_order:
        return "xlarge"
    return context_order[-1] if context_order else "xlarge"


def current_holder():
    try:
        status = run_core_json("status", "--json")
    except Exception:  # noqa: BLE001 - routing fail-safe must not traceback
        return ""
    holder = status.get("holder", "")
    return holder if isinstance(holder, str) and AGENT_RE.fullmatch(holder) else ""


def provider_self_model(holder):
    if not holder:
        return "", ""
    registry = load_provider_registry()
    matches = []
    for row in registry.get("agents", []):
        if isinstance(row, dict) and row.get("name") == holder:
            model = row.get("model_id") or row.get("model")
            if isinstance(model, str) and model:
                matches.append(model)
    unique = sorted(set(matches))
    return (unique[0], "provider") if len(unique) == 1 else ("", "")


def resolve_self_model(args, holder):
    presence, _err = read_json_diagnostic(PRESENCE, {})
    if holder and isinstance(presence.get(holder), dict):
        row = presence[holder]
        model = row.get("agent_model") or row.get("model") or row.get("Agent-Model")
        verified = (
            row.get("agent_model_verified") is True
            or row.get("verified_agent_model") is True
            or row.get("agent_model_source") == "Agent-Model"
        )
        if isinstance(model, str) and model and verified:
            return model, "runtime-lane"
    if getattr(args, "self_model", ""):
        return args.self_model, "operator"
    return provider_self_model(holder)


def fail_safe_recommendation(args, reason, findings, *, floor="", optimum="", verify=None):
    holder = current_holder()
    self_model, self_source = resolve_self_model(args, holder)
    if not self_model:
        reason = "no delegation recommendation; use the pen-holder manually"
    return {
        "ok": True,
        "route": "recommend",
        "authority": "advisory",
        "launch": False,
        "task_type": args.task_type,
        "skill": args.skill,
        "holder": holder,
        "floor": floor,
        "optimum": optimum,
        "required_capabilities": [],
        "required_context_class": "",
        "feasible": [],
        "picked": self_model,
        "picked_tier": "",
        "picked_cost_band": "",
        "reason": reason,
        "self_model": self_model,
        "self_source": self_source,
        "saved_vs": "",
        "verify": verify or [],
        "findings": findings,
    }


def route_recommendation(args):
    models_manifest, skills_manifest, findings = load_routing_manifests()
    findings.extend(routing_findings(models_manifest, skills_manifest))
    if any(f.get("severity") == "error" for f in findings):
        return {"ok": False, "route": "recommend", "authority": "advisory", "launch": False,
                "task_type": args.task_type, "skill": args.skill,
                "reason": "routing manifest error", "findings": findings}
    tiers = routing_order(models_manifest, "tiers", DEFAULT_TIER_ORDER)
    costs = routing_order(models_manifest, "cost_bands", DEFAULT_COST_ORDER)
    latencies = routing_order(models_manifest, "latency_bands", DEFAULT_LATENCY_ORDER)
    contexts = routing_order(models_manifest, "context_classes", DEFAULT_CONTEXT_ORDER)
    task_types = skills_manifest.get("task_types", {}) if isinstance(skills_manifest.get("task_types", {}), dict) else {}
    if args.task_type not in task_types:
        return fail_safe_recommendation(args, f"unknown task-type {args.task_type!r}; fail-safe to pen-holder", findings)
    defaults = skills_manifest.get("defaults", {}) if isinstance(skills_manifest.get("defaults", {}), dict) else {}
    rule = dict(defaults)
    rule.update(task_types[args.task_type])
    floor, finding = resolve_model_ref(rule.get("min_model", ""), models_manifest, tiers, label=f"{args.task_type}.min_model")
    if finding:
        findings.append(finding)
    optimum, finding = resolve_model_ref(rule.get("optimum_model", rule.get("min_model", "")), models_manifest, tiers, label=f"{args.task_type}.optimum_model")
    if finding:
        findings.append(finding)
    if any(f.get("severity") == "error" for f in findings):
        return {"ok": False, "route": "recommend", "authority": "advisory", "launch": False,
                "task_type": args.task_type, "skill": args.skill,
                "reason": "routing manifest error", "findings": findings}
    required_caps = rule.get("required_capabilities", [])
    required_context = rule.get("required_context_class", contexts[0] if contexts else "small")
    required_context = order_max(contexts, required_context, context_class_for_tokens(args.input_tokens, contexts))
    verify = rule.get("verify", [])
    eligible = []
    for row in [r for r in models_manifest.get("models", []) if isinstance(r, dict)]:
        if order_index(tiers, row.get("tier")) < order_index(tiers, floor):
            continue
        if not set(required_caps).issubset(set(row.get("capabilities", []))):
            continue
        if order_index(contexts, row.get("context_class")) < order_index(contexts, required_context):
            continue
        eligible.append(row)
    sort_key = lambda r: (order_index(costs, r.get("cost_band")), order_index(latencies, r.get("latency")), r.get("id", ""))
    feasible_rows = sorted(eligible, key=sort_key)
    feasible = [{
        "id": row.get("id"),
        "tier": row.get("tier"),
        "cost_band": row.get("cost_band"),
        "latency": row.get("latency"),
        "context_class": row.get("context_class"),
    } for row in feasible_rows]
    if not feasible_rows:
        return fail_safe_recommendation(
            args,
            "no eligible model clears floor/capabilities/context; fail-safe to pen-holder",
            findings,
            floor=floor,
            optimum=optimum,
            verify=verify,
        )
    picked = feasible_rows[0]
    optimum_candidates = [row for row in feasible_rows if order_index(tiers, row.get("tier")) >= order_index(tiers, optimum)]
    saved_vs = ""
    if optimum_candidates and optimum_candidates[0].get("id") != picked.get("id"):
        saved_vs = optimum_candidates[0].get("id", "")
    return {
        "ok": True,
        "route": "recommend",
        "authority": "advisory",
        "launch": False,
        "task_type": args.task_type,
        "skill": args.skill,
        "holder": current_holder(),
        "floor": floor,
        "optimum": optimum,
        "downgradable": bool(rule.get("downgradable", True)),
        "required_capabilities": required_caps,
        "required_context_class": required_context,
        "feasible": feasible,
        "picked": picked.get("id", ""),
        "picked_tier": picked.get("tier", ""),
        "picked_cost_band": picked.get("cost_band", ""),
        "picked_latency": picked.get("latency", ""),
        "below_optimum": order_index(tiers, picked.get("tier")) < order_index(tiers, optimum),
        "reason": "cheapest eligible model; latency tie-break",
        "saved_vs": saved_vs,
        "verify": verify,
        "findings": findings,
    }


def cmd_route_recommend(args):
    result = route_recommendation(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"m8shift-runtime.py v{VERSION}")
        print("── route recommendation ───────────────")
        print(f"authority: {result.get('authority')}")
        print(f"task_type: {result.get('task_type')}")
        print(f"floor: {result.get('floor', '-') or '-'}")
        print(f"optimum: {result.get('optimum', '-') or '-'}")
        print(f"picked: {result.get('picked', '-') or '-'}")
        print(f"reason: {result.get('reason', '-')}")
        verify = ", ".join(result.get("verify") or []) or "-"
        print(f"verify: {verify}")
        for finding in result.get("findings", []):
            print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0 if result.get("ok") else 1


def list_named_files(directory, suffix):
    if not os.path.isdir(directory):
        return []
    return sorted(name[:-len(suffix)] for name in os.listdir(directory) if name.endswith(suffix))


def cmd_roles_list(args):
    roles = list_named_files(ROLES_DIR, ".md")
    print(json.dumps({"roles": roles}, ensure_ascii=False, sort_keys=True) if args.json else "\n".join(roles))
    return 0


def cmd_roles_show(args):
    name = args.name.strip()
    if not AGENT_RE.fullmatch(name):
        sys.exit("m8shift-runtime: invalid role name")
    path = os.path.join(ROLES_DIR, f"{name}.md")
    if not os.path.exists(path):
        sys.exit(f"m8shift-runtime: role {name!r} not found")
    print(read_text(path))
    return 0


def cmd_workflows_list(args):
    workflows = list_named_files(WORKFLOWS_DIR, ".json")
    print(json.dumps({"workflows": workflows}, ensure_ascii=False, sort_keys=True) if args.json else "\n".join(workflows))
    return 0


def cmd_workflows_show(args):
    name = args.name.strip()
    if not AGENT_RE.fullmatch(name):
        sys.exit("m8shift-runtime: invalid workflow name")
    path = os.path.join(WORKFLOWS_DIR, f"{name}.json")
    if not os.path.exists(path):
        sys.exit(f"m8shift-runtime: workflow {name!r} not found")
    print(json.dumps(read_json(path, {}), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def cmd_approve(args):
    by = args.by.strip().lower()
    if not AGENT_RE.fullmatch(by):
        sys.exit("m8shift-runtime: invalid --by agent/operator name")
    run_id = validate_run_id(args.run)
    gate_id = validate_run_id(args.gate)
    payload = {
        "gate_id": gate_id,
        "by": by,
        "decision": args.decision,
        "reason": args.reason,
    }
    row = runtime_event("approval", run_id=run_id, payload=payload, **payload)
    append_jsonl(APPROVALS, row)
    print(f"✓ approval recorded for {run_id}/{gate_id}: {args.decision}")
    return 0


def cmd_report(args):
    run_id = validate_run_id(args.run)
    findings = []

    def rows_for(path):
        rows, err = read_jsonl_diagnostic(path)
        if err:
            findings.append({"severity": "warning", "check": "runtime.jsonl", "message": err})
            return []
        return [row for row in rows if row.get("run_id") == run_id]

    events = rows_for(RUNS)
    progress = rows_for(PROGRESS)
    approvals = rows_for(APPROVALS)
    payload = {
        "run_id": run_id,
        "events": events,
        "progress": progress,
        "approvals": approvals,
        "runtime_findings": findings,
        "runtime_version": VERSION,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    lines = [
        f"# M8Shift run report — {run_id}",
        "",
        f"- events: {len(events)}",
        f"- progress notes: {len(progress)}",
        f"- approvals: {len(approvals)}",
        "",
    ]
    for finding in findings:
        lines.append(f"- warning `{finding.get('check')}`: {finding.get('message')}")
    for row in events:
        lines.append(f"- event `{row.get('event', row.get('type', '?'))}` at {row.get('ts', '-')}: {row.get('status', row.get('relay_state', ''))}")
    for row in progress:
        lines.append(f"- progress at {row.get('ts', '-')}: {row.get('message', '')}")
    for row in approvals:
        lines.append(f"- approval `{row.get('gate_id')}` by {row.get('by')}: {row.get('decision')} — {row.get('reason', '')}")
    report = "\n".join(lines).rstrip() + "\n"
    if args.write:
        out_dir = os.path.join(RUN_REPORTS_DIR, run_id)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(path)
    else:
        print(report, end="")
    return 0


def runtime_ledger_paths():
    paths = [RUNS, PROGRESS, IDEMPOTENCY, APPROVALS]
    if os.path.exists(NOTIFY_LOG):
        paths.append(NOTIFY_LOG)
    if os.path.isdir(INBOX_DIR):
        for name in sorted(os.listdir(INBOX_DIR)):
            if name.endswith(".jsonl"):
                paths.append(os.path.join(INBOX_DIR, name))
    return paths


def default_retention_policy():
    return {
        "schema": RETENTION_SCHEMA,
        "enabled": False,
        "default": {"strategy": "fixed-count", "keep": 1000, "archive": True},
        "ledgers": {},
    }


def load_retention_policy():
    if not os.path.exists(RETENTION_POLICY):
        return default_retention_policy(), [], "absent"
    policy, err = read_json_diagnostic(RETENTION_POLICY, {})
    if err:
        return default_retention_policy(), [{
            "severity": "error",
            "check": "runtime.retention_policy",
            "message": f"{os.path.relpath(RETENTION_POLICY, HERE)}: {err}",
        }], "malformed"
    findings = []
    if policy.get("schema") and policy.get("schema") != RETENTION_SCHEMA:
        findings.append({
            "severity": "warning",
            "check": "runtime.retention_policy",
            "message": f"unexpected retention schema {policy.get('schema')!r}",
        })
    effective = default_retention_policy()
    effective.update({k: v for k, v in policy.items() if k in {"schema", "enabled", "default", "ledgers"}})
    if not isinstance(effective.get("default"), dict):
        effective["default"] = default_retention_policy()["default"]
        findings.append({
            "severity": "error",
            "check": "runtime.retention_policy",
            "message": "retention default must be an object",
        })
    if not isinstance(effective.get("ledgers"), dict):
        effective["ledgers"] = {}
        findings.append({
            "severity": "error",
            "check": "runtime.retention_policy",
            "message": "retention ledgers must be an object",
        })
    return effective, findings, "configured"


def archive_path_for(path):
    rel = os.path.relpath(path, RUNTIME_DIR).replace(os.sep, "--")
    return os.path.join(RUNTIME_DIR, "archive", rel)


def prune_runtime_ledger(path, keep, archive=True):
    label = os.path.relpath(path, HERE)
    rows, err = read_jsonl_diagnostic(path)
    if err:
        return {
            "path": label,
            "before": None,
            "after": None,
            "pruned": 0,
            "archived_to": "",
            "finding": {"severity": "warning", "check": "runtime.jsonl", "message": err},
        }
    before = len(rows)
    if before <= keep:
        return {"path": label, "before": before, "after": before, "pruned": 0, "archived_to": ""}
    cut = before - keep
    pruned = rows[:cut]
    kept = rows[cut:]
    archived_to = ""
    if archive and pruned:
        archive_path = archive_path_for(path)
        append_jsonl_rows(archive_path, pruned)
        archived_to = os.path.relpath(archive_path, HERE)
    atomic_write_jsonl(path, kept)
    return {"path": label, "before": before, "after": len(kept), "pruned": len(pruned), "archived_to": archived_to}


def cmd_retention_prune(args):
    if args.keep < 0:
        sys.exit("m8shift-runtime: --keep must be >= 0")
    ensure_runtime_dirs()
    findings = []
    ledgers = []
    for path in runtime_ledger_paths():
        result = prune_runtime_ledger(path, args.keep, archive=not args.no_archive)
        finding = result.pop("finding", None)
        if finding:
            findings.append(finding)
        ledgers.append(result)
    payload = {
        "ok": not any(f["severity"] == "error" for f in findings),
        "keep": args.keep,
        "archive": not args.no_archive,
        "ledgers": ledgers,
        "findings": findings,
        "runtime_version": VERSION,
        "policy": "basic_fixed_count",
        "future_policy_rfc": "docs/en/rfc/026-rfc-sidecar-retention.md",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"m8shift-runtime.py v{VERSION}")
    print("── runtime retention prune ─────────────")
    for row in ledgers:
        print(f"{row['path']}: {row['before']} → {row['after']} (pruned {row['pruned']})")
        if row.get("archived_to"):
            print(f"  archived: {row['archived_to']}")
    for finding in findings:
        print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0 if payload["ok"] else 1


def normalize_retention_rule(rule, *, source):
    if not isinstance(rule, dict):
        return None, {
            "severity": "error",
            "check": "runtime.retention_policy",
            "message": f"{source}: rule must be an object",
        }
    strategy = rule.get("strategy", "fixed-count")
    if strategy not in {"fixed-count", "age", "combined"}:
        return None, {
            "severity": "error",
            "check": "runtime.retention_policy",
            "message": f"{source}: unsupported strategy {strategy!r}",
        }
    out = {"strategy": strategy, "archive": bool(rule.get("archive", True))}
    if strategy in {"fixed-count", "combined"}:
        keep = rule.get("keep")
        if not isinstance(keep, int) or keep < 0:
            return None, {
                "severity": "error",
                "check": "runtime.retention_policy",
                "message": f"{source}: keep must be a non-negative integer",
            }
        out["keep"] = keep
    if strategy in {"age", "combined"}:
        max_age_days = rule.get("max_age_days")
        if not isinstance(max_age_days, (int, float)) or max_age_days < 0:
            return None, {
                "severity": "error",
                "check": "runtime.retention_policy",
                "message": f"{source}: max_age_days must be a non-negative number",
            }
        out["max_age_days"] = float(max_age_days)
    return out, None


def retention_rules_for_existing_ledgers(policy):
    paths = [path for path in runtime_ledger_paths() if os.path.exists(path)]
    rules = {}
    findings = []
    default_rule, finding = normalize_retention_rule(policy.get("default", {}), source="default")
    if finding:
        findings.append(finding)
    if default_rule:
        for path in paths:
            rules[path] = default_rule
    for pattern, raw_rule in policy.get("ledgers", {}).items():
        normalized_pattern = pattern.replace("\\", "/") if isinstance(pattern, str) else pattern
        if not isinstance(pattern, str) or pattern.startswith(("/", "\\")) or ".." in normalized_pattern.split("/"):
            findings.append({
                "severity": "error",
                "check": "runtime.retention_policy",
                "message": f"unsafe ledger pattern {pattern!r}",
            })
            continue
        rule, finding = normalize_retention_rule(raw_rule, source=f"ledgers.{pattern}")
        if finding:
            findings.append(finding)
            continue
        matched = False
        for path in paths:
            rel = os.path.relpath(path, RUNTIME_DIR).replace(os.sep, "/")
            if fnmatch.fnmatch(rel, pattern):
                rules[path] = rule
                matched = True
        if not matched:
            findings.append({
                "severity": "info",
                "check": "runtime.retention_policy",
                "message": f"ledger pattern {pattern!r} matched no existing JSONL ledger",
            })
    return rules, findings


def retention_row_ts(row):
    return parse_utc(row.get("ts", ""))


def ts_bounds(rows):
    dates = [retention_row_ts(row) for row in rows]
    dates = [value for value in dates if value is not None]
    if not dates:
        return "", ""
    return iso_from_dt(min(dates)), iso_from_dt(max(dates))


def split_rows_by_retention(rows, rule, *, label):
    strategy = rule["strategy"]
    keep_indices = set()
    findings = []
    if strategy in {"fixed-count", "combined"}:
        keep = rule.get("keep", 0)
        if keep:
            keep_indices.update(range(max(0, len(rows) - keep), len(rows)))
    if strategy in {"age", "combined"}:
        cutoff = now() - dt.timedelta(days=rule["max_age_days"])
        undated = 0
        for idx, row in enumerate(rows):
            row_ts = retention_row_ts(row)
            if row_ts is None:
                keep_indices.add(idx)
                undated += 1
            elif row_ts >= cutoff:
                keep_indices.add(idx)
        if undated:
            findings.append({
                "severity": "warning",
                "check": "runtime.retention_undated",
                "message": f"{label}: kept {undated} row(s) with missing or unparseable ts",
            })
    if strategy == "fixed-count":
        kept = rows[-rule["keep"]:] if rule["keep"] else []
        pruned = rows[:max(0, len(rows) - rule["keep"])] if rule["keep"] else list(rows)
        return kept, pruned, findings
    kept = []
    pruned = []
    for idx, row in enumerate(rows):
        (kept if idx in keep_indices else pruned).append(row)
    return kept, pruned, findings


def apply_retention_to_ledger(path, rule, *, dry_run=False, no_archive=False):
    label = os.path.relpath(path, RUNTIME_DIR).replace(os.sep, "/")
    rows, err = read_jsonl_diagnostic(path)
    if err:
        return {
            "ledger": label,
            "path": os.path.relpath(path, HERE),
            "strategy": rule["strategy"],
            "before": None,
            "after": None,
            "kept": None,
            "pruned": 0,
            "archive": bool(rule.get("archive", True)) and not no_archive,
            "archived_to": "",
            "dry_run": dry_run,
            "finding": {"severity": "warning", "check": "runtime.jsonl", "message": err},
        }
    kept, pruned, findings = split_rows_by_retention(rows, rule, label=label)
    archive_enabled = bool(rule.get("archive", True)) and not no_archive
    archived_to = ""
    if pruned and not dry_run:
        if archive_enabled:
            archive_path = archive_path_for(path)
            append_jsonl_rows(archive_path, pruned)
            archived_to = os.path.relpath(archive_path, HERE)
            oldest_ts, newest_ts = ts_bounds(pruned)
            append_jsonl(RETENTION_ARCHIVE_INDEX, {
                "ledger": label,
                "strategy": rule["strategy"],
                "pruned": len(pruned),
                "kept": len(kept),
                "oldest_ts": oldest_ts,
                "newest_ts": newest_ts,
                "archived_at": iso(),
            })
        atomic_write_jsonl(path, kept)
    if pruned and dry_run and archive_enabled:
        archived_to = os.path.relpath(archive_path_for(path), HERE)
    result = {
        "ledger": label,
        "path": os.path.relpath(path, HERE),
        "strategy": rule["strategy"],
        "before": len(rows),
        "after": len(kept),
        "kept": len(kept),
        "pruned": len(pruned),
        "archive": archive_enabled,
        "archived_to": archived_to,
        "dry_run": dry_run,
    }
    if findings:
        result["findings"] = findings
    return result


def cmd_retention_policy_show(args):
    policy, findings, source = load_retention_policy()
    payload = {
        "ok": not any(f["severity"] == "error" for f in findings),
        "policy_path": os.path.relpath(RETENTION_POLICY, HERE),
        "source": source,
        "policy": policy,
        "runtime_version": VERSION,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["ok"] else 1
    print(f"m8shift-runtime.py v{VERSION}")
    print("── runtime retention policy ───────────")
    print(f"path: {payload['policy_path']}")
    print(f"source: {source}")
    print(f"enabled: {bool(policy.get('enabled'))}")
    print(json.dumps(policy, ensure_ascii=False, sort_keys=True, indent=2))
    for finding in findings:
        print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0 if payload["ok"] else 1


def cmd_retention_apply(args):
    ensure_runtime_dirs()
    policy, findings, source = load_retention_policy()
    ledgers = []
    if source == "absent":
        findings.append({
            "severity": "info",
            "check": "runtime.retention_policy",
            "message": f"{os.path.relpath(RETENTION_POLICY, HERE)} absent; retention apply is a no-op",
        })
    elif not any(f["severity"] == "error" for f in findings) and not bool(policy.get("enabled")):
        findings.append({
            "severity": "info",
            "check": "runtime.retention_policy",
            "message": "retention policy disabled; retention apply is a no-op",
        })
    if source != "absent" and bool(policy.get("enabled")) and not any(f["severity"] == "error" for f in findings):
        rules, rule_findings = retention_rules_for_existing_ledgers(policy)
        findings.extend(rule_findings)
        if not any(f["severity"] == "error" for f in findings):
            for path in sorted(rules):
                result = apply_retention_to_ledger(
                    path, rules[path], dry_run=args.dry_run, no_archive=args.no_archive,
                )
                finding = result.pop("finding", None)
                if finding:
                    findings.append(finding)
                findings.extend(result.pop("findings", []))
                ledgers.append(result)
    ok = not any(f["severity"] == "error" for f in findings)
    payload = {
        "ok": ok,
        "policy": "runtime_retention_v1",
        "policy_path": os.path.relpath(RETENTION_POLICY, HERE),
        "source": source,
        "enabled": bool(policy.get("enabled")) if source != "absent" else False,
        "dry_run": args.dry_run,
        "archive": not args.no_archive,
        "ledgers": ledgers,
        "findings": findings,
        "runtime_version": VERSION,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if ok else 1
    print(f"m8shift-runtime.py v{VERSION}")
    print("── runtime retention apply ────────────")
    if not ledgers:
        print("no-op: no ledgers pruned.")
    for row in ledgers:
        print(f"{row['ledger']}: {row['before']} → {row['after']} (pruned {row['pruned']}, strategy {row['strategy']})")
        if row.get("archived_to"):
            print(f"  archived: {row['archived_to']}")
    for finding in findings:
        print(f"{finding['severity']} {finding['check']}: {finding['message']}")
    return 0 if ok else 1


def runtime_summary(agent=""):
    findings = []
    presence, err = read_json_diagnostic(PRESENCE, {})
    if err:
        findings.append({"severity": "warning", "check": "runtime.json", "message": f"{os.path.relpath(PRESENCE, HERE)}: {err}"})
    progress, err = read_jsonl_diagnostic(PROGRESS)
    if err:
        findings.append({"severity": "warning", "check": "runtime.jsonl", "message": err})
    runs, err = read_jsonl_diagnostic(RUNS)
    if err:
        findings.append({"severity": "warning", "check": "runtime.jsonl", "message": err})
    if agent:
        agents = [agent]
    else:
        discovered = set(presence)
        discovered.update(row.get("agent") for row in progress if row.get("agent"))
        discovered.update(row.get("agent") for row in runs if row.get("agent"))
        if os.path.isdir(INBOX_DIR):
            for name in os.listdir(INBOX_DIR):
                if name.endswith(".jsonl"):
                    discovered.add(name[:-6])
        agents = sorted(ag for ag in discovered if AGENT_RE.fullmatch(ag))
    out = {}
    for ag in agents:
        inbox_path = os.path.join(INBOX_DIR, f"{ag}.jsonl")
        inbox, err = read_jsonl_diagnostic(inbox_path)
        if err:
            findings.append({"severity": "warning", "check": "runtime.inbox", "message": err})
        last_progress = next((row for row in reversed(progress) if row.get("agent") == ag), None)
        last_run_event = next((row for row in reversed(runs) if row.get("agent") == ag), None)
        pres = presence.get(ag)
        if isinstance(pres, dict):
            finding = no_progress_finding(ag, pres)
            if finding:
                findings.append(finding)
        out[ag] = {
            "presence": pres,
            "presence_stale": isinstance(pres, dict) and not fresh_presence(pres, pres.get("stale_after_seconds", 300)),
            "inbox_count": len(inbox),
            "last_progress": last_progress,
            "last_run_event": last_run_event,
        }
    return out, findings


def cmd_status_runtime(args):
    core = load_core()
    agent = validate_agent(core, args.agent) if args.agent else ""
    status = run_core_json("status", "--json")
    summary, findings = runtime_summary(agent)
    headroom = compute_headroom(agent)
    finding = headroom_finding(headroom)
    if finding:
        findings.append(finding)
    findings.extend(headroom.get("runtime_findings", []))
    context_rtk = context_rtk_status()
    findings.extend(context_rtk.get("findings", []))
    if args.json:
        print(json.dumps({
            "m8shift_version": status.get("m8shift_version"),
            "runtime_version": VERSION,
            "relay": status,
            "runtime": summary,
            "headroom": headroom,
            "context_rtk": context_rtk,
            "runtime_findings": findings,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"m8shift-runtime.py v{VERSION}")
    print(f"relay: {status.get('state')} holder={status.get('holder')} turn={status.get('turn')}")
    reasons = "; ".join(headroom.get("reasons") or ["-"])
    print(f"headroom: {headroom.get('status')} — {reasons}")
    print(context_rtk.get("label", "RTK: OFF (native)"))
    if context_rtk.get("last_pack"):
        last = context_rtk["last_pack"]
        print(
            "  last pack: "
            f"{last.get('pack_id') or '-'} ratio={last.get('compression_ratio')} "
            f"proxy={last.get('estimated_proxy_tokens_before')}→{last.get('estimated_proxy_tokens_after')}"
        )
    if not args.brief:
        print(f"  next: {headroom.get('next')}")
    for ag, data in summary.items():
        pres = data.get("presence") or {}
        print(
            f"{ag}: presence={pres.get('state', '-')} session={pres.get('session_id', '-')} "
            f"inbox={data.get('inbox_count', 0)} RTK={presence_rtk_label(pres)}"
        )
        if not args.brief and data.get("last_progress"):
            print(f"  last progress: {data['last_progress'].get('message')} ({data['last_progress'].get('ts')})")
        if not args.brief and data.get("last_run_event"):
            row = data["last_run_event"]
            print(f"  last run: {row.get('event', row.get('type', '-'))} {row.get('run_id', '')} ({row.get('ts', '-')})")
    return 0


def cmd_headroom(args):
    if args.pause_on and not args.agent:
        sys.exit("m8shift-runtime: headroom --pause-on requires an agent")
    if args.pause_on and not args.reason.strip():
        sys.exit("m8shift-runtime: headroom --pause-on requires --reason")
    if args.window_status and args.window_status not in HEADROOM_LEVEL:
        sys.exit("m8shift-runtime: invalid --window-status")
    for name in (
        "warn_after_turns_since_checkpoint",
        "warn_after_handoff_body_bytes",
        "warn_after_relay_bytes",
        "pause_recommendation_after_turns_since_checkpoint",
        "pause_recommendation_after_relay_bytes",
    ):
        if getattr(args, name) < 0:
            sys.exit("m8shift-runtime: headroom thresholds must be >= 0")
    headroom = compute_headroom(
        args.agent,
        warn_turns=args.warn_after_turns_since_checkpoint,
        warn_body_bytes=args.warn_after_handoff_body_bytes,
        warn_relay_bytes=args.warn_after_relay_bytes,
        high_turns=args.pause_recommendation_after_turns_since_checkpoint,
        high_relay_bytes=args.pause_recommendation_after_relay_bytes,
        harness_status=args.window_status,
        harness_reason=args.window_reason,
    )
    headroom["checkpoint_written"] = ""
    headroom["paused"] = False
    should_checkpoint = args.checkpoint
    should_pause = bool(args.pause_on and HEADROOM_LEVEL[headroom["status"]] >= HEADROOM_LEVEL[args.pause_on])
    if should_pause:
        core = load_core()
        text, lk = load_status(core)
        validate_agent(core, args.agent)
        if lk.get("holder") != args.agent or lk.get("state") in {"DONE", "PAUSED"}:
            sys.exit(
                f"m8shift-runtime: cannot pause as {args.agent}; "
                f"state={lk.get('state')} holder={lk.get('holder')}"
            )
        should_checkpoint = True
    if should_checkpoint:
        try:
            headroom["checkpoint_written"] = write_headroom_checkpoint(
                args.agent or headroom.get("relay", {}).get("holder", ""),
                headroom,
                args.reason or "headroom checkpoint",
            )
        except RuntimeError as e:
            sys.exit(f"m8shift-runtime: checkpoint failed: {e}")
    if should_pause:
        result = subprocess.run(
            [sys.executable, CORE_PATH, "pause", args.agent, "--reason", args.reason],
            cwd=HERE,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit((result.stderr or result.stdout).strip())
        headroom["paused"] = True
        headroom["pause_output"] = (result.stdout or "").strip()
    elif args.pause_on:
        headroom["pause_skipped"] = f"headroom={headroom['status']} below {args.pause_on}"

    if args.json:
        print(json.dumps(headroom, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"m8shift-runtime.py v{VERSION}")
    print("── headroom ───────────────────────────")
    print(f"status: {headroom['status']}")
    print(f"reasons: {'; '.join(headroom.get('reasons') or ['-'])}")
    print(f"next: {headroom['next']}")
    metrics = headroom["metrics"]
    print(
        f"metrics: turns_since_checkpoint={metrics['turns_since_checkpoint']} "
        f"relay_bytes={metrics['relay_bytes']} "
        f"max_body_bytes={metrics['max_handoff_body_bytes']}"
    )
    if headroom.get("checkpoint_written"):
        print(f"checkpoint: {headroom['checkpoint_written']}")
    if headroom.get("paused"):
        print("paused: yes")
    elif headroom.get("pause_skipped"):
        print(headroom["pause_skipped"])
    return 0


def gitignored_runtime():
    path = os.path.join(HERE, ".gitignore")
    try:
        with open(path, encoding="utf-8") as fh:
            return any(line.strip() in {".m8shift/", ".m8shift/runtime/"} for line in fh)
    except OSError:
        return False


def ensure_runtime_gitignore():
    path = os.path.join(HERE, ".gitignore")
    wanted = [".m8shift/runtime/", ".m8shift/runs/", ".m8shift/cache/", ".m8shift/tmp/"]
    try:
        text = read_text(path)
    except OSError:
        text = ""
    lines = text.splitlines()
    existing = {line.strip() for line in lines}
    added = False
    for line in wanted:
        if line not in existing and ".m8shift/" not in existing:
            lines.append(line)
            added = True
    if added:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
    return added


def cmd_doctor(args):
    findings = []
    core = load_core()
    try:
        run_core_json("status", "--json")
    except Exception as e:  # noqa: BLE001 - report as diagnostic, do not traceback
        findings.append({"severity": "error", "check": "core.status", "message": str(e)})
    if os.path.isdir(RUNTIME_DIR) and not gitignored_runtime():
        findings.append({
            "severity": "warning",
            "check": "runtime.gitignore",
            "message": ".m8shift/runtime exists but .m8shift/ is not gitignored",
        })
    notify_config, notify_findings = load_notify_config()
    findings.extend(notify_findings)
    if "os" in notify_config.get("tiers", []):
        argv, exe = os_notify_argv(notify_config.get("os_preset", "auto"), "turn-ready", "test")
        if argv and ((os.path.isabs(argv[0]) and not os.path.exists(argv[0]))
                     or (not os.path.isabs(argv[0]) and shutil.which(argv[0]) is None)):
            findings.append({
                "severity": "warning",
                "check": "runtime.notify_os",
                "message": f"OS notifier {exe or argv[0]!r} is enabled but not found on PATH",
            })
    presence, err = read_json_diagnostic(PRESENCE, {})
    if err:
        findings.append({"severity": "warning", "check": "runtime.json", "message": f"{os.path.relpath(PRESENCE, HERE)}: {err}"})
    for path in (RUNS, PROGRESS, IDEMPOTENCY, APPROVALS):
        rows, err = read_jsonl_diagnostic(path)
        if err:
            findings.append({"severity": "warning", "check": "runtime.jsonl", "message": err})
            continue
        if any(row.get("schema") != RUNTIME_EVENT_SCHEMA for row in rows):
            findings.append({
                "severity": "warning",
                "check": "runtime.event_schema",
                "message": f"{os.path.relpath(path, HERE)} has an event without schema {RUNTIME_EVENT_SCHEMA}",
            })
    if os.path.isdir(INBOX_DIR):
        for name in os.listdir(INBOX_DIR):
            if name.endswith(".jsonl"):
                rows, err = read_jsonl_diagnostic(os.path.join(INBOX_DIR, name))
                if err:
                    findings.append({"severity": "warning", "check": "runtime.inbox", "message": err})
                    continue
                if any(row.get("schema") != RUNTIME_EVENT_SCHEMA for row in rows):
                    findings.append({
                        "severity": "warning",
                        "check": "runtime.event_schema",
                        "message": f".m8shift/runtime/inbox/{name} has an event without schema {RUNTIME_EVENT_SCHEMA}",
                    })
    for agent, row in presence.items():
        if isinstance(row, dict) and not fresh_presence(row, args.stale_after):
            findings.append({
                "severity": "info",
                "check": "runtime.presence_stale",
                "message": f"{agent} runtime presence is stale",
            })
        if isinstance(row, dict):
            finding = no_progress_finding(agent, row)
            if finding:
                findings.append(finding)
    try:
        headroom = compute_headroom()
        finding = headroom_finding(headroom)
        if finding:
            findings.append(finding)
        findings.extend(headroom.get("runtime_findings", []))
    except Exception as e:  # noqa: BLE001 - runtime diagnostics must not traceback
        findings.append({"severity": "warning", "check": "runtime.headroom", "message": str(e)})
    try:
        findings.extend(context_rtk_status().get("findings", []))
    except Exception as e:  # noqa: BLE001 - runtime diagnostics must not traceback
        findings.append({"severity": "warning", "check": "runtime.context_rtk", "message": str(e)})
    if os.path.exists(PROVIDERS):
        findings.extend(provider_findings(load_provider_registry()))
    if os.path.exists(ROUTING_MODELS) or os.path.exists(ROUTING_SKILLS):
        models_manifest, skills_manifest, route_findings = load_routing_manifests()
        findings.extend(route_findings)
        findings.extend(routing_findings(models_manifest, skills_manifest))
    try:
        findings.extend(listener_doctor_findings())
    except Exception as e:  # noqa: BLE001 - runtime diagnostics must not traceback
        findings.append({"severity": "warning", "check": "runtime.listener", "message": str(e)})
    try:
        findings.extend(usage_doctor_findings())
    except Exception as e:  # noqa: BLE001 - runtime diagnostics must not traceback
        findings.append({"severity": "warning", "check": "runtime.usage", "message": str(e)})
    ok = not any(f["severity"] == "error" for f in findings)
    if args.json:
        print(json.dumps({
            "ok": ok,
            "runtime_version": VERSION,
            "findings": findings,
        }, ensure_ascii=False, sort_keys=True))
        return 0 if ok else 1
    print(f"m8shift-runtime.py v{VERSION}")
    print("── runtime doctor ─────────────────────")
    if not findings:
        print("✓ no findings.")
    else:
        for f in findings:
            print(f"{f['severity']} {f['check']}: {f['message']}")
    return 0 if ok else 1


# ── RFC 047 — listener lifecycle companion (Phases B–E, all backends) ──
#
# Advisory charter (never negotiable): the listener is a supervisor, NOT a routing
# authority. It never writes M8SHIFT.md, never runs claim/append/done itself (only
# the runner child performs relay actions, including its own `claim --refresh`
# heartbeat), and never force-steals a pen. PAUSED / DONE / peer-owned / externally
# moved relay states are first-class neutral: the listener sleeps. All process
# control uses explicit argv arrays (no shell interpolation), and the Windows
# aliveness/stop paths never use os.kill(pid, 0) or POSIX signals (RFC 047).
# OS service backends (launchd/systemd/windows) are LIFECYCLE adapters only: the
# service payload is always the same `listener start --foreground ...` argv, the
# service definition never resurrects a halted listener (KeepAlive=false /
# Restart=no), and every service-manager interaction is an explicit bounded argv
# call behind an injectable probe seam so tests never install real services.
# The stuck-work retry wakes ONLY through the runner's explicit --resume-working
# mode (never a plain relaunch, never a force-claim).


def listener_backoff(consecutive_failures, base=LISTENER_BACKOFF_BASE_S, cap=LISTENER_MAX_BACKOFF_S):
    """RFC 047 bounded failure backoff ladder: 20 → 40 → 80 → 160 → 300 (capped).

    Pure and sleep-free so it is unit-testable without waiting; the loop owns the
    actual sleep. Zero/negative failure counts mean no backoff. The exponent is
    clamped so a corrupted sidecar counter cannot force a huge-int computation.
    """
    if consecutive_failures <= 0:
        return 0
    cap = max(1, int(cap))
    exponent = min(int(consecutive_failures) - 1, 32)
    return int(min(base * (2 ** exponent), cap))


def validate_listener_agent(raw):
    agent = (raw or "").strip().lower()
    if not AGENT_RE.fullmatch(agent):
        sys.exit(f"m8shift-runtime: invalid agent name {raw!r}")
    return agent


def listener_paths(agent):
    return {
        "pid": os.path.join(LISTENERS_DIR, f"{agent}.pid"),
        "state": os.path.join(LISTENERS_DIR, f"{agent}.json"),
        "log": os.path.join(LISTENER_LOGS_DIR, f"{agent}-listener.log"),
    }


def listener_log_line(msg):
    print(f"[m8shift-listener] {iso()} {msg}", flush=True)


def listener_emit(agent, msg, owns_log=False):
    """One loop log line. A detached/service-payload listener OWNS its log file and
    appends to it directly, applying writer-side rotation at write time (RFC 047);
    an interactive foreground loop keeps printing to the operator's stdout. On any
    log-file OSError the line falls back to stdout so it is never lost silently."""
    if owns_log:
        path = listener_paths(agent)["log"]
        try:
            os.makedirs(LISTENER_LOGS_DIR, exist_ok=True)
            rotate_listener_log(path)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[m8shift-listener] {iso()} {msg}\n")
            return
        except OSError:
            pass
    listener_log_line(msg)


def read_relay_lock_fields():
    """Read-only LOCK snapshot for the listener loop.

    Returns the LOCK fields as a dict, or None when the relay file or its markers
    are missing/unreadable. The listener never writes the relay; a missing or
    invalid relay while polling is neutral (wait, never launch, never repair).
    """
    try:
        with open(RELAY_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    if RELAY_LOCK_BEGIN not in text or RELAY_LOCK_END not in text:
        return None
    body = text[text.index(RELAY_LOCK_BEGIN) + len(RELAY_LOCK_BEGIN):text.index(RELAY_LOCK_END)]
    fields = {}
    for line in body.splitlines():
        m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def macos_protected_folder(project_dir=None, home=None):
    """RFC 047 macOS protected-folder heuristic on SYNTHETIC-testable paths.

    True when the project sits under a TCC-protected user folder (~/Documents,
    ~/Desktop, ~/Downloads, iCloud Drive under ~/Library/Mobile Documents or any
    com~apple~CloudDocs path). launchd LaunchAgents frequently get `Operation not
    permitted` / getcwd failures there. Pure path logic — never calls launchd —
    and always derived from expanduser("~") (or an injected home for tests).
    """
    project = os.path.realpath(project_dir or HERE)
    if "com~apple~clouddocs" in project.replace(os.sep, "/").lower():
        return True
    base_home = os.path.realpath(home or os.path.expanduser("~"))
    for name in MACOS_PROTECTED_FOLDERS:
        base = os.path.join(base_home, name)
        if project == base or project.startswith(base + os.sep):
            return True
    return False


def listener_backend_probe(problems=None):
    """Backend-selection facts, with the injectable seam (RFC 047 Phase D).

    M8SHIFT_LISTENER_BACKEND_PROBE may hold a JSON object overriding any probed
    key — tests force a deterministic host without touching a real service
    manager. Probed facts: platform, launchctl/systemctl/schtasks availability,
    gui_session (no SSH markers), user_session (XDG_RUNTIME_DIR present), and the
    macOS protected_folder heuristic. With `problems` (doctor mode) an invalid
    injection is reported as a finding message instead of exiting.
    """
    if os.name == "nt":  # pragma: no cover - exercised only on Windows hosts
        platform = "windows"
    elif sys.platform == "darwin":
        platform = "darwin"
    elif sys.platform.startswith("linux"):
        platform = "linux"
    else:
        platform = "other"
    ssh = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    facts = {
        "platform": platform,
        "launchctl": shutil.which("launchctl") is not None,
        "systemctl": shutil.which("systemctl") is not None,
        "schtasks": platform == "windows",
        "gui_session": not ssh,
        "user_session": bool(xdg) and os.path.isdir(xdg),
        "protected_folder": platform == "darwin" and macos_protected_folder(),
    }
    raw = os.environ.get(LISTENER_BACKEND_PROBE_ENV, "")
    if raw:
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError:
            overrides = None
        if not isinstance(overrides, dict):
            msg = f"{LISTENER_BACKEND_PROBE_ENV} must be a JSON object of probe overrides"
            if problems is None:
                sys.exit(f"m8shift-runtime: {msg}")
            problems.append(msg)
        else:
            facts.update(overrides)
    return facts


def select_listener_backend(requested, facts):
    """RFC 047 Phase D backend selection → (backend, fallback_reason).

    Pure decision over (injectable) probe facts, so the whole matrix is testable
    without a service manager. An EXPLICIT service-backend request also degrades
    to `local` — with a visible reason — when the session cannot host it (wrong
    platform/binary, no GUI session for launchd, no user session for systemd): a
    service that can never bootstrap is worse than a portable local detach.
    `auto` picks the platform service backend when clearly suitable; a macOS
    protected-folder project makes auto choose local (doctor also warns), while
    an explicit `launchd` request there proceeds — operator's explicit choice.
    """
    if requested == "local":
        return "local", ""
    darwin_ok = facts.get("platform") == "darwin" and facts.get("launchctl")
    linux_ok = facts.get("platform") == "linux" and facts.get("systemctl")
    win_ok = facts.get("platform") == "windows" and facts.get("schtasks")
    if requested == "launchd":
        if not darwin_ok:
            return "local", "launchd/launchctl is not available on this host"
        if not facts.get("gui_session"):
            return "local", ("no GUI session (SSH or agent session): a gui/<uid> "
                             "LaunchAgent cannot be bootstrapped")
        return "launchd", ""
    if requested == "systemd":
        if not linux_ok:
            return "local", "systemd/systemctl is not available on this host"
        if not facts.get("user_session"):
            return "local", "no systemd user session (XDG_RUNTIME_DIR is missing)"
        return "systemd", ""
    if requested == "windows":
        if not win_ok:
            return "local", "schtasks is not available on this host"
        return "windows", ""
    # auto: safest suitable OS service backend, else local with a printed reason.
    if darwin_ok:
        if facts.get("protected_folder"):
            return "local", ("project is under a macOS protected folder — launchd would "
                             "likely be denied access; use --backend local or grant the "
                             "service permission")
        if not facts.get("gui_session"):
            return "local", "no GUI session available for a launchd LaunchAgent"
        return "launchd", ""
    if linux_ok:
        if not facts.get("user_session"):
            return "local", "no systemd user session available"
        return "systemd", ""
    if win_ok:  # pragma: no cover - exercised only on Windows hosts
        return "windows", ""
    return "local", "no OS service backend is available on this host"


def listener_service_label(agent):
    """Stable service identity per project+agent: sanitized project directory name
    plus a short path hash (two projects sharing a basename must not collide in
    the user's service namespace)."""
    base = re.sub(r"[^a-z0-9-]+", "-", os.path.basename(HERE).lower()).strip("-") or "project"
    digest = hashlib.sha256(HERE.encode("utf-8")).hexdigest()[:8]
    return f"ai.m8shift.{base}-{digest}.{agent}"


def listener_child_argv(args, agent, runner_path, *, service_payload=False):
    """The supervised foreground loop as one explicit argv array.

    This IS the service payload for every backend — `listener start --foreground
    ...` — so listener semantics NEVER change per backend (RFC 047): only the
    lifecycle wrapper around this argv differs. `--service-payload` marks a loop
    started by an OS service manager (owns its log/pid files itself).
    """
    argv = [
        sys.executable, SELF_PATH, "listener", "start",
        "--agent", agent, "--foreground", "--backend", "local",
        "--poll-interval", str(args.poll_interval),
        "--max-retries", str(args.max_retries),
        "--max-backoff", str(args.max_backoff),
        "--runner", runner_path,
    ]
    if args.cmd_file:
        argv += ["--cmd-file", os.path.abspath(args.cmd_file)]
    if args.provider:
        argv.append("--provider")
    if args.max_ticks:
        argv += ["--max-ticks", str(args.max_ticks)]
    if service_payload:
        argv.append("--service-payload")
    return argv


def launchd_plist_doc(label, child_argv, workdir, log_path):
    """LaunchAgent definition (RFC 047 Phase D), as a plistlib-serializable dict.

    KeepAlive is ALWAYS False: launchd must never resurrect a listener that
    halted itself after max retries — the persisted halted sidecar is the
    authority, and an auto-respawn would erase the retry guarantee.
    """
    return {
        "Label": label,
        "ProgramArguments": list(child_argv),
        "WorkingDirectory": workdir,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }


def systemd_quote(arg):
    """Quote one ExecStart argument for a systemd unit: double-quote when needed,
    escape backslash/quote, and double % (systemd specifier) everywhere."""
    arg = arg.replace("%", "%%")
    if arg and not re.search(r'[\s"\'\\;]', arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def systemd_unit_text(label, child_argv, workdir, log_path):
    """User unit text (RFC 047 Phase D). Restart=no keeps the retry guarantee in
    the listener: max-retries/halted live in the listener sidecar and systemd
    must not overrule them by resurrecting the process. (The RFC's alternative —
    Restart=on-failure bounded by StartLimit* — is deliberately not used: no
    restart is strictly safer and a halted loop already stays resident.)"""
    exec_start = " ".join(systemd_quote(a) for a in child_argv)
    return (
        "[Unit]\n"
        f"Description=M8Shift listener ({label})\n"
        "\n"
        "[Service]\n"
        "Type=exec\n"
        f"WorkingDirectory={systemd_quote(workdir)}\n"
        f"ExecStart={exec_start}\n"
        "Restart=no\n"
        f"StandardOutput=append:{log_path}\n"
        f"StandardError=append:{log_path}\n"
    )


def windows_task_command(child_argv):
    """One /TR command string for `schtasks` (guarded by os.name at install time).

    schtasks cannot take an argv array, so the payload argv is joined with the
    documented Windows quoting rules (subprocess.list2cmdline) — still no shell
    interpolation of our own; the string is handed to schtasks as ONE argv item.
    """
    return subprocess.list2cmdline(child_argv)


def backend_install_plan(backend, agent, args, runner_path):
    """GENERATE (never install) one service backend's definition + argv steps.

    Pure content generation: tests assert plist/unit text without bootstrapping
    anything. Generated definitions land under .m8shift/runtime/listeners/ and
    are removed by `listener stop`. Each install/uninstall step is an explicit
    bounded argv; `required: False` steps are best-effort (e.g. a pre-bootstrap
    bootout of a leftover service).
    """
    label = listener_service_label(agent)
    log_path = listener_paths(agent)["log"]
    child = listener_child_argv(args, agent, runner_path, service_payload=True)
    if backend == "launchd":
        service_file = os.path.join(LISTENERS_DIR, f"{label}.plist")
        content = plistlib.dumps(
            launchd_plist_doc(label, child, HERE, log_path), fmt=plistlib.FMT_XML,
        ).decode("utf-8")
        uid = os.getuid() if hasattr(os, "getuid") else 0
        domain = f"gui/{uid}"
        install = [
            {"argv": ["launchctl", "bootout", f"{domain}/{label}"], "required": False},
            {"argv": ["launchctl", "bootstrap", domain, service_file], "required": True},
        ]
        uninstall = [
            {"argv": ["launchctl", "bootout", f"{domain}/{label}"], "required": False},
        ]
    elif backend == "systemd":
        unit = f"{label}.service"
        service_file = os.path.join(LISTENERS_DIR, unit)
        content = systemd_unit_text(label, child, HERE, log_path)
        install = [
            {"argv": ["systemctl", "--user", "link", service_file], "required": True},
            {"argv": ["systemctl", "--user", "start", unit], "required": True},
        ]
        uninstall = [
            {"argv": ["systemctl", "--user", "stop", unit], "required": False},
            {"argv": ["systemctl", "--user", "disable", unit], "required": False},
        ]
    elif backend == "windows":
        service_file = os.path.join(LISTENERS_DIR, f"{label}.task.json")
        command = windows_task_command(child)
        content = json.dumps({
            "schema": LISTENER_BACKEND_SCHEMA,
            "task_name": label,
            "schedule": "ONCE",
            "command": command,
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        install = [
            {"argv": ["schtasks", "/Create", "/F", "/SC", "ONCE", "/ST", "00:00",
                      "/TN", label, "/TR", command], "required": True},
            {"argv": ["schtasks", "/Run", "/TN", label], "required": True},
        ]
        uninstall = [
            {"argv": ["schtasks", "/End", "/TN", label], "required": False},
            {"argv": ["schtasks", "/Delete", "/TN", label, "/F"], "required": False},
        ]
    else:
        sys.exit(f"m8shift-runtime: no service plan for backend {backend!r}")
    return {
        "backend": backend,
        "label": label,
        "service_file": service_file,
        "content": content,
        "child_argv": child,
        "install": install,
        "uninstall": uninstall,
    }


def run_service_argv(argv):
    """Run one bounded service-manager argv → '' on success, else a one-line
    error detail (never raises; used for both required and best-effort steps)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{argv[0]}: {e}"
    if r.returncode == 0:
        return ""
    msg = (r.stderr or r.stdout or "").strip().splitlines()
    detail = msg[0] if msg else ""
    return f"{' '.join(argv)} → rc={r.returncode}" + (f": {detail}" if detail else "")


def listener_backend_record_path(agent):
    return os.path.join(LISTENERS_DIR, f"{agent}.backend.json")


def read_listener_backend_record(agent):
    doc, err = read_json_diagnostic(listener_backend_record_path(agent), {})
    if err or not isinstance(doc, dict) or doc.get("schema") != LISTENER_BACKEND_SCHEMA:
        return {}
    return doc


def write_listener_backend_record(agent, doc):
    os.makedirs(LISTENERS_DIR, exist_ok=True)
    path = listener_backend_record_path(agent)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def install_service_backend(agent, plan):
    """Write the generated definition, record it, then drive the service manager
    with the plan's explicit argv steps. A required-step failure is persisted in
    the backend record (`doctor` → listener.backend_failed): the operator must
    be able to see WHY the service is absent, not just that it is."""
    os.makedirs(LISTENERS_DIR, exist_ok=True)
    os.makedirs(LISTENER_LOGS_DIR, exist_ok=True)
    with open(plan["service_file"], "w", encoding="utf-8") as fh:
        fh.write(plan["content"])
    record = {
        "schema": LISTENER_BACKEND_SCHEMA,
        "agent": agent,
        "backend": plan["backend"],
        "label": plan["label"],
        "service_file": os.path.relpath(plan["service_file"], HERE),
        "installed_at": iso(),
        "uninstall": plan["uninstall"],
        "last_error": "",
    }
    write_listener_backend_record(agent, record)
    for step in plan["install"]:
        detail = run_service_argv(step["argv"])
        if detail and step.get("required", True):
            record["last_error"] = detail[:300]
            write_listener_backend_record(agent, record)
            print(f"m8shift-runtime: {plan['backend']} service install failed: {detail}",
                  file=sys.stderr)
            return 1
    return 0


def uninstall_service_backend(agent, record):
    """Best-effort service teardown for `listener stop`: run the recorded
    uninstall argv steps, then remove the generated definition + record.
    The definition is only ever deleted INSIDE .m8shift/runtime/listeners/
    (path-containment guard against a tampered record)."""
    for step in record.get("uninstall") or []:
        argv = step.get("argv") if isinstance(step, dict) else None
        if isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv):
            run_service_argv(argv)
    service_file = record.get("service_file", "")
    if isinstance(service_file, str) and service_file:
        path = service_file if os.path.isabs(service_file) else os.path.join(HERE, service_file)
        if os.path.realpath(path).startswith(os.path.realpath(LISTENERS_DIR) + os.sep):
            try:
                os.unlink(path)
            except OSError:
                pass
    try:
        os.unlink(listener_backend_record_path(agent))
    except OSError:
        pass


def backend_service_state(record):
    """Read-only service-manager query for `listener status`: 'loaded',
    'not-loaded', or 'unknown'. Queries only when the current (probe-injectable)
    platform can host the recorded backend, so status never blocks on — or
    touches — a foreign service manager."""
    facts = listener_backend_probe(problems=[])
    backend = record.get("backend", "")
    label = record.get("label", "")
    if not label:
        return "unknown"
    if backend == "launchd" and facts.get("platform") == "darwin" and facts.get("launchctl"):
        uid = os.getuid() if hasattr(os, "getuid") else 0
        argv = ["launchctl", "print", f"gui/{uid}/{label}"]
    elif backend == "systemd" and facts.get("platform") == "linux" and facts.get("systemctl"):
        argv = ["systemctl", "--user", "is-active", f"{label}.service"]
    elif backend == "windows" and facts.get("platform") == "windows" and facts.get("schtasks"):
        argv = ["schtasks", "/Query", "/TN", label]  # pragma: no cover - Windows hosts
    else:
        return "unknown"
    return "loaded" if run_service_argv(argv) == "" else "not-loaded"


def listener_log_threshold():
    """Writer-side rotation threshold in bytes: 5 MiB by default (RFC 047),
    injectable via M8SHIFT_LISTENER_LOG_MAX_BYTES so tests rotate at a tiny
    size. Invalid/non-positive injections fall back to the default."""
    raw = os.environ.get(LISTENER_LOG_MAX_ENV, "")
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return LISTENER_LOG_MAX_BYTES


def rotate_listener_log(path, max_bytes=None, keep=LISTENER_LOG_KEEP):
    """Bounded writer-side rotation: <log> → <log>.1 → … → <log>.<keep>, oldest
    generation dropped. Called by the OWNING writer at write time only (RFC 047);
    runs.jsonl is explicitly exempt — it is the runtime ledger and only the
    `retention` commands may prune it. Returns True when a rotation happened."""
    if os.path.basename(path) == "runs.jsonl":
        return False
    limit = max_bytes if max_bytes else listener_log_threshold()
    try:
        if os.path.getsize(path) < limit:
            return False
    except OSError:
        return False
    for gen in range(keep, 0, -1):
        src = path if gen == 1 else f"{path}.{gen - 1}"
        if not os.path.exists(src):
            continue
        try:
            os.replace(src, f"{path}.{gen}")
        except OSError:
            return False
    return True


def listener_starters():
    """Agents configured with start_on_idle=true → {agent: source}, discovered in
    operator profile files (.m8shift/providers/*.json with the listener profile
    schema) and persisted listener state sidecars. Feeds the at-most-one-starter
    guard in `listener start` and doctor's listener.multiple_starters (RFC 047)."""
    starters = {}
    if os.path.isdir(LISTENER_PROFILES_DIR):
        for name in sorted(os.listdir(LISTENER_PROFILES_DIR)):
            if not name.endswith(".json"):
                continue
            doc, err = read_json_diagnostic(os.path.join(LISTENER_PROFILES_DIR, name), {})
            if err or not isinstance(doc, dict) or doc.get("schema") != LISTENER_PROFILE_SCHEMA:
                continue
            agent = doc.get("agent", "")
            if (isinstance(agent, str) and AGENT_RE.fullmatch(agent)
                    and doc.get("start_on_idle") is True):
                starters.setdefault(agent, f".m8shift/providers/{name}")
    if os.path.isdir(LISTENERS_DIR):
        for name in sorted(os.listdir(LISTENERS_DIR)):
            if not name.endswith(".json") or name.endswith(".backend.json"):
                continue
            agent = name[:-5]
            if not AGENT_RE.fullmatch(agent):
                continue
            doc = read_listener_state(agent)
            if doc.get("schema") == LISTENER_STATE_SCHEMA and doc.get("start_on_idle") is True:
                starters.setdefault(agent, f".m8shift/runtime/listeners/{name}")
    return starters


def script_version(path):
    """Parse `VERSION = "..."` from a core/companion script head; '' if unknown."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(65536)
    except OSError:
        return ""
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else ""


def listener_doctor_findings():
    """RFC 047 Phase E — advisory, read-only listener diagnostics for `doctor`.

    Emits the RFC Phase-2 table: listener.not_installed / dead / backend_failed /
    protected_folder / version_skew / repeated_non_completion / halted /
    multiple_starters, plus the rotation companion listener.log_too_large.
    Never mutates any file and never queries a service manager (the probe seam
    supplies host facts; an invalid probe injection becomes a finding).
    """
    findings = []
    probe_problems = []
    facts = listener_backend_probe(probe_problems)
    for msg in probe_problems:
        findings.append({"severity": "warning", "check": "listener.backend_probe", "message": msg})
    states, pid_agents = {}, set()
    if os.path.isdir(LISTENERS_DIR):
        for name in sorted(os.listdir(LISTENERS_DIR)):
            if name.endswith(".backend.json"):
                agent = name[:-len(".backend.json")]
                record = read_listener_backend_record(agent)
                if record.get("last_error"):
                    findings.append({
                        "severity": "warning",
                        "check": "listener.backend_failed",
                        "message": (f"{agent}: {record.get('backend', 'service')} backend "
                                    f"failed: {record['last_error']}"),
                    })
            elif name.endswith(".pid"):
                agent = name[:-4]
                pid_agents.add(agent)
                exists, pid = read_listener_pid(agent)
                if exists and (pid is None or not listener_pid_alive(pid)):
                    findings.append({
                        "severity": "warning",
                        "check": "listener.dead",
                        "message": (f"{agent}: listener pid file exists but the process is "
                                    "gone — `listener status --repair` or `listener start`"),
                    })
            elif name.endswith(".json"):
                agent = name[:-5]
                doc = read_listener_state(agent)
                if doc.get("schema") == LISTENER_STATE_SCHEMA:
                    states[agent] = doc
    repeated = set()
    for agent, doc in sorted(states.items()):
        phase = doc.get("phase", "")
        fails = doc.get("consecutive_failures")
        fails = fails if isinstance(fails, int) and fails >= 0 else 0
        if phase == "halted":
            findings.append({
                "severity": "warning",
                "check": "listener.halted",
                "message": (f"{agent}: listener persisted a halted phase "
                            f"({doc.get('reason') or 'max retries reached'}) — inspect logs, "
                            "then clear explicitly with `listener start --restart`"),
            })
        elif fails >= LISTENER_REPEATED_NON_COMPLETION_N:
            repeated.add(agent)
            findings.append({
                "severity": "warning",
                "check": "listener.repeated_non_completion",
                "message": (f"{agent}: {fails} consecutive failed turns "
                            f"(last: {doc.get('last_classification') or 'unknown'}) — inspect "
                            "the provider prompt/profile and the relay status"),
            })
        recorded = doc.get("runtime_version", "")
        if isinstance(recorded, str) and recorded and recorded != VERSION:
            findings.append({
                "severity": "warning",
                "check": "listener.version_skew",
                "message": (f"{agent}: listener state was written by runtime {recorded} "
                            f"but this companion is {VERSION} — restart the listener"),
            })
    # Trailing consecutive non_completion runs in the runtime ledger (per agent).
    rows, err = read_jsonl_diagnostic(RUNS)
    if not err:
        streaks, closed = {}, set()
        for row in reversed(rows):
            if row.get("event") != "run.ended":
                continue
            agent = row.get("agent") or ""
            if not agent or agent in closed:
                continue
            if row.get("status") == "non_completion":
                streaks[agent] = streaks.get(agent, 0) + 1
            else:
                closed.add(agent)
        for agent, streak in sorted(streaks.items()):
            if streak >= LISTENER_REPEATED_NON_COMPLETION_N and agent not in repeated:
                findings.append({
                    "severity": "warning",
                    "check": "listener.repeated_non_completion",
                    "message": (f"{agent}: last {streak} runs in runs.jsonl ended "
                                "non_completion — the provider exits without completing "
                                "its relay turn"),
                })
    # not_installed: headless-configured agents (provider registry or a listener
    # profile file) that have neither a listener state nor a pid file.
    configured = {}
    if os.path.exists(PROVIDERS):
        for row in load_provider_registry().get("agents", []) or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name", "")
            if (isinstance(name, str) and AGENT_RE.fullmatch(name)
                    and row.get("mode") in ("headless", "hybrid")):
                configured.setdefault(name, f"providers.json mode={row.get('mode')}")
    if os.path.isdir(LISTENER_PROFILES_DIR):
        for name in sorted(os.listdir(LISTENER_PROFILES_DIR)):
            if not name.endswith(".json"):
                continue
            doc, perr = read_json_diagnostic(os.path.join(LISTENER_PROFILES_DIR, name), {})
            if perr or not isinstance(doc, dict) or doc.get("schema") != LISTENER_PROFILE_SCHEMA:
                continue
            agent = doc.get("agent", "")
            if isinstance(agent, str) and AGENT_RE.fullmatch(agent):
                configured.setdefault(agent, f".m8shift/providers/{name}")
    for agent, source in sorted(configured.items()):
        if agent not in states and agent not in pid_agents:
            findings.append({
                "severity": "warning",
                "check": "listener.not_installed",
                "message": (f"{agent}: headless provider is configured ({source}) but no "
                            "listener has ever been started — `listener start --agent "
                            f"{agent} ...`"),
            })
    # version skew between the shipped scripts themselves (core / runner / runtime).
    for path, what in ((CORE_PATH, "core m8shift.py"),
                       (DEFAULT_RUNNER_PATH, "runner examples/headless_runner.py")):
        version = script_version(path)
        if version and version != VERSION:
            findings.append({
                "severity": "warning",
                "check": "listener.version_skew",
                "message": (f"{what} is {version} but m8shift-runtime.py is {VERSION} — "
                            "update the matching companions together"),
            })
    if facts.get("platform") == "darwin" and facts.get("protected_folder"):
        findings.append({
            "severity": "warning",
            "check": "listener.protected_folder",
            "message": ("project sits under a macOS user-protected folder; a launchd "
                        "LaunchAgent may be denied access (Operation not permitted) — "
                        "use `listener start --backend local` or grant the service access"),
        })
    starters = listener_starters()
    if len(starters) > 1:
        detail = ", ".join(f"{agent} ({source})" for agent, source in sorted(starters.items()))
        findings.append({
            "severity": "warning",
            "check": "listener.multiple_starters",
            "message": f"more than one agent is configured with start_on_idle=true: {detail} "
                       "— leave only one IDLE starter (RFC 047)",
        })
    threshold = listener_log_threshold()
    if os.path.isdir(LISTENER_LOGS_DIR):
        for name in sorted(os.listdir(LISTENER_LOGS_DIR)):
            if not name.endswith("-listener.log"):
                continue
            try:
                size = os.path.getsize(os.path.join(LISTENER_LOGS_DIR, name))
            except OSError:
                continue
            if size >= threshold:
                findings.append({
                    "severity": "info",
                    "check": "listener.log_too_large",
                    "message": (f".m8shift/runtime/logs/{name} is {size} bytes "
                                f"(rotation threshold {threshold}) — the owning listener "
                                "rotates it at its next write"),
                })
    return findings


def listener_profile_findings(doc, agent):
    """Validate a m8shift.listener.profile.v1 document; returns problem strings."""
    if not isinstance(doc, dict):
        return ["profile must be a JSON object"]
    problems = []
    if doc.get("schema") != LISTENER_PROFILE_SCHEMA:
        problems.append(f"schema must be {LISTENER_PROFILE_SCHEMA}")
    prof_agent = doc.get("agent", "")
    if not isinstance(prof_agent, str) or not AGENT_RE.fullmatch(prof_agent):
        problems.append("agent must match [a-z][a-z0-9_-]*")
    elif agent and prof_agent != agent:
        problems.append(f"profile agent {prof_agent!r} does not match --agent {agent!r}")
    argv = doc.get("argv")
    if isinstance(argv, str):
        problems.append("argv must be an argv array, not a shell string")
    elif not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        problems.append("argv must be a non-empty JSON array of non-empty strings")
    cwd = doc.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd:
        problems.append("cwd must be a non-empty string path")
    else:
        cwd_abs = cwd if os.path.isabs(cwd) else os.path.join(HERE, cwd)
        if not os.path.isdir(cwd_abs):
            problems.append(f"cwd is not an existing directory: {cwd}")
    env_allow = doc.get("env_allowlist", [])
    if env_allow in (None, ""):
        env_allow = []
    if not isinstance(env_allow, list) or not all(
            isinstance(v, str) and ENV_RE.fullmatch(v) for v in env_allow):
        problems.append("env_allowlist must be a list of environment variable names")
    if not isinstance(doc.get("start_on_idle", False), bool):
        problems.append("start_on_idle must be a boolean (default false)")
    return problems


def normalize_listener_profile(doc, source):
    cwd = doc.get("cwd", ".") or "."
    cwd_abs = cwd if os.path.isabs(cwd) else os.path.abspath(os.path.join(HERE, cwd))
    return {
        "schema": LISTENER_PROFILE_SCHEMA,
        "agent": doc.get("agent", ""),
        "argv": list(doc.get("argv") or []),
        "cwd": cwd_abs,
        "env_allowlist": list(doc.get("env_allowlist") or []),
        "start_on_idle": bool(doc.get("start_on_idle", False)),
        "source": source,
    }


def load_listener_profile(args, agent):
    """Load and validate the provider profile BEFORE any process work (RFC 047)."""
    if bool(args.cmd_file) == bool(args.provider):
        sys.exit("m8shift-runtime: listener start requires exactly one of --cmd-file or --provider")
    if args.cmd_file:
        path = os.path.abspath(args.cmd_file)
        if not os.path.exists(path):
            sys.exit(f"m8shift-runtime: listener profile not found: {args.cmd_file}")
        doc, err = read_json_diagnostic(path, {})
        if err:
            sys.exit(f"m8shift-runtime: cannot read listener profile {args.cmd_file}: {err}")
        source = os.path.relpath(path, HERE)
    else:
        row = provider_by_name(agent)
        if not row:
            sys.exit(f"m8shift-runtime: no provider entry for {agent} in .m8shift/providers.json")
        errors = [f for f in provider_entry_findings(row, agent) if f["severity"] == "error"]
        if errors:
            sys.exit(f"m8shift-runtime: provider entry for {agent} is invalid: "
                     + "; ".join(f["message"] for f in errors))
        argv, _platform = select_provider_argv(row)
        if not argv:
            sys.exit(f"m8shift-runtime: provider entry for {agent} has no argv (nothing to launch headlessly)")
        doc = {
            "schema": LISTENER_PROFILE_SCHEMA,
            "agent": agent,
            "argv": list(argv),
            "cwd": ".",
            "env_allowlist": row.get("env_allowlist") or [],
            "start_on_idle": False,
        }
        source = os.path.relpath(PROVIDERS, HERE)
    problems = listener_profile_findings(doc, agent)
    if problems:
        sys.exit(f"m8shift-runtime: invalid listener profile ({source}):\n  - "
                 + "\n  - ".join(problems))
    return normalize_listener_profile(doc, source)


def new_listener_run_id(agent):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{agent}-{uuid.uuid4().hex[:8]}"


def listener_runner_argv(agent, profile, runner_path, run_id, resume_working=False):
    """One bounded runner turn as an explicit argv array (never a shell string).

    The listener supervises the RUNNER; the runner supervises the provider and is
    the one-shot classifier (RFC 047 Phase A exit codes). RFC 028 markers in the
    provider argv are rendered here without shell interpolation. A stuck-work
    retry sets `resume_working`: the runner gets --resume-working (the ONLY way
    this listener ever wakes an own WORKING lock) and the rendered prompt tells
    the provider it already holds the pen — finish and append, do not claim.
    """
    prompt_template = LISTENER_RESUME_PROMPT if resume_working else LISTENER_TURN_PROMPT
    provider_argv = render_argv_template(
        profile["argv"],
        agent=agent,
        prompt=prompt_template.format(agent=agent, agent_upper=agent.upper()),
        run_id=run_id,
    )
    argv = [
        sys.executable, runner_path, agent, "--once",
        "--m8shift", RELAY_PATH,
        "--m8shift-py", CORE_PATH,
        "--runtime-dir", RUNTIME_DIR,
        "--run-id", run_id,
        "--cwd", profile["cwd"],
    ]
    if profile["env_allowlist"]:
        argv += ["--env-allowlist", ",".join(profile["env_allowlist"])]
    if profile["start_on_idle"]:
        argv.append("--start-on-idle")
    if resume_working:
        argv.append("--resume-working")
    argv += ["--cmd", *provider_argv]
    return argv


def read_listener_state(agent):
    doc, err = read_json_diagnostic(listener_paths(agent)["state"], {})
    if err or not isinstance(doc, dict):
        return {}
    return doc


def write_listener_state(agent, *, phase, consecutive_failures,
                         last_run_id="", last_classification="", reason="",
                         start_on_idle=False):
    os.makedirs(LISTENERS_DIR, exist_ok=True)
    doc = {
        "schema": LISTENER_STATE_SCHEMA,
        "agent": agent,
        "phase": phase,
        "consecutive_failures": consecutive_failures,
        "last_run_id": last_run_id,
        "last_classification": last_classification,
        # start_on_idle is persisted so listener_starters()/doctor can enforce the
        # at-most-one-starter rule; runtime_version feeds listener.version_skew.
        "start_on_idle": bool(start_on_idle),
        "runtime_version": VERSION,
        "updated_at": iso(),
    }
    if reason:
        doc["reason"] = reason
    path = listener_paths(agent)["state"]
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return doc


def read_listener_pid(agent):
    """Return (pid_file_exists, pid_or_None); malformed content yields (True, None)."""
    path = listener_paths(agent)["pid"]
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().strip()
    except FileNotFoundError:
        return False, None
    except OSError:
        return True, None
    try:
        pid = int(raw)
    except ValueError:
        return True, None
    return True, pid if pid > 0 else None


def write_listener_pid(agent, pid):
    os.makedirs(LISTENERS_DIR, exist_ok=True)
    path = listener_paths(agent)["pid"]
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"{pid}\n")
    os.replace(tmp, path)


def remove_listener_pid(agent):
    try:
        os.unlink(listener_paths(agent)["pid"])
        return True
    except OSError:
        return False


def remove_own_listener_pid(agent):
    """Self-cleanup on clean loop exit: only the pid file naming THIS process."""
    exists, pid = read_listener_pid(agent)
    if exists and pid == os.getpid():
        remove_listener_pid(agent)


def windows_pid_alive(pid):  # pragma: no cover - exercised only on Windows hosts
    """Windows aliveness probe via `tasklist` argv — never os.kill(pid, 0) (RFC 047)."""
    try:
        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return f'"{int(pid)}"' in (probe.stdout or "")


def listener_pid_alive(pid):
    """Backend aliveness probe: POSIX signal-0; Windows tasklist (no os.kill there)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised only on Windows hosts
        return windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _posix_signal_group_or_pid(pid, sig):
    """Signal the process group led by `pid`; fall back to the single process only
    when the pid is alive but not a group leader. Never guesses another group."""
    try:
        os.killpg(pid, sig)
        return True
    except ProcessLookupError:
        if not listener_pid_alive(pid):
            return False  # group and leader already gone
    except (PermissionError, OSError):
        pass
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def listener_terminate_group(pid, grace):
    """RFC 047 stop contract: TERM the WHOLE process group, wait `grace`, then KILL.

    Windows path uses `taskkill /PID <pid> /T /F` as an explicit argv subprocess —
    no POSIX signals and no os.kill aliveness probes on Windows. Returns True when
    the supervised pid is confirmed dead.
    """
    if os.name == "nt":  # pragma: no cover - exercised only on Windows hosts
        try:
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        deadline = time.monotonic() + max(1.0, grace)
        while time.monotonic() < deadline:
            if not listener_pid_alive(pid):
                return True
            time.sleep(0.2)
        return not listener_pid_alive(pid)
    _posix_signal_group_or_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace)
    while time.monotonic() < deadline:
        if not listener_pid_alive(pid):
            break
        time.sleep(0.1)
    # Always follow with a group KILL so a TERM-ignoring grandchild cannot outlive
    # its leader; signalling an already-empty group is a harmless no-op.
    _posix_signal_group_or_pid(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not listener_pid_alive(pid):
            return True
        time.sleep(0.05)
    return not listener_pid_alive(pid)


def listener_run_classification(run_id):
    """Read the runner's own classification for `run_id` from the runs ledger.

    Companion-side read of `.m8shift/runtime/runs.jsonl` only — never the relay.
    Returns "" when the ledger has no run.ended row (e.g. stub/foreign runners).
    """
    rows, err = read_jsonl_diagnostic(RUNS)
    if err:
        return ""
    for row in reversed(rows):
        if row.get("run_id") == run_id and row.get("event") == "run.ended":
            status = row.get("status") or row.get("verification_status") or ""
            return status if isinstance(status, str) else ""
    return ""


def build_listener_plan(agent, profile, runner_path, args, backend, fallback_reason=""):
    paths = listener_paths(agent)
    max_retries = args.max_retries
    plan = {
        "schema": LISTENER_PLAN_SCHEMA,
        "agent": agent,
        "backend": backend,
        "backend_requested": args.backend,
        "backend_fallback_reason": fallback_reason,
        "mode": "foreground" if args.foreground else "detached",
        "profile": {key: profile[key] for key in
                    ("schema", "agent", "argv", "cwd", "env_allowlist", "start_on_idle")},
        "profile_source": profile["source"],
        "runner": os.path.relpath(runner_path, HERE),
        "runner_exists": os.path.isfile(runner_path),
        "runner_argv_preview": listener_runner_argv(agent, profile, runner_path, "RUN_ID"),
        "poll_interval_seconds": args.poll_interval,
        "max_ticks": args.max_ticks,
        "max_retries": max_retries,
        "max_backoff_seconds": args.max_backoff,
        "backoff_ladder_seconds": [listener_backoff(n, cap=args.max_backoff)
                                   for n in range(1, max_retries + 1)],
        "pid_file": os.path.relpath(paths["pid"], HERE),
        "state_file": os.path.relpath(paths["state"], HERE),
        "log_file": os.path.relpath(paths["log"], HERE),
        "runtime_version": VERSION,
    }
    if backend in LISTENER_SERVICE_BACKENDS and not args.foreground:
        # Dry-run inspection of the WOULD-BE service install: rendered definition
        # plus the exact bounded argv steps — nothing is written or bootstrapped.
        service = backend_install_plan(backend, agent, args, runner_path)
        plan["service"] = {
            "label": service["label"],
            "service_file": os.path.relpath(service["service_file"], HERE),
            "content": service["content"],
            "install_argv": [step["argv"] for step in service["install"]],
            "uninstall_argv": [step["argv"] for step in service["uninstall"]],
        }
    return plan


def spawn_detached_listener(args, agent, runner_path, backend):
    """Local backend detach: stdlib process primitives only (RFC 047 Phase C).

    POSIX detaches with start_new_session=True (child pid == pgid, so stop can
    killpg the whole tree). Windows uses the documented creationflags and relies
    on `taskkill /T` for stop. stdout/stderr are appended to the listener log.
    """
    os.makedirs(LISTENERS_DIR, exist_ok=True)
    os.makedirs(LISTENER_LOGS_DIR, exist_ok=True)
    child_argv = listener_child_argv(args, agent, runner_path)
    env = os.environ.copy()
    env[LISTENER_DETACHED_ENV] = "1"
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "cwd": HERE,
        "env": env,
    }
    if os.name == "nt":  # pragma: no cover - exercised only on Windows hosts
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        popen_kwargs["start_new_session"] = True
    log_path = listener_paths(agent)["log"]
    with open(log_path, "ab") as log_fh:
        popen_kwargs["stdout"] = log_fh
        popen_kwargs["stderr"] = log_fh
        proc = subprocess.Popen(child_argv, **popen_kwargs)
    write_listener_pid(agent, proc.pid)
    return proc.pid


def run_listener_loop(agent, profile, runner_path, *, poll, max_ticks, max_retries,
                      max_backoff, owns_log=False):
    """The RFC 047 listener loop — one bounded runner turn per wake, zero model spend
    while it is not this agent's turn.

    Decision table per tick (LOCK is read READ-ONLY; the listener never edits it):
      DONE                                          → clean stop (exit 0)
      AWAITING_<agent>                              → launch exactly ONE runner turn
      IDLE + profile.start_on_idle                  → launch exactly ONE runner turn
      WORKING_<agent> (holder==agent) + previous
        run classified stuck_working + budget left  → launch ONE runner turn WITH
                                                      --resume-working (the runner's
                                                      explicit finish-the-held-turn
                                                      mode; never a plain relaunch,
                                                      never a force-claim); with the
                                                      budget exhausted → persist
                                                      phase=halted instead
      PAUSED / AWAITING_<peer> / WORKING_<peer> /
        IDLE without starter / missing relay        → sleep (first-class neutral)
    Runner exit mapping: 0 resets the failure counter; 1 and 2 increment it;
    3 (external_transition) and 4 (suspended) leave it unchanged. At --max-retries
    the loop persists phase=halted, stays resident, and launches nothing more; a
    restarted listener reloads the sidecar and honors an existing halt until an
    explicit `listener start --restart`.
    """
    me_awaiting = f"AWAITING_{agent.upper()}"
    me_working = f"WORKING_{agent.upper()}"
    persisted = read_listener_state(agent)
    phase = persisted.get("phase") if persisted.get("phase") in LISTENER_PHASES else "polling"
    fails = persisted.get("consecutive_failures")
    fails = fails if isinstance(fails, int) and fails >= 0 else 0
    last_run_id = persisted.get("last_run_id") if isinstance(persisted.get("last_run_id"), str) else ""
    last_classification = (persisted.get("last_classification")
                           if isinstance(persisted.get("last_classification"), str) else "")
    reason = persisted.get("reason") if isinstance(persisted.get("reason"), str) else ""

    def say(msg):
        listener_emit(agent, msg, owns_log)

    if phase == "backoff":
        phase = "polling"  # backoff timers are not resumed across restarts
    if phase != "halted":
        reason = ""
    else:
        say(f"{agent}: persisted halted phase found ({reason or 'max retries reached'}) — "
            "supervising without launches; clear it with `listener start --restart`.")

    def save():
        write_listener_state(agent, phase=phase, consecutive_failures=fails,
                             last_run_id=last_run_id,
                             last_classification=last_classification, reason=reason,
                             start_on_idle=profile["start_on_idle"])

    save()
    ticks = 0
    try:
        while True:
            if max_ticks and ticks >= max_ticks:
                say(f"{agent}: max ticks reached ({max_ticks}) — leaving the loop.")
                return 0
            ticks += 1
            if phase == "halted":
                time.sleep(poll)  # resident so status/logs stay inspectable; never launches
                continue
            lk = read_relay_lock_fields()
            if lk is None:
                time.sleep(poll)  # missing/invalid relay is neutral: wait, never repair
                continue
            state = lk.get("state", "")
            if state == "DONE":
                say(f"{agent}: relay session is DONE — stopping cleanly.")
                save()
                return 0
            wake = ""
            if state == me_awaiting:
                wake = "awaiting_turn"
            elif state == "IDLE" and profile["start_on_idle"]:
                wake = "idle_start"
            elif (state == me_working and lk.get("holder", "") == agent
                    and last_classification == "stuck_working"):
                # RFC 047 stuck-work retry: the previous run for this lane ended
                # holding the pen without an append. Relaunch ONE bounded runner
                # turn in the runner's EXPLICIT --resume-working mode (finish the
                # held turn; no claim, never a force-claim) — but only while the
                # retry budget remains; otherwise persist halted without launching.
                if fails >= max_retries:
                    phase = "halted"
                    reason = f"max_retries_after_{last_classification or 'failure'}"
                    say(f"{agent}: own WORKING lock is still stuck with the retry budget "
                        f"exhausted ({fails}/{max_retries}) — HALTED without launching. "
                        "The relay is left for operator recovery; clear with "
                        "`listener start --restart`.")
                    save()
                    continue
                wake = "stuck_retry"
            if not wake:
                # PAUSED, AWAITING_<peer>, WORKING_<peer>, a WORKING_<agent> lock this
                # listener did not classify as stuck, and IDLE without starter
                # permission are all neutral: sleep. Never launch on WORKING_<peer>.
                if phase != "polling":
                    phase = "polling"
                    save()
                time.sleep(poll)
                continue
            run_id = new_listener_run_id(agent)
            resume = wake == "stuck_retry"
            argv = listener_runner_argv(agent, profile, runner_path, run_id,
                                        resume_working=resume)
            say(f"{agent}: state={state} ({wake}) → launching one runner turn"
                f"{' (resume-working)' if resume else ''}, run {run_id}.")
            try:
                rc = subprocess.run(argv, cwd=HERE).returncode
            except OSError as e:
                say(f"{agent}: runner launch failed: {e}")
                rc = 2
            last_run_id = run_id
            last_classification = (listener_run_classification(run_id)
                                   or LISTENER_RUNNER_EXITS.get(rc, "runner_crash"))
            if rc == 0:
                fails = 0
                phase = "polling"
                say(f"{agent}: run {run_id} succeeded ({last_classification}); failure counter reset.")
                save()
                time.sleep(poll)
                continue
            if rc in (3, 4):
                # external_transition / suspended never burn the retry budget (RFC 047).
                phase = "polling"
                say(f"{agent}: run {run_id} was neutral ({last_classification}); counter unchanged.")
                save()
                time.sleep(poll)
                continue
            fails += 1
            if fails >= max_retries:
                phase = "halted"
                reason = f"max_retries_after_{last_classification or 'failure'}"
                say(f"{agent}: run {run_id} failed ({last_classification}); {fails}/{max_retries} — "
                    "HALTED. The relay is left for operator recovery; no force-claim is ever attempted.")
                save()
                continue
            phase = "backoff"
            delay = listener_backoff(fails, cap=max_backoff)
            say(f"{agent}: run {run_id} failed ({last_classification}); {fails}/{max_retries} — "
                f"backing off {delay}s.")
            save()
            time.sleep(delay)
    finally:
        remove_own_listener_pid(agent)


def cmd_listener_start(args):
    agent = validate_listener_agent(args.agent)
    if args.poll_interval <= 0:
        sys.exit("m8shift-runtime: --poll-interval must be > 0 (fractional seconds allowed)")
    if args.max_ticks < 0:
        sys.exit("m8shift-runtime: --max-ticks must be >= 0")
    if args.max_retries < 1:
        sys.exit("m8shift-runtime: --max-retries must be >= 1")
    if args.max_backoff < 1:
        sys.exit("m8shift-runtime: --max-backoff must be >= 1")
    facts = listener_backend_probe()
    backend, fallback_reason = select_listener_backend(args.backend, facts)
    profile = load_listener_profile(args, agent)
    if profile["start_on_idle"]:
        # RFC 047 at-most-one-starter: refusing here (not just warning) keeps two
        # IDLE starters from ever racing the first turn. Doctor also reports the
        # misconfiguration as listener.multiple_starters.
        others = sorted(a for a in listener_starters() if a != agent)
        if others:
            sys.exit("m8shift-runtime: at most one agent may start from IDLE (RFC 047): "
                     f"{agent!r} requests start_on_idle=true but "
                     f"{', '.join(repr(a) for a in others)} is already configured as the "
                     "starter — leave only one starter profile")
    runner_path = os.path.abspath(args.runner) if args.runner else DEFAULT_RUNNER_PATH
    if args.dry_run:
        # Validation-only: prints the plan and writes NO pid, state, log, or
        # service file (service backends render their definition inside the plan).
        plan = build_listener_plan(agent, profile, runner_path, args, backend, fallback_reason)
        print(json.dumps({"dry_run": True, "plan": plan},
                         ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if fallback_reason:
        # RFC 047: the fallback must be VISIBLE — never silently downgrade.
        print(f"backend {args.backend} → local: {fallback_reason}")
    if not os.path.isfile(runner_path):
        sys.exit(f"m8shift-runtime: headless runner not found at "
                 f"{os.path.relpath(runner_path, HERE)} (pass --runner PATH)")
    supervised = os.environ.get(LISTENER_DETACHED_ENV) == "1" or args.service_payload
    if not supervised:
        exists, pid = read_listener_pid(agent)
        if exists and pid and listener_pid_alive(pid):
            if not args.restart:
                sys.exit(f"m8shift-runtime: listener for {agent!r} is already running "
                         f"(pid {pid}); stop it first or rerun with --restart")
            if not listener_terminate_group(pid, 10.0):
                sys.exit(f"m8shift-runtime: could not stop the running listener (pid {pid}) for --restart")
            remove_listener_pid(agent)
            print(f"replaced running listener for {agent} (pid {pid}).")
        elif exists:
            shown = pid if pid is not None else "invalid"
            print(f"stale listener pid file for {agent} (pid {shown} is not alive) — repairing before start.")
            remove_listener_pid(agent)
        if args.restart:
            # --restart is the explicit operator act that clears a persisted halt.
            write_listener_state(agent, phase="polling", consecutive_failures=0,
                                 last_run_id="", last_classification="", reason="",
                                 start_on_idle=profile["start_on_idle"])
    if args.foreground:
        # The loop always records its own pid: for a local detach this is the same
        # value the parent already wrote; for an OS-service payload there IS no
        # parent, so this write is the only source of pid truth for status/stop.
        write_listener_pid(agent, os.getpid())
        return run_listener_loop(
            agent, profile, runner_path,
            poll=args.poll_interval, max_ticks=args.max_ticks,
            max_retries=args.max_retries, max_backoff=args.max_backoff,
            owns_log=supervised)
    paths = listener_paths(agent)
    if backend in LISTENER_SERVICE_BACKENDS:
        # OS service lifecycle (RFC 047 Phase D): generate the definition under
        # .m8shift/runtime/listeners/, then drive the service manager with the
        # plan's explicit argv steps. The payload is the SAME foreground loop.
        plan = backend_install_plan(backend, agent, args, runner_path)
        rc = install_service_backend(agent, plan)
        if rc != 0:
            return rc
        print(f"✓ listener installed for {agent} (backend {backend}, service {plan['label']})")
        print(f"  service: {os.path.relpath(plan['service_file'], HERE)}")
        print(f"  log:     {os.path.relpath(paths['log'], HERE)}")
        print(f"  state:   {os.path.relpath(paths['state'], HERE)}")
        return 0
    pid = spawn_detached_listener(args, agent, runner_path, backend)
    print(f"✓ listener started for {agent} (pid {pid}, backend {backend}, detached)")
    print(f"  log:   {os.path.relpath(paths['log'], HERE)}")
    print(f"  state: {os.path.relpath(paths['state'], HERE)}")
    return 0


def cmd_listener_stop(args):
    agent = validate_listener_agent(args.agent)
    if args.grace < 0:
        sys.exit("m8shift-runtime: --grace must be >= 0")
    rc = 0
    exists, pid = read_listener_pid(agent)
    if not exists:
        print(f"no listener pid file for {agent} (nothing to stop).")
    elif pid is None:
        remove_listener_pid(agent)
        print(f"removed malformed listener pid file for {agent}.")
    elif not listener_pid_alive(pid):
        remove_listener_pid(agent)
        print(f"stale listener pid file removed for {agent} (pid {pid} was already dead).")
    elif not listener_terminate_group(pid, args.grace):
        print(f"m8shift-runtime: listener pid {pid} did not die after TERM/KILL; "
              "pid file kept for inspection", file=sys.stderr)
        rc = 1
    else:
        remove_listener_pid(agent)  # only after confirmed death
        print(f"✓ listener stopped for {agent} (pid {pid}, process group terminated).")
    # RFC 047 Phase D: stop also tears down an installed OS-service definition —
    # generated files under .m8shift/runtime/listeners/ are removed by stop, even
    # when the process/pid side had nothing left to kill.
    record = read_listener_backend_record(agent)
    if record:
        uninstall_service_backend(agent, record)
        print(f"✓ removed {record.get('backend', 'service')} definition for {agent} "
              f"({record.get('service_file', '') or record.get('label', '')}).")
    return rc


def cmd_listener_status(args):
    agent = validate_listener_agent(args.agent)
    paths = listener_paths(agent)
    exists, pid = read_listener_pid(agent)
    alive = bool(pid) and listener_pid_alive(pid)
    if not exists:
        pid_status = "dead"
    elif alive:
        pid_status = "alive"
    else:
        pid_status = "stale"
    doc = read_listener_state(agent)
    phase = doc.get("phase") if doc.get("phase") in LISTENER_PHASES else ""
    halted = phase == "halted"  # persisted: rendered even when the process is gone
    repaired = False
    if args.repair and pid_status == "stale":
        repaired = remove_listener_pid(agent)
        if repaired:
            pid_status = "dead"
    status_label = "HALTED" if halted else pid_status.upper()
    fails = doc.get("consecutive_failures")
    fails = fails if isinstance(fails, int) and fails >= 0 else 0
    # RFC 047 Phase D visibility: when an OS-service backend is installed, status
    # names it and reports the (read-only queried) service state.
    record = read_listener_backend_record(agent)
    backend = record.get("backend", "") if record else "local"
    service_state = backend_service_state(record) if record else ""
    payload = {
        "agent": agent,
        "status": status_label,
        "pid": pid,
        "pid_status": pid_status,
        "process_resident": alive,
        "phase": phase,
        "halted": halted,
        "backend": backend,
        "service_state": service_state,
        "service_label": record.get("label", "") if record else "",
        "service_file": record.get("service_file", "") if record else "",
        "service_error": record.get("last_error", "") if record else "",
        "consecutive_failures": fails,
        "last_run_id": doc.get("last_run_id", ""),
        "last_classification": doc.get("last_classification", ""),
        "updated_at": doc.get("updated_at", ""),
        "reason": doc.get("reason", ""),
        "repaired": repaired,
        "pid_file": os.path.relpath(paths["pid"], HERE),
        "state_file": os.path.relpath(paths["state"], HERE),
        "log_file": os.path.relpath(paths["log"], HERE),
        "runtime_version": VERSION,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    where = f" (pid {pid}, process {'resident' if alive else 'gone'})" if exists else ""
    print(f"listener {agent}: {status_label}{where}")
    if record:
        line = f"  backend: {backend}  service: {service_state or 'unknown'} ({record.get('label', '')})"
        print(line)
        if record.get("last_error"):
            print(f"  service error: {record['last_error']}")
    if phase:
        print(f"  phase: {phase}  consecutive_failures: {fails}")
    if doc.get("last_run_id") or doc.get("last_classification"):
        print(f"  last run: {doc.get('last_run_id') or '-'} "
              f"classification={doc.get('last_classification') or '-'} "
              f"updated={doc.get('updated_at') or '-'}")
    if halted:
        print(f"  reason: {doc.get('reason') or 'max retries reached'}")
        print(f"  clear with: python3 m8shift-runtime.py listener start --agent {agent} --restart ...")
    if pid_status == "stale":
        print("  stale pid file — repair with `listener status --repair`, `listener stop`, "
              "or a fresh `listener start`.")
    if repaired:
        print("  ✓ stale pid file removed.")
    if args.repair and pid_status == "alive":
        print("  listener is alive; nothing to repair.")
    return 0


def cmd_listener_logs(args):
    agent = validate_listener_agent(args.agent)
    if args.tail < 1:
        sys.exit("m8shift-runtime: --tail must be >= 1")
    path = listener_paths(agent)["log"]
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        sys.exit(f"m8shift-runtime: no listener log for {agent} at {os.path.relpath(path, HERE)}")
    for line in lines[-args.tail:]:
        print(line)
    return 0


# ── RFC 040 PR A — read-only usage snapshots (Phase 2 slice) ──
#
# Advisory charter (never negotiable, mirrors the listener charter): the usage
# companion OBSERVES provider session usage, it never routes and never pauses.
# PR A is strictly read-only with respect to the relay: it never writes
# M8SHIFT.md or LOCK, never calls core pause/resume/cooldown, never queues a
# cooperative WORKING_* interrupt, and never launches a provider. Adapters run
# as explicit argv arrays only (no shell strings) with a bounded timeout and a
# capped stdout; M8Shift itself never opens the network — an adapter is a local
# CLI or a local fixture/status file. Raw adapter output is never stored
# verbatim: only normalized m8shift.usage.snapshot.v1 fields plus an optional
# size-capped redacted excerpt reach the sidecars. Unknown usage is fail-open:
# status "unknown", exit 0, warning finding. Exit codes 30/40 are advisory
# automation hints, nothing more (RFC 040, "PR A scope").

USAGE_DIR = os.path.join(PROJECT_DIR, "usage")
USAGE_ADAPTERS = os.path.join(USAGE_DIR, "adapters.json")
USAGE_FIXTURES_DIR = os.path.join(USAGE_DIR, "fixtures")
USAGE_LEDGER = os.path.join(RUNTIME_DIR, "usage.jsonl")
USAGE_ERRORS = os.path.join(RUNTIME_DIR, "usage-adapter-errors.jsonl")
USAGE_ADAPTERS_SCHEMA = "m8shift.usage.adapters.v1"
USAGE_SNAPSHOT_SCHEMA = "m8shift.usage.snapshot.v1"
USAGE_FIXTURE_SCHEMA = "m8shift.usage.fixture.v1"
USAGE_ADAPTER_KINDS = ("cli_json", "fixture")
USAGE_PROVENANCE = ("official", "local_estimate", "proxy_reported",
                    "historical_estimate", "manual", "unknown")
USAGE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
USAGE_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
USAGE_ADAPTER_KEYS = {"//", "name", "agent", "provider", "kind", "command",
                      "fixture_path", "timeout_s", "enabled", "sha256"}
USAGE_TIMEOUT_MIN_S = 1
USAGE_TIMEOUT_MAX_S = 60
USAGE_TIMEOUT_DEFAULT_S = 10
USAGE_MAX_STDOUT_BYTES = 262144
USAGE_RAW_EXCERPT_MAX_CHARS = 240
USAGE_ERRORS_KEEP = 200
USAGE_WARN_THRESHOLD_DEFAULT = 0.80
USAGE_LIMIT_THRESHOLD_DEFAULT = 1.0
USAGE_STALE_AFTER_MINUTES_DEFAULT = 30
# PR A advisory exit codes (read-only surface only; RFC 040 "PR A scope"):
# 0 ok/unknown (fail-open), 12 adapter/config error, 30 near_limit advisory,
# 40 limit_hit advisory. Precedence: 40 > 30 > 12 > 0.
USAGE_EXIT_OK = 0
USAGE_EXIT_CONFIG = 12
USAGE_EXIT_NEAR_LIMIT = 30
USAGE_EXIT_LIMIT_HIT = 40
# Redaction for the optional raw excerpt: token/key-shaped runs never reach the
# sidecars (no existing runtime redaction helper to reuse; patterns mirror the
# context companion's redact-before-store intent).
USAGE_REDACT_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?key|token|secret|password|authorization|credential)\b\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}\b"),
)
# ── RFC 040 PR B — guard/watch/wait/resume constants ──
USAGE_HOLD = os.path.join(RUNTIME_DIR, "usage-hold.json")
USAGE_HOLD_SCHEMA = "m8shift.usage.hold.v1"
USAGE_HOLD_SOURCE = "usage-monitor"
USAGE_CORE_TIMEOUT_S = 30
USAGE_WATCH_INTERVAL_DEFAULT_S = 60.0
USAGE_WAIT_INTERVAL_DEFAULT_S = 30.0
# PR B uses the RFC 040 GENERAL exit-code table (the PR A 0/12/30/40 advisory
# mapping applies to the five read-only commands ONLY): 0 ok, 10 near_limit
# advisory, 11 limit_hit (hold recommended/applied), 12 working-holder
# advisory, 20 unknown (fail-open), 30 adapter/config/policy error, 40
# malformed usage sidecar, 64 CLI usage error, 70 apply-time I/O failure,
# 75 wait still held. Precedence: 40 > 64 > 30 > 70 > 12 > 11 > 10 > 20 > 0.
USAGE_GUARD_EXIT_OK = 0
USAGE_GUARD_EXIT_WARN = 10
USAGE_GUARD_EXIT_HOLD = 11
USAGE_GUARD_EXIT_WORKING = 12
USAGE_GUARD_EXIT_UNKNOWN = 20
USAGE_GUARD_EXIT_ERROR = 30
USAGE_GUARD_EXIT_MALFORMED = 40
USAGE_GUARD_EXIT_USAGE = 64
USAGE_GUARD_EXIT_IO = 70
USAGE_WAIT_EXIT_STILL_HELD = 75
USAGE_GUARD_PRECEDENCE = (40, 64, 30, 70, 12, 11, 10, 20, 0)
USAGE_VERDICT_ORDER = ("limit_hit", "near_limit", "unknown", "ok")
USAGE_VERDICT_EXIT = {"limit_hit": USAGE_GUARD_EXIT_HOLD,
                      "near_limit": USAGE_GUARD_EXIT_WARN,
                      "unknown": USAGE_GUARD_EXIT_UNKNOWN,
                      "ok": USAGE_GUARD_EXIT_OK}
# The core cmd_cooldown LOCK-note signature; recognizing it is how the guard
# family distinguishes a usage cooldown from a plain operator pause.
USAGE_COOLDOWN_NOTE_RE = re.compile(r"cooldown until (\S+) for ([a-z][a-z0-9_-]*|any): ")


def default_usage_adapters():
    return {
        "schema": USAGE_ADAPTERS_SCHEMA,
        "generated_by": f"m8shift-runtime.py {VERSION}",
        "adapters": [
            {
                "//": ("Disabled example: point `command` at a local `claude usage`-style CLI "
                       "that prints m8shift.usage.fixture.v1 JSON on stdout "
                       "(see examples/usage-fixtures/claude.json), then set enabled:true."),
                "name": "claude-usage-cli",
                "agent": "claude",
                "provider": "anthropic-claude",
                "kind": "cli_json",
                "command": ["claude-usage-example", "--json"],
                "timeout_s": USAGE_TIMEOUT_DEFAULT_S,
                "enabled": False,
            },
            {
                "//": ("Disabled example: point `fixture_path` at a local status file with the "
                       "same m8shift.usage.fixture.v1 shape, then set enabled:true."),
                "name": "codex-usage-fixture",
                "agent": "codex",
                "provider": "openai-codex",
                "kind": "fixture",
                "fixture_path": ".m8shift/usage/fixtures/codex.json",
                "timeout_s": USAGE_TIMEOUT_DEFAULT_S,
                "enabled": False,
            },
        ],
    }


def sample_usage_fixture(agent):
    """Obviously synthetic m8shift.usage.fixture.v1 sample (round numbers, epoch-ish dates)."""
    return {
        "schema": USAGE_FIXTURE_SCHEMA,
        "agent": agent,
        "provenance": "manual",
        "captured_at": "2026-01-01T00:00:00Z",
        "used_tokens": 12500,
        "limit_tokens": 100000,
        "windows": [
            {"kind": "session_5h", "resets_at": "2026-01-01T05:00:00Z",
             "used": 12500, "limit": 100000},
            {"kind": "weekly", "resets_at": "2026-01-08T00:00:00Z",
             "used": 50000, "limit": 1000000},
        ],
    }


def usage_timeout_s(entry):
    value = entry.get("timeout_s", USAGE_TIMEOUT_DEFAULT_S)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(USAGE_TIMEOUT_DEFAULT_S)
    if not (USAGE_TIMEOUT_MIN_S <= value <= USAGE_TIMEOUT_MAX_S):
        return float(USAGE_TIMEOUT_DEFAULT_S)
    return float(value)


def usage_adapter_entry_findings(entry, prefix, seen):
    findings = []
    if not isinstance(entry, dict):
        return [{"severity": "error", "check": "usage.adapter",
                 "message": f"{prefix} is not an object"}]
    name = entry.get("name", "")
    if not isinstance(name, str) or not USAGE_NAME_RE.fullmatch(name):
        findings.append({"severity": "error", "check": "usage.name",
                         "message": f"{prefix}.name is invalid"})
    elif name in seen:
        findings.append({"severity": "error", "check": "usage.name_duplicate",
                         "message": f"duplicate adapter name {name}"})
    if isinstance(name, str):
        seen.add(name)
    label = name or prefix
    agent = entry.get("agent", "")
    if not isinstance(agent, str) or not AGENT_RE.fullmatch(agent):
        findings.append({"severity": "error", "check": "usage.agent",
                         "message": f"{label}: agent is invalid"})
    provider = entry.get("provider", "")
    if provider not in (None, "") and not isinstance(provider, str):
        findings.append({"severity": "error", "check": "usage.provider",
                         "message": f"{label}: provider must be a string"})
    kind = entry.get("kind", "")
    if kind not in USAGE_ADAPTER_KINDS:
        findings.append({"severity": "error", "check": "usage.kind",
                         "message": f"{label}: kind must be one of {', '.join(USAGE_ADAPTER_KINDS)}"})
    command = entry.get("command")
    if kind == "cli_json" or command is not None:
        if isinstance(command, str):
            findings.append({"severity": "error", "check": "usage.command_string",
                             "message": f"{label}: command must be an argv array, not a shell string"})
        elif not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
            findings.append({"severity": "error", "check": "usage.command",
                             "message": f"{label}: command must be a non-empty list of non-empty strings"})
        else:
            exe = command[0]
            if not os.path.isabs(exe) and ("/" in exe or "\\" in exe):
                findings.append({"severity": "error", "check": "usage.command_path",
                                 "message": f"{label}: command[0] must be a bare PATH program or an absolute path"})
    if kind == "fixture":
        fixture_path = entry.get("fixture_path", "")
        if not isinstance(fixture_path, str) or not fixture_path.strip():
            findings.append({"severity": "error", "check": "usage.fixture_path",
                             "message": f"{label}: fixture kind requires a non-empty fixture_path"})
    timeout = entry.get("timeout_s", USAGE_TIMEOUT_DEFAULT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
            or not (USAGE_TIMEOUT_MIN_S <= timeout <= USAGE_TIMEOUT_MAX_S):
        findings.append({"severity": "error", "check": "usage.timeout",
                         "message": f"{label}: timeout_s must be a number between "
                                    f"{USAGE_TIMEOUT_MIN_S} and {USAGE_TIMEOUT_MAX_S}"})
    enabled = entry.get("enabled", False)
    if not isinstance(enabled, bool):
        findings.append({"severity": "error", "check": "usage.enabled",
                         "message": f"{label}: enabled must be a boolean"})
    pin = entry.get("sha256", "")
    if pin not in (None, "") and (not isinstance(pin, str) or not USAGE_SHA256_RE.fullmatch(pin.lower())):
        findings.append({"severity": "error", "check": "usage.sha256",
                         "message": f"{label}: sha256 must be a 64-hex-character digest"})
    for key in sorted(set(entry) - USAGE_ADAPTER_KEYS):
        findings.append({"severity": "warning", "check": "usage.unknown_key",
                         "message": f"{label}: unknown key {key!r} ignored"})
    return findings


def usage_config_findings(doc):
    findings = []
    if not isinstance(doc, dict):
        return [{"severity": "error", "check": "usage.schema",
                 "message": "usage adapters config is not a JSON object"}], []
    if doc.get("schema") != USAGE_ADAPTERS_SCHEMA:
        findings.append({"severity": "error", "check": "usage.schema",
                         "message": f"expected schema {USAGE_ADAPTERS_SCHEMA}"})
    adapters = doc.get("adapters")
    if not isinstance(adapters, list):
        return findings + [{"severity": "error", "check": "usage.adapters",
                            "message": "adapters must be a list"}], []
    seen = set()
    for idx, entry in enumerate(adapters):
        findings.extend(usage_adapter_entry_findings(entry, f"adapters[{idx}]", seen))
    entries = [entry for entry in adapters if isinstance(entry, dict)]
    return findings, entries


def load_usage_config():
    """Returns (entries, findings, config_error). Missing/invalid file => config_error."""
    doc, err = read_json_diagnostic(USAGE_ADAPTERS, {})
    if err:
        return [], [{"severity": "error", "check": "usage.config",
                     "message": f"{os.path.relpath(USAGE_ADAPTERS, HERE)}: {err}"}], True
    if not doc:
        return [], [{"severity": "error", "check": "usage.config",
                     "message": "missing .m8shift/usage/adapters.json (run: usage init)"}], True
    findings, entries = usage_config_findings(doc)
    return entries, findings, any(f["severity"] == "error" for f in findings)


def redact_usage_excerpt(text, cap=USAGE_RAW_EXCERPT_MAX_CHARS):
    out = text or ""
    for pattern in USAGE_REDACT_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    out = " ".join(out.split())
    return out[:cap]


def _usage_int_or_none(value, field, warnings):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        warnings.append(f"{field} must be a non-negative integer; ignored")
        return None
    return value


def _usage_iso_or_none(value, field, warnings):
    if value in (None, ""):
        return None
    if isinstance(value, str) and parse_utc(value):
        return value
    warnings.append(f"{field} must be UTC ISO 8601 (YYYY-MM-DDTHH:MM:SSZ); ignored")
    return None


def _usage_ratio_or_none(value, field, warnings):
    """RFC 040 Phase 3: an optional per-window `used_ratio` — the fraction of the
    window's limit already consumed, for official sources that report a
    percent/ratio rather than absolute token counts. A float in [0, 1]; anything
    else is ignored (never coerced) with a warning. Booleans are not ratios."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append(f"{field} must be a number in [0, 1]; ignored")
        return None
    ratio = float(value)
    # NaN/Inf slip past < / > comparisons (all NaN comparisons are False) and would
    # serialize as non-standard JSON; reject any non-finite value outright.
    if not math.isfinite(ratio):
        warnings.append(f"{field} must be a finite number in [0, 1]; ignored")
        return None
    if ratio < 0 or ratio > 1:
        warnings.append(f"{field} must be in [0, 1]; ignored")
        return None
    return ratio


def normalize_usage_snapshot(doc, *, agent, adapter_name, kind, raw_text="", include_raw_excerpt=False):
    """Normalize one m8shift.usage.fixture.v1 document to the pinned
    m8shift.usage.snapshot.v1 shape (RFC 040 "PR A snapshot schema bytes").
    Returns (snapshot, warnings); snapshot is None only on unusable input."""
    warnings = []
    if not isinstance(doc, dict):
        return None, ["adapter output is not a JSON object"]
    schema = doc.get("schema")
    if schema not in (None, USAGE_FIXTURE_SCHEMA):
        return None, [f"unsupported input schema {schema!r} (expected {USAGE_FIXTURE_SCHEMA})"]
    if schema is None:
        warnings.append(f"input does not declare schema {USAGE_FIXTURE_SCHEMA}")
    doc_agent = doc.get("agent")
    if isinstance(doc_agent, str) and doc_agent and doc_agent != agent:
        warnings.append(f"input agent {doc_agent!r} differs from adapter agent {agent!r}; adapter config wins")
    provenance = doc.get("provenance", "unknown")
    if provenance not in USAGE_PROVENANCE:
        warnings.append(f"unknown provenance {provenance!r}; recorded as \"unknown\"")
        provenance = "unknown"
    captured_at = _usage_iso_or_none(doc.get("captured_at"), "captured_at", warnings) or iso()
    used_tokens = _usage_int_or_none(doc.get("used_tokens"), "used_tokens", warnings)
    limit_tokens = _usage_int_or_none(doc.get("limit_tokens"), "limit_tokens", warnings)
    raw_windows = doc.get("windows", [])
    if raw_windows in (None, ""):
        raw_windows = []
    if not isinstance(raw_windows, list):
        warnings.append("windows must be a list; ignored")
        raw_windows = []
    windows = []
    for idx, win in enumerate(raw_windows):
        if not isinstance(win, dict):
            warnings.append(f"windows[{idx}] is not an object; dropped")
            continue
        wkind = win.get("kind")
        if not isinstance(wkind, str) or not wkind:
            warnings.append(f"windows[{idx}].kind must be a non-empty string; window dropped")
            continue
        w_used = _usage_int_or_none(win.get("used"), f"windows[{idx}].used", warnings)
        w_limit = _usage_int_or_none(win.get("limit"), f"windows[{idx}].limit", warnings)
        w_ratio = _usage_ratio_or_none(win.get("used_ratio"), f"windows[{idx}].used_ratio", warnings)
        # RFC 040 Phase 3 honesty rule: a percent/ratio is never a token count.
        # A window carrying BOTH used_ratio and a non-null used/limit is unit-mixed
        # and is REJECTED (dropped, never coerced) so neither value can be misread.
        if w_ratio is not None and (w_used is not None or w_limit is not None):
            warnings.append(f"windows[{idx}] carries both used_ratio and used/limit "
                            "tokens (unit-mixed); window dropped")
            continue
        window = {
            "kind": wkind,
            "resets_at": _usage_iso_or_none(win.get("resets_at"), f"windows[{idx}].resets_at", warnings),
            "used": w_used,
            "limit": w_limit,
        }
        # Additive: `used_ratio` appears ONLY on ratio-native windows, so token-only
        # snapshots stay byte-identical to the shipped v1 output.
        if w_ratio is not None:
            window["used_ratio"] = w_ratio
        windows.append(window)
    ratios = [w["used"] / w["limit"] for w in windows
              if w["used"] is not None and isinstance(w["limit"], int) and w["limit"] > 0]
    # Ratio-native windows contribute their used_ratio directly — no token math.
    ratios += [w["used_ratio"] for w in windows if w.get("used_ratio") is not None]
    if not ratios and used_tokens is not None and isinstance(limit_tokens, int) and limit_tokens > 0:
        ratios = [used_tokens / limit_tokens]
    decision_ratio = round(max(ratios), 4) if ratios else None
    known = {"schema", "agent", "provenance", "captured_at", "used_tokens", "limit_tokens", "windows"}
    for key in sorted(set(doc) - known):
        warnings.append(f"unknown input key {key!r} ignored")
    snapshot = {
        "schema": USAGE_SNAPSHOT_SCHEMA,
        "agent": agent,
        "source": {"adapter": adapter_name, "kind": kind, "provenance": provenance},
        "captured_at": captured_at,
        "used_tokens": used_tokens,
        "limit_tokens": limit_tokens,
        "decision_ratio": decision_ratio,
        "windows": windows,
    }
    if include_raw_excerpt and raw_text:
        snapshot["raw_excerpt_redacted"] = redact_usage_excerpt(raw_text)
    return snapshot, warnings


def classify_usage_ratio(ratio, warn_threshold, limit_threshold):
    if ratio is None:
        return "unknown"
    if ratio >= limit_threshold:
        return "limit_hit"
    if ratio >= warn_threshold:
        return "near_limit"
    return "ok"


def usage_exit_code(classifications, had_adapter_error):
    """PR A advisory precedence: 40 > 30 > 12 > 0 (unknown/ok are fail-open 0)."""
    if "limit_hit" in classifications:
        return USAGE_EXIT_LIMIT_HIT
    if "near_limit" in classifications:
        return USAGE_EXIT_NEAR_LIMIT
    if had_adapter_error:
        return USAGE_EXIT_CONFIG
    return USAGE_EXIT_OK


def trim_usage_errors_ledger(keep=USAGE_ERRORS_KEEP):
    """Bound the adapter-error sidecar to its last `keep` raw lines (bytes preserved)."""
    try:
        with open(USAGE_ERRORS, encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines() if line.strip()]
    except OSError:
        return
    if len(lines) <= keep:
        return
    reject_symlinked_runtime_path(USAGE_ERRORS)
    tmp = f"{USAGE_ERRORS}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines[-keep:]) + "\n")
    os.replace(tmp, USAGE_ERRORS)


def record_usage_adapter_error(adapter_name, agent, message):
    row = runtime_event(
        "usage.adapter_error",
        agent=agent if isinstance(agent, str) and AGENT_RE.fullmatch(agent or "") else "",
        payload={"adapter": adapter_name, "message": redact_usage_excerpt(message),
                 "exit_code": USAGE_EXIT_CONFIG},
    )
    append_jsonl(USAGE_ERRORS, row)
    trim_usage_errors_ledger()


def run_usage_adapter_bounded(argv, timeout, cap):
    """USAGE-1 (Codex review): bounded subprocess capture that NEVER materializes
    unbounded adapter stdout in memory. Binary pipes + reader threads accumulate at
    most cap+1 bytes each; the process is killed on stdout overflow or timeout.

    Returns (returncode, stdout_bytes, stderr_bytes, overflowed, timed_out);
    returncode is None when the process was killed before exiting on its own."""
    proc = subprocess.Popen(argv, cwd=HERE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            shell=False)
    buffers = {"out": b"", "err": b""}
    overflow = threading.Event()

    def reader(stream, key):
        buf = bytearray()
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                take = cap + 1 - len(buf)
                if take > 0:
                    buf += chunk[:take]
                if len(buf) > cap:
                    overflow.set()          # stop accumulating; the main loop kills
                    break
        except (OSError, ValueError):
            pass
        buffers[key] = bytes(buf)

    threads = [threading.Thread(target=reader, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=reader, args=(proc.stderr, "err"), daemon=True)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while proc.poll() is None:
        if overflow.is_set():
            proc.kill()
            break
        if time.monotonic() > deadline:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.05)
    proc.wait()
    for t in threads:
        t.join(timeout=5)
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except (OSError, ValueError):
            pass
    return proc.returncode, buffers["out"], buffers["err"], overflow.is_set(), timed_out


def run_usage_adapter(entry):
    """Read one ENABLED adapter. Bounded, argv-only, no shell, no network by
    M8Shift itself. Returns (doc, raw_text, error_message)."""
    kind = entry.get("kind")
    if kind == "fixture":
        path = entry.get("fixture_path", "")
        if not os.path.isabs(path):
            path = os.path.join(HERE, path)
        try:
            if os.path.getsize(path) > USAGE_MAX_STDOUT_BYTES:
                return None, "", "fixture exceeds the size cap"
            raw = read_text(path)
        except OSError as e:
            return None, "", f"fixture unreadable: {e}"
        try:
            return json.loads(raw), raw, ""
        except json.JSONDecodeError as e:
            return None, raw, f"fixture is not valid JSON: {e}"
    argv = list(entry.get("command") or [])
    exe = argv[0]
    resolved = exe if os.path.isabs(exe) else shutil.which(exe)
    if not resolved or not os.path.exists(resolved):
        return None, "", f"executable {exe!r} not found"
    pin = (entry.get("sha256") or "").lower()
    if pin:
        try:
            digest = sha256_file(os.path.realpath(resolved))
        except (OSError, ValueError) as e:
            return None, "", f"cannot hash executable for identity pin: {e}"
        if digest != pin:
            return None, "", "adapter identity mismatch (sha256 pin); refusing to run"
    timeout = usage_timeout_s(entry)
    try:
        rc, out_b, err_b, overflowed, timed_out = run_usage_adapter_bounded(
            [resolved] + argv[1:], timeout, USAGE_MAX_STDOUT_BYTES)
    except OSError as e:
        return None, "", f"adapter failed to start: {e}"
    if overflowed:
        # Cap-specific finding: the output is discarded, never parsed (USAGE-1).
        return None, "", (f"adapter stdout exceeded the {USAGE_MAX_STDOUT_BYTES}-byte cap; "
                          "process killed, output discarded")
    if timed_out:
        return None, "", f"adapter timed out after {timeout:g}s"
    stdout = out_b.decode("utf-8", errors="replace")
    stderr = err_b.decode("utf-8", errors="replace")
    if rc != 0:
        return None, stdout, f"adapter exited {rc}: {redact_usage_excerpt(stderr or stdout)}"
    try:
        return json.loads(stdout), stdout, ""
    except json.JSONDecodeError as e:
        return None, stdout, f"adapter stdout is not valid JSON: {e}"


def usage_agent_filter(raw):
    """Validated --agent filter. Returns (agent, error); agent '' means no filter."""
    if not raw:
        return "", None
    value = raw.strip().lower()
    if not AGENT_RE.fullmatch(value):
        return "", f"invalid agent name {raw!r}"
    return value, None


def selected_usage_entries(entries, agent_filter):
    matching = [e for e in entries
                if not agent_filter or e.get("agent") == agent_filter]
    enabled = [e for e in matching if e.get("enabled") is True]
    return enabled, len(matching) - len(enabled)


def print_usage_findings(findings):
    for f in findings:
        print(f"{f['severity']} {f['check']}: {f['message']}")


def cmd_usage_init(args):
    os.makedirs(USAGE_FIXTURES_DIR, exist_ok=True)
    created = []
    if write_json_if_missing(USAGE_ADAPTERS, default_usage_adapters()):
        created.append(".m8shift/usage/adapters.json")
    codex_fixture = os.path.join(USAGE_FIXTURES_DIR, "codex.json")
    if write_json_if_missing(codex_fixture, sample_usage_fixture("codex")):
        created.append(".m8shift/usage/fixtures/codex.json")
    ensure_runtime_gitignore()
    if args.json:
        print(json.dumps({"created": created, "runtime_version": VERSION},
                         ensure_ascii=False, sort_keys=True))
        return USAGE_EXIT_OK
    if created:
        print(f"✓ usage scaffold ready ({len(created)} file(s) written; adapters stay disabled until edited).")
        for path in created:
            print(f"  {path}")
    else:
        print("✓ kept existing .m8shift/usage/ files (no clobber).")
    return USAGE_EXIT_OK


def cmd_usage_adapters_list(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_EXIT_CONFIG
    entries, findings, config_error = load_usage_config()
    rows = []
    for entry in entries:
        if agent_filter and entry.get("agent") != agent_filter:
            continue
        rows.append({
            "name": entry.get("name", ""),
            "agent": entry.get("agent", ""),
            "provider": entry.get("provider", ""),
            "kind": entry.get("kind", ""),
            "enabled": entry.get("enabled") is True,
            "timeout_s": usage_timeout_s(entry),
            "identity_pinned": bool(entry.get("sha256")),
        })
    if args.json:
        print(json.dumps({"adapters": rows, "findings": findings,
                          "ok": not config_error, "runtime_version": VERSION},
                         ensure_ascii=False, sort_keys=True))
        return USAGE_EXIT_CONFIG if config_error else USAGE_EXIT_OK
    if not rows and not findings:
        print("no usage adapters configured (run: usage init)")
    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        pin = "pinned" if row["identity_pinned"] else "unpinned"
        print(f"{row['name']}  agent={row['agent']} kind={row['kind']} {state} {pin} timeout={row['timeout_s']:g}s")
    print_usage_findings(findings)
    return USAGE_EXIT_CONFIG if config_error else USAGE_EXIT_OK


def cmd_usage_adapters_check(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_EXIT_CONFIG
    entries, findings, config_error = load_usage_config()
    probed = []
    if not config_error:
        enabled, _skipped = selected_usage_entries(entries, agent_filter)
        for entry in enabled:
            name = entry.get("name", "")
            doc, _raw, err = run_usage_adapter(entry)
            if err:
                record_usage_adapter_error(name, entry.get("agent", ""), err)
                findings.append({"severity": "error", "check": "usage.probe",
                                 "message": f"{name}: {err}"})
                probed.append({"name": name, "ok": False})
                continue
            snapshot, warnings = normalize_usage_snapshot(
                doc, agent=entry.get("agent", ""), adapter_name=name,
                kind=entry.get("kind", ""))
            if snapshot is None:
                record_usage_adapter_error(name, entry.get("agent", ""), warnings[0])
                findings.append({"severity": "error", "check": "usage.probe",
                                 "message": f"{name}: {warnings[0]}"})
                probed.append({"name": name, "ok": False})
                continue
            for message in warnings:
                findings.append({"severity": "warning", "check": "usage.normalize",
                                 "message": f"{name}: {message}"})
            probed.append({"name": name, "ok": True})
    ok = not any(f["severity"] == "error" for f in findings)
    if args.json:
        print(json.dumps({"ok": ok, "probed": probed, "findings": findings,
                          "runtime_version": VERSION},
                         ensure_ascii=False, sort_keys=True))
        return USAGE_EXIT_OK if ok else USAGE_EXIT_CONFIG
    if not findings:
        print("✓ usage adapters config OK"
              + (f" ({len(probed)} enabled adapter(s) probed)" if probed else " (no enabled adapters probed)"))
    print_usage_findings(findings)
    return USAGE_EXIT_OK if ok else USAGE_EXIT_CONFIG


def collect_usage_snapshots(agent_filter, warn_threshold, limit_threshold,
                            include_raw_excerpt):
    """Shared PR A/PR B snapshot collection: runs the enabled adapters and appends
    each normalized snapshot to the ledger. Returns
    (results, findings, had_adapter_error, skipped_disabled, config_error)."""
    entries, findings, config_error = load_usage_config()
    if config_error:
        return [], findings, False, 0, True
    enabled, skipped_disabled = selected_usage_entries(entries, agent_filter)
    results = []
    had_adapter_error = False
    for entry in enabled:
        name = entry.get("name", "")
        agent = entry.get("agent", "")
        doc, raw, err = run_usage_adapter(entry)
        if err:
            had_adapter_error = True
            record_usage_adapter_error(name, agent, err)
            findings.append({"severity": "error", "check": "usage.adapter",
                             "message": f"{name}: {err}"})
            continue
        snapshot, warnings = normalize_usage_snapshot(
            doc, agent=agent, adapter_name=name, kind=entry.get("kind", ""),
            raw_text=raw, include_raw_excerpt=include_raw_excerpt)
        if snapshot is None:
            had_adapter_error = True
            record_usage_adapter_error(name, agent, warnings[0])
            findings.append({"severity": "error", "check": "usage.adapter",
                             "message": f"{name}: {warnings[0]}"})
            continue
        append_jsonl(USAGE_LEDGER, runtime_event(
            "usage.snapshot", agent=agent, payload={"snapshot": snapshot}))
        classification = classify_usage_ratio(
            snapshot["decision_ratio"], warn_threshold, limit_threshold)
        if classification == "unknown":
            findings.append({"severity": "warning", "check": "usage.unknown",
                             "message": f"{name}: usage unknown for {agent}; fail-open (no pause)"})
        for message in warnings:
            findings.append({"severity": "warning", "check": "usage.normalize",
                             "message": f"{name}: {message}"})
        results.append({"adapter": name, "classification": classification,
                        "snapshot": snapshot})
    if not enabled:
        findings.append({"severity": "warning", "check": "usage.no_adapter",
                         "message": "no enabled usage adapter matched; usage unknown (fail-open)"})
    return results, findings, had_adapter_error, skipped_disabled, False


def cmd_usage_snapshot(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_EXIT_CONFIG
    results, findings, had_adapter_error, skipped_disabled, config_error = \
        collect_usage_snapshots(agent_filter, args.warn_threshold,
                                args.limit_threshold, args.raw_excerpt)
    if config_error:
        if args.json:
            print(json.dumps({"ok": False, "snapshots": [], "findings": findings,
                              "runtime_version": VERSION},
                             ensure_ascii=False, sort_keys=True))
        else:
            print_usage_findings(findings)
        return USAGE_EXIT_CONFIG
    code = usage_exit_code({r["classification"] for r in results}, had_adapter_error)
    if args.json:
        print(json.dumps({"ok": code in (USAGE_EXIT_OK, USAGE_EXIT_NEAR_LIMIT, USAGE_EXIT_LIMIT_HIT),
                          "exit_code": code, "snapshots": results,
                          "skipped_disabled": skipped_disabled, "findings": findings,
                          "runtime_version": VERSION},
                         ensure_ascii=False, sort_keys=True))
        return code
    for r in results:
        s = r["snapshot"]
        ratio = "-" if s["decision_ratio"] is None else f"{s['decision_ratio']:g}"
        tokens = f"{s['used_tokens']}/{s['limit_tokens']}" \
            if s["used_tokens"] is not None and s["limit_tokens"] is not None else "-"
        print(f"{s['agent']}  {r['classification']}  ratio={ratio} tokens={tokens} "
              f"adapter={r['adapter']} captured={s['captured_at']}")
    print_usage_findings(findings)
    return code


def read_usage_ledger_diagnostic():
    """Tolerant usage.jsonl reader: malformed lines become warning findings, never crashes."""
    rows, findings = [], []
    try:
        with open(USAGE_LEDGER, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, RecursionError, ValueError) as e:
                    findings.append({"severity": "warning", "check": "usage.ledger",
                                     "message": f".m8shift/runtime/usage.jsonl:{n}: {e}"})
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    findings.append({"severity": "warning", "check": "usage.ledger",
                                     "message": f".m8shift/runtime/usage.jsonl:{n}: not a JSON object"})
    except FileNotFoundError:
        pass
    except OSError as e:
        findings.append({"severity": "warning", "check": "usage.ledger", "message": str(e)})
    return rows, findings


def latest_usage_snapshots(rows, findings):
    latest = {}
    for row in rows:
        if row.get("type") != "usage.snapshot":
            continue
        snapshot = (row.get("payload") or {}).get("snapshot") \
            if isinstance(row.get("payload"), dict) else None
        if not isinstance(snapshot, dict) or snapshot.get("schema") != USAGE_SNAPSHOT_SCHEMA:
            findings.append({"severity": "warning", "check": "usage.ledger",
                             "message": "usage.snapshot event without a valid "
                                        f"{USAGE_SNAPSHOT_SCHEMA} payload skipped"})
            continue
        agent = snapshot.get("agent")
        if not isinstance(agent, str) or not agent:
            findings.append({"severity": "warning", "check": "usage.ledger",
                             "message": "usage.snapshot event without agent skipped"})
            continue
        latest[agent] = snapshot  # append order: last one wins
    return latest


def usage_ledger_report(agent_filter, warn_threshold, limit_threshold, stale_after_minutes):
    """Freshest ledger snapshot per agent, classified with staleness degradation
    (shared by `usage status` and the PR B guard family). Returns
    (report_rows, latest_snapshots_by_agent, findings)."""
    rows, findings = read_usage_ledger_diagnostic()
    latest = latest_usage_snapshots(rows, findings)
    if agent_filter:
        latest = {agent: snap for agent, snap in latest.items() if agent == agent_filter}
    stale_after_s = max(0, stale_after_minutes) * 60
    report = []
    for agent in sorted(latest):
        snapshot = latest[agent]
        captured = parse_utc(snapshot.get("captured_at", ""))
        age_s = int((now() - captured).total_seconds()) if captured else None
        stale = age_s is None or age_s > stale_after_s
        classification = classify_usage_ratio(
            snapshot.get("decision_ratio"), warn_threshold, limit_threshold)
        effective = classification
        if stale:
            effective = "unknown"
            findings.append({"severity": "warning", "check": "usage.stale",
                             "message": f"{agent}: latest snapshot is stale "
                                        f"(older than {stale_after_minutes}m); "
                                        "treated as unknown (fail-open)"})
        elif classification == "unknown":
            findings.append({"severity": "warning", "check": "usage.unknown",
                             "message": f"{agent}: usage unknown; fail-open (no pause)"})
        report.append({
            "agent": agent,
            "adapter": (snapshot.get("source") or {}).get("adapter", ""),
            "captured_at": snapshot.get("captured_at", ""),
            "age_seconds": age_s,
            "stale": stale,
            "decision_ratio": snapshot.get("decision_ratio"),
            "used_tokens": snapshot.get("used_tokens"),
            "limit_tokens": snapshot.get("limit_tokens"),
            "classification": effective,
        })
    if not report:
        findings.append({"severity": "warning", "check": "usage.no_data",
                         "message": "no usage snapshots recorded; usage unknown (fail-open)"})
    return report, latest, findings


def cmd_usage_status(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_EXIT_CONFIG
    report, _latest, findings = usage_ledger_report(
        agent_filter, args.warn_threshold, args.limit_threshold, args.stale_after_minutes)
    code = usage_exit_code({row["classification"] for row in report}, False)
    if args.json:
        print(json.dumps({"ok": True, "exit_code": code, "agents": report,
                          "findings": findings, "runtime_version": VERSION},
                         ensure_ascii=False, sort_keys=True))
        return code
    print(f"m8shift-runtime.py v{VERSION}")
    print("── usage status (advisory, read-only) ─")
    for row in report:
        ratio = "-" if row["decision_ratio"] is None else f"{row['decision_ratio']:g}"
        tokens = f"{row['used_tokens']}/{row['limit_tokens']}" \
            if row["used_tokens"] is not None and row["limit_tokens"] is not None else "-"
        freshness = "stale" if row["stale"] else "fresh"
        print(f"{row['agent']}  {row['classification']}  ratio={ratio} tokens={tokens} "
              f"{freshness} captured={row['captured_at'] or '-'}")
    print_usage_findings(findings)
    return code


# ── RFC 040 PR B — guard / watch / wait / resume (completes the usage block) ──
#
# PR B charter: guard/watch/wait are read-only with respect to everything but
# their own verdict output; `--apply` may write ONLY the usage-hold.json
# sidecar plus a usage.jsonl audit event, and may transition the relay ONLY by
# calling the core `cooldown` command as an argv subprocess (usage `resume`
# likewise calls core `resume`). The companion never edits M8SHIFT.md/LOCK
# itself, never interrupts or force-claims a WORKING_* lock, never launches a
# provider, never opens the network, and NEVER resumes automatically — the
# only road back is an explicit `usage resume` invocation. Exit codes follow
# the RFC 040 GENERAL table (PR B constants above), not the PR A read-only
# mapping, which stays pinned to the five read-only commands.


def parse_usage_cooldown_note(note):
    """Recognize the core cooldown LOCK-note signature
    (`cooldown until <ISO> for <agent|any>: <reason>`). Returns
    {"until", "resume_for"} or None for any other note (operator pause)."""
    m = USAGE_COOLDOWN_NOTE_RE.match(note or "")
    if not m:
        return None
    return {"until": m.group(1), "resume_for": m.group(2)}


def usage_relay_snapshot():
    """Read-only relay view for the guard family (state/holder/turn/note).
    A missing or unreadable relay yields {} — callers degrade gracefully."""
    try:
        core = load_core()
        _, lk = load_status(core)
    except (SystemExit, Exception):
        return {}
    return {
        "state": lk.get("state", ""),
        "holder": lk.get("holder", ""),
        "turn": lk.get("turn", ""),
        "note": lk.get("note", ""),
    }


def run_core_command(argv_tail, timeout=USAGE_CORE_TIMEOUT_S):
    """PR B core interaction: an argv subprocess to the project's own m8shift.py
    beside this companion (resolved like the listener resolves its runner) —
    never a shell string, never an inlined core transition. Capture is bounded
    through the PR A adapter runner. Returns (returncode, stdout, stderr,
    error_message); returncode is None when the call never completed."""
    if not os.path.isfile(CORE_PATH):
        return None, "", "", f"missing core at {os.path.relpath(CORE_PATH, HERE)}"
    argv = [sys.executable, CORE_PATH] + [str(a) for a in argv_tail]
    try:
        rc, out_b, err_b, overflowed, timed_out = run_usage_adapter_bounded(
            argv, timeout, USAGE_MAX_STDOUT_BYTES)
    except OSError as e:
        return None, "", "", f"core call failed to start: {e}"
    if timed_out:
        return None, "", "", f"core call timed out after {timeout:g}s"
    if overflowed:
        return None, "", "", "core call stdout exceeded the byte cap"
    return (rc, out_b.decode("utf-8", errors="replace"),
            err_b.decode("utf-8", errors="replace"), "")


def core_argv_display(argv_tail):
    """Audit-friendly core argv for sidecar events (relative names only — the
    sidecars must never record host-specific absolute paths)."""
    return ["python3", "m8shift.py"] + [str(a) for a in argv_tail]


def read_usage_hold():
    """Returns (hold, error). Missing file => (None, None); a hold that does not
    parse or does not match m8shift.usage.hold.v1 => (None, message) — PR B
    commands map that to exit 40 (malformed usage sidecar)."""
    if not os.path.exists(USAGE_HOLD):
        return None, None
    rel = os.path.relpath(USAGE_HOLD, HERE)
    doc, err = read_json_diagnostic(USAGE_HOLD, {})
    if err:
        return None, f"{rel}: {err}"
    if doc.get("schema") != USAGE_HOLD_SCHEMA:
        return None, f"{rel}: expected schema {USAGE_HOLD_SCHEMA}"
    agent = doc.get("agent")
    if not isinstance(agent, str) or not AGENT_RE.fullmatch(agent):
        return None, f"{rel}: agent is invalid"
    for field in ("placed_at", "resets_at"):
        value = doc.get(field)
        if value is not None and (not isinstance(value, str) or not parse_utc(value)):
            return None, f"{rel}: {field} must be UTC ISO 8601 (YYYY-MM-DDTHH:MM:SSZ) or null"
    return doc, None


def usage_snapshot_ref(snapshot):
    adapter = (snapshot.get("source") or {}).get("adapter", "")
    return (".m8shift/runtime/usage.jsonl#"
            f"{snapshot.get('captured_at', '')}/{snapshot.get('agent', '')}/{adapter}")


def usage_reset_candidate(snapshot, limit_threshold):
    """core `--until` candidate: the earliest resets_at among windows at/above
    the limit threshold; fallback the earliest known resets_at; None when the
    snapshot names no reset (the monitor never invents a provider reset)."""
    limited, known = [], []
    for win in snapshot.get("windows") or []:
        if not isinstance(win, dict):
            continue
        resets = win.get("resets_at")
        t = parse_utc(resets) if isinstance(resets, str) else None
        if not t:
            continue
        known.append((t, resets))
        used, limit = win.get("used"), win.get("limit")
        if isinstance(used, int) and isinstance(limit, int) and limit > 0 \
                and used / limit >= limit_threshold:
            limited.append((t, resets))
    pool = limited or known
    return min(pool)[1] if pool else None


def post_usage_hold(agent, resets_at, reason, snapshot_ref):
    """Idempotent hold write (RFC 040 PR B bytes: exactly seven keys). An
    existing hold for the same agent whose resets_at is at/after the candidate
    is kept byte-identical (placed_at preserved). Returns (written, hold_row,
    error)."""
    existing, err = read_usage_hold()
    if err:
        return False, None, err
    if existing and existing.get("agent") == agent:
        old = parse_utc(existing.get("resets_at") or "")
        new = parse_utc(resets_at or "")
        if not new or (old and old >= new):
            return False, existing, None
    row = {
        "schema": USAGE_HOLD_SCHEMA,
        "agent": agent,
        "placed_at": iso(),
        "resets_at": resets_at,
        "reason": reason,
        "source": USAGE_HOLD_SOURCE,
        "snapshot_ref": snapshot_ref,
    }
    try:
        reject_symlinked_runtime_path(USAGE_HOLD)
        atomic_write_json(USAGE_HOLD, row)
    except OSError as e:
        return False, None, f"cannot write {os.path.relpath(USAGE_HOLD, HERE)}: {e}"
    return True, row, None


def clear_usage_hold():
    """Delete the hold file (clearing = deletion; the audit trail lives in
    usage.jsonl). Returns (cleared, error)."""
    if not os.path.exists(USAGE_HOLD):
        return False, None
    try:
        reject_symlinked_runtime_path(USAGE_HOLD)
        os.remove(USAGE_HOLD)
    except OSError as e:
        return False, f"cannot remove {os.path.relpath(USAGE_HOLD, HERE)}: {e}"
    return True, None


def append_usage_action_event(event_type, agent, payload):
    """Audit append for --apply/resume ACTIONS (mandatory per RFC 040 PR B;
    guard verdicts alone are never recorded)."""
    append_jsonl(USAGE_LEDGER, runtime_event(event_type, agent=agent, payload=payload))


def usage_worst_verdict(report):
    present = {row["classification"] for row in report}
    for verdict in USAGE_VERDICT_ORDER:
        if verdict in present:
            return verdict
    return "unknown"


def usage_pick_code(codes):
    for code in USAGE_GUARD_PRECEDENCE:
        if code in codes:
            return code
    return USAGE_GUARD_EXIT_OK


def usage_apply_hold(agent, row, snapshot, relay, args):
    """The `guard --apply` decision table (limit_hit only; RFC 040 "PR B scope").
    Returns (exit_code, applied_payload, findings). Relay transitions happen
    ONLY through the core cooldown argv call below."""
    findings = []
    state = relay.get("state", "")
    ratio = row.get("decision_ratio")
    ratio_txt = "-" if ratio is None else f"{ratio:g}"
    reason = (f"{agent} usage limit_hit (decision_ratio {ratio_txt} >= "
              f"limit threshold {args.limit_threshold:g})")
    ref = usage_snapshot_ref(snapshot)
    resets_at = usage_reset_candidate(snapshot, args.limit_threshold)

    def warn(check, message):
        findings.append({"severity": "warning", "check": check, "message": message})

    if state == f"WORKING_{agent.upper()}":
        # Own lock: cooperative advisory only — hold sidecar + audit event,
        # exit 12. No core call, no interrupt, no force (RFC 040 PR B).
        written, hold_row, io_err = post_usage_hold(agent, resets_at, reason, ref)
        if io_err:
            findings.append({"severity": "error", "check": "usage.hold_io", "message": io_err})
            return USAGE_GUARD_EXIT_IO, None, findings
        append_usage_action_event("usage.hold_advisory", agent, {
            "action": "advisory_hold" if written else "advisory_hold_already_active",
            "relay_state_before": state, "relay_state_after": state,
            "hold": hold_row, "snapshot_ref": ref, "core": None,
        })
        warn("usage.working",
             f"{agent} holds the pen (state={state}): advisory hold "
             f"{'posted' if written else 'already active'}; pause at the next safe "
             "point (no core call, no interrupt, no force)")
        return USAGE_GUARD_EXIT_WORKING, {"action": "advisory_hold", "written": written,
                                          "hold": hold_row}, findings
    if state.startswith("WORKING_"):
        warn("usage.working_peer",
             f"relay is {state} for another agent: nothing written or called "
             "(the next guard tick re-evaluates)")
        return USAGE_GUARD_EXIT_WORKING, {"action": "peer_working_advisory"}, findings
    if state == "DONE":
        warn("usage.done", "relay session is DONE: left alone, no hold placed")
        return USAGE_GUARD_EXIT_HOLD, {"action": "done_left_alone"}, findings

    if state == "PAUSED":
        cool = parse_usage_cooldown_note(relay.get("note", ""))
        if not cool:
            warn("usage.operator_pause",
                 "relay is PAUSED by an operator pause (not a usage cooldown): "
                 "never converted, nothing written")
            return USAGE_GUARD_EXIT_HOLD, {"action": "operator_pause_left_alone"}, findings
        existing_until = parse_utc(cool["until"])
        candidate = parse_utc(resets_at or "")
        if not candidate or (existing_until and existing_until >= candidate):
            warn("usage.hold_active",
                 f"usage cooldown already active until {cool['until']}; nothing to extend")
            return USAGE_GUARD_EXIT_HOLD, {"action": "hold_already_active",
                                           "until": cool["until"]}, findings
        argv_tail = ["cooldown", "--until", resets_at, "--reason", reason,
                     "--source", USAGE_HOLD_SOURCE, "--replace"]
        if cool["resume_for"] != "any":
            argv_tail += ["--for", cool["resume_for"]]
    else:
        if not resets_at:
            findings.append({
                "severity": "error", "check": "usage.no_reset",
                "message": f"{agent} hit its limit but no window names a resets_at; "
                           "refusing to invent one — place a manual cooldown via "
                           "`python3 m8shift.py cooldown --until ... --reason ...`"})
            return USAGE_GUARD_EXIT_ERROR, None, findings
        argv_tail = ["cooldown", "--until", resets_at, "--reason", reason,
                     "--source", USAGE_HOLD_SOURCE]
        if state in ("IDLE", f"AWAITING_{agent.upper()}"):
            # From AWAITING_<peer>, --for is omitted so the core keeps its own
            # awaited-agent inference (it refuses a mismatched --for).
            argv_tail += ["--for", agent]

    rc, _out, err_txt, run_err = run_core_command(argv_tail)
    if run_err or rc != 0:
        detail = run_err or redact_usage_excerpt(err_txt) or f"exit {rc}"
        findings.append({"severity": "error", "check": "usage.core_call",
                         "message": f"core cooldown call failed: {detail}"})
        return USAGE_GUARD_EXIT_ERROR, None, findings
    relay_after = usage_relay_snapshot()
    written, hold_row, io_err = post_usage_hold(agent, resets_at, reason, ref)
    if io_err:
        findings.append({"severity": "error", "check": "usage.hold_io", "message": io_err})
        return USAGE_GUARD_EXIT_IO, None, findings
    append_usage_action_event("usage.hold_placed", agent, {
        "action": "cooldown_applied",
        "relay_state_before": state, "relay_state_after": relay_after.get("state", ""),
        "hold": hold_row, "snapshot_ref": ref,
        "core": {"argv": core_argv_display(argv_tail), "returncode": rc},
    })
    warn("usage.hold_placed",
         f"usage hold placed for {agent} until {resets_at}; relay is "
         f"{relay_after.get('state', 'PAUSED')}")
    return USAGE_GUARD_EXIT_HOLD, {"action": "cooldown_applied", "until": resets_at,
                                   "written": written, "hold": hold_row}, findings


def usage_guard_evaluate(args, agent_filter, *, apply_mode, snapshot_findings=None,
                         snapshot_error=False):
    """Shared PR B evaluation (the guard command and each watch tick).
    Returns (exit_code, payload)."""
    findings = list(snapshot_findings or [])
    relay = usage_relay_snapshot()
    hold, hold_err = read_usage_hold()
    if hold_err:
        findings.append({"severity": "error", "check": "usage.hold", "message": hold_err})
        return USAGE_GUARD_EXIT_MALFORMED, {
            "verdict": "unknown", "agents": [], "relay": relay, "hold": None,
            "applied": None, "findings": findings}
    report, latest, ledger_findings = usage_ledger_report(
        agent_filter, args.warn_threshold, args.limit_threshold, args.stale_after_minutes)
    findings.extend(ledger_findings)
    verdict = usage_worst_verdict(report)
    codes = [USAGE_VERDICT_EXIT[verdict]]
    if snapshot_error:
        codes.append(USAGE_GUARD_EXIT_ERROR)
    applied = None
    if apply_mode:
        if verdict == "limit_hit":
            apply_row = next(r for r in report if r["classification"] == "limit_hit")
            apply_code, applied, apply_findings = usage_apply_hold(
                apply_row["agent"], apply_row, latest.get(apply_row["agent"], {}),
                relay, args)
            findings.extend(apply_findings)
            codes.append(apply_code)
            hold, _refresh_err = read_usage_hold()  # refresh after a possible write
        else:
            findings.append({"severity": "warning", "check": "usage.apply",
                             "message": f"verdict is {verdict}: nothing applied "
                                        "(holds are placed on limit_hit only)"})
    return usage_pick_code(codes), {
        "verdict": verdict, "agents": report, "relay": relay, "hold": hold,
        "applied": applied, "findings": findings}


def print_usage_guard_result(command, code, payload, json_mode):
    if json_mode:
        out = dict(payload)
        out["ok"] = code in (USAGE_GUARD_EXIT_OK, USAGE_GUARD_EXIT_WARN,
                             USAGE_GUARD_EXIT_HOLD, USAGE_GUARD_EXIT_WORKING,
                             USAGE_GUARD_EXIT_UNKNOWN)
        out["exit_code"] = code
        out["runtime_version"] = VERSION
        print(json.dumps(out, ensure_ascii=False, sort_keys=True), flush=True)
        return code
    relay_state = (payload.get("relay") or {}).get("state") or "-"
    print(f"{command}: verdict={payload['verdict']} relay={relay_state} exit={code}",
          flush=True)
    for row in payload["agents"]:
        ratio = "-" if row["decision_ratio"] is None else f"{row['decision_ratio']:g}"
        freshness = "stale" if row["stale"] else "fresh"
        print(f"  {row['agent']}  {row['classification']}  ratio={ratio} {freshness} "
              f"captured={row['captured_at'] or '-'}")
    applied = payload.get("applied")
    if applied:
        print(f"  applied: {applied.get('action')}")
    print_usage_findings(payload["findings"])
    return code


def cmd_usage_guard(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.apply and not agent_filter:
        print("m8shift-runtime: usage guard --apply requires --agent", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    code, payload = usage_guard_evaluate(args, agent_filter, apply_mode=args.apply)
    return print_usage_guard_result("usage guard", code, payload, args.json)


def cmd_usage_watch(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.apply and not agent_filter:
        print("m8shift-runtime: usage watch --apply requires --agent", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.interval <= 0:
        print("m8shift-runtime: --interval must be > 0 (fractional seconds allowed)",
              file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.max_ticks < 0:
        print("m8shift-runtime: --max-ticks must be >= 0", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    ticks = 0
    while True:
        ticks += 1
        _results, snapshot_findings, had_error, _skipped, config_error = \
            collect_usage_snapshots(agent_filter, args.warn_threshold,
                                    args.limit_threshold, False)
        code, payload = usage_guard_evaluate(
            args, agent_filter, apply_mode=args.apply,
            snapshot_findings=snapshot_findings,
            snapshot_error=(had_error or config_error))
        payload["tick"] = ticks
        # A watch tick that sees an ok verdict NEVER resumes anything (PR B
        # non-goal: no automatic resume; only `usage resume` may resume).
        print_usage_guard_result(f"usage watch tick {ticks}", code, payload, args.json)
        if args.max_ticks and ticks >= args.max_ticks:
            return code
        time.sleep(args.interval)


def cmd_usage_wait(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.interval <= 0:
        print("m8shift-runtime: --interval must be > 0 (fractional seconds allowed)",
              file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    if args.max_ticks < 0:
        print("m8shift-runtime: --max-ticks must be >= 0", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    ticks = 0
    while True:
        ticks += 1
        _hold, hold_err = read_usage_hold()
        if hold_err:
            print(f"m8shift-runtime: {hold_err}", file=sys.stderr)
            return USAGE_GUARD_EXIT_MALFORMED
        report, _latest, findings = usage_ledger_report(
            agent_filter, args.warn_threshold, args.limit_threshold,
            args.stale_after_minutes)
        verdict = usage_worst_verdict(report)
        released = verdict == "ok" or (verdict == "unknown" and not args.until_ok)
        if args.json:
            print(json.dumps({"tick": ticks, "verdict": verdict, "released": released,
                              "findings": findings, "runtime_version": VERSION},
                             ensure_ascii=False, sort_keys=True), flush=True)
        else:
            print(f"usage wait tick {ticks}: verdict={verdict}"
                  f"{' — released' if released else ''}", flush=True)
        if released:
            return USAGE_GUARD_EXIT_OK
        if args.max_ticks and ticks >= args.max_ticks:
            if not args.json:
                print(f"usage wait: still held after {ticks} tick(s) (exit 75)",
                      flush=True)
            return USAGE_WAIT_EXIT_STILL_HELD
        time.sleep(args.interval)


def cmd_usage_resume(args):
    agent_filter, agent_err = usage_agent_filter(args.agent)
    if agent_err:
        print(f"m8shift-runtime: {agent_err}", file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    findings = []
    hold, hold_err = read_usage_hold()
    if hold_err:
        print(f"m8shift-runtime: {hold_err}", file=sys.stderr)
        return USAGE_GUARD_EXIT_MALFORMED
    relay = usage_relay_snapshot()
    state = relay.get("state", "")
    cool = parse_usage_cooldown_note(relay.get("note", "")) if state == "PAUSED" else None
    agent = agent_filter
    if not agent and cool and cool["resume_for"] != "any":
        agent = cool["resume_for"]
    if not agent and hold:
        agent = hold.get("agent", "")
    if not agent:
        print("m8shift-runtime: cannot determine the agent to resume for; pass --agent",
              file=sys.stderr)
        return USAGE_GUARD_EXIT_USAGE
    # The verdict gate uses the hold's agent when a hold exists (the LIMITED
    # agent must have recovered), else the resume agent.
    gate_agent = hold.get("agent") if hold else agent
    report, _latest, ledger_findings = usage_ledger_report(
        gate_agent, args.warn_threshold, args.limit_threshold, args.stale_after_minutes)
    findings.extend(ledger_findings)
    verdict = usage_worst_verdict(report)

    def emit(code, action, extra=None):
        if args.json:
            out = {"ok": code in (USAGE_GUARD_EXIT_OK, USAGE_GUARD_EXIT_WARN,
                                  USAGE_GUARD_EXIT_HOLD),
                   "exit_code": code, "action": action, "agent": agent,
                   "gate_agent": gate_agent, "verdict": verdict, "relay": relay,
                   "hold": hold, "findings": findings, "runtime_version": VERSION}
            out.update(extra or {})
            print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        else:
            print(f"usage resume: {action} (verdict={verdict}, exit={code})")
            print_usage_findings(findings)
        return code

    if verdict == "limit_hit":
        findings.append({"severity": "warning", "check": "usage.resume_refused",
                         "message": f"{gate_agent} is still limit_hit; hold and relay "
                                    "left untouched"})
        return emit(USAGE_GUARD_EXIT_HOLD, "refused_still_limit_hit")
    if verdict != "ok":
        findings.append({"severity": "warning", "check": "usage.resume_refused",
                         "message": f"{gate_agent} verdict is {verdict} (not ok); "
                                    "hold and relay left untouched"})
        return emit(USAGE_GUARD_EXIT_WARN, "refused_not_ok_yet")
    if cool:
        if cool["resume_for"] not in ("any", agent):
            findings.append({"severity": "error", "check": "usage.resume_mismatch",
                             "message": f"active usage cooldown is for "
                                        f"{cool['resume_for']}, not {agent}; refusing "
                                        "to steal the lane"})
            return emit(USAGE_GUARD_EXIT_ERROR, "refused_cooldown_for_other_agent")
        argv_tail = ["resume", agent, "--reason",
                     f"usage window ok for {gate_agent}; cleared by usage-monitor"]
        rc, _out, err_txt, run_err = run_core_command(argv_tail)
        if run_err or rc != 0:
            detail = run_err or redact_usage_excerpt(err_txt) or f"exit {rc}"
            findings.append({"severity": "error", "check": "usage.core_call",
                             "message": f"core resume call failed: {detail}"})
            return emit(USAGE_GUARD_EXIT_ERROR, "core_resume_failed")
        relay_after = usage_relay_snapshot()
        cleared, clear_err = clear_usage_hold()
        if clear_err:
            findings.append({"severity": "error", "check": "usage.hold_io",
                             "message": clear_err})
            return emit(USAGE_GUARD_EXIT_IO, "hold_clear_failed")
        append_usage_action_event("usage.hold_cleared", agent, {
            "action": "resumed",
            "relay_state_before": state,
            "relay_state_after": relay_after.get("state", ""),
            "hold": hold, "hold_cleared": cleared,
            "snapshot_ref": (hold or {}).get("snapshot_ref"),
            "core": {"argv": core_argv_display(argv_tail), "returncode": rc},
        })
        findings.append({"severity": "warning", "check": "usage.resumed",
                         "message": f"relay resumed for {agent} "
                                    f"(state {relay_after.get('state', '')}); "
                                    "usage hold cleared"})
        return emit(USAGE_GUARD_EXIT_OK, "resumed", {"relay_after": relay_after})
    if hold:
        # Stale hold: the relay is not usage-cooldown-PAUSED (running, IDLE,
        # operator-PAUSED, DONE). Clear the sidecar only — an operator pause is
        # NEVER resumed by the usage monitor.
        cleared, clear_err = clear_usage_hold()
        if clear_err:
            findings.append({"severity": "error", "check": "usage.hold_io",
                             "message": clear_err})
            return emit(USAGE_GUARD_EXIT_IO, "hold_clear_failed")
        append_usage_action_event("usage.hold_cleared", agent, {
            "action": "stale_hold_cleared",
            "relay_state_before": state, "relay_state_after": state,
            "hold": hold, "hold_cleared": cleared,
            "snapshot_ref": hold.get("snapshot_ref"), "core": None,
        })
        findings.append({"severity": "warning", "check": "usage.hold_cleared",
                         "message": "stale usage hold cleared; relay untouched "
                                    "(no usage cooldown is active)"})
        return emit(USAGE_GUARD_EXIT_OK, "stale_hold_cleared")
    return emit(USAGE_GUARD_EXIT_OK, "nothing_to_do")


def usage_doctor_findings():
    """Advisory usage-sidecar diagnostics for `doctor` (existence-guarded)."""
    findings = []
    _hold, hold_err = read_usage_hold()
    if hold_err:
        findings.append({"severity": "warning", "check": "usage.hold", "message": hold_err})
    if os.path.exists(USAGE_ADAPTERS):
        doc, err = read_json_diagnostic(USAGE_ADAPTERS, {})
        if err:
            findings.append({"severity": "warning", "check": "usage.config",
                             "message": f"{os.path.relpath(USAGE_ADAPTERS, HERE)}: {err}"})
        else:
            config_findings, _entries = usage_config_findings(doc)
            findings.extend(config_findings)
    for path in (USAGE_LEDGER, USAGE_ERRORS):
        if not os.path.exists(path):
            continue
        rows, err = read_jsonl_diagnostic(path)
        if err:
            findings.append({"severity": "warning", "check": "usage.jsonl", "message": err})
            continue
        if any(row.get("schema") != RUNTIME_EVENT_SCHEMA for row in rows):
            findings.append({
                "severity": "warning",
                "check": "runtime.event_schema",
                "message": f"{os.path.relpath(path, HERE)} has an event without schema {RUNTIME_EVENT_SCHEMA}",
            })
    return findings


def main():
    p = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        description="Local runtime companion for M8Shift sidecars.")
    p.add_argument("--version", action="version", version=f"m8shift-runtime.py {VERSION}",
                   help="show the runtime companion version and exit")
    sub = p.add_subparsers(dest="cmd", required=True)

    ri = sub.add_parser("init", help="scaffold optional local runtime companion files")
    ri.add_argument("--agents", default="", help="comma-separated roster for provider defaults")
    ri.add_argument("--force", action="store_true", help="overwrite existing companion config files")
    ri.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    ri.set_defaults(fn=cmd_runtime_init)

    w = sub.add_parser("watch", help="update local presence while watching relay state")
    w.add_argument("agent", help="agent name whose presence lane to update")
    w.add_argument("--session", default="", help="stable UI/session id for this agent lane")
    w.add_argument("--run", default="", help="optional run id")
    w.add_argument("--interval", type=int, default=5,
                   help="seconds to sleep between watch iterations (default: 5)")
    w.add_argument("--stale-after", type=int, default=300,
                   help="seconds after which another session's presence lane counts as stale (default: 300)")
    w.add_argument("--no-progress-warn-after", type=int, default=0,
                   help="warn when no progress/run event advances within N seconds (0 disables)")
    w.add_argument("--no-progress-block-after", type=int, default=0,
                   help="block this companion loop when no progress/run event advances within N seconds (0 disables)")
    w.add_argument("--once", action="store_true", help="run a single watch iteration and exit")
    w.add_argument("--takeover-stale", action="store_true",
                   help="explicitly take over a different session only when its lane is stale")
    w.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    w.add_argument("--no-notify", action="store_true",
                   help="do not emit local notifications from this watch loop")
    w.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    w.set_defaults(fn=cmd_watch)

    nt = sub.add_parser("notify", help="one-shot local notification or notification config")
    nt.add_argument("target", help="agent name, or 'config' for notification settings")
    nt.add_argument("--event", choices=tuple(sorted(NOTIFY_EVENTS)), default="",
                    help="notification event to emit; required when target is an agent")
    nt.add_argument("--message", default="",
                    help="override notification text; defaults to the resume prompt or event name")
    nt.add_argument("--prompt-file", default="", help="read exact resume prompt from file")
    nt.add_argument("--enable", default="", help="config: comma-separated tiers stdout,file,bell,os,hook")
    nt.add_argument("--os-preset", default="", help="config: auto, off, osascript, notify-send, powershell, or executable")
    nt.add_argument("--hook-argv", nargs="+", default=None,
                    help="config: argv list for hook tier; placeholders must be literal argv items")
    nt.add_argument("--hook-json", default="",
                    help="config: JSON argv array for hook tier, useful for argv items beginning with '-'")
    nt.add_argument("--dedup-window-seconds", type=int, default=None,
                    help="config: duplicate suppression window in seconds")
    nt.add_argument("--show", action="store_true", help="config: show effective config")
    nt.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    nt.set_defaults(fn=cmd_notify)

    op = sub.add_parser("operator", help="queue an operator message for one agent lane")
    op.add_argument("agent", help="agent lane the message is queued for")
    op.add_argument("--mode", choices=("followup", "collect", "interrupt", "status"), required=True,
                    help="delivery contract recorded with the message (how the agent should handle it)")
    op.add_argument("--idempotency-key", default="",
                    help="skip the message as a duplicate if this key was already recorded")
    op.add_argument("message", help="operator message text appended to the agent's inbox")
    op.set_defaults(fn=cmd_operator)

    pr = sub.add_parser("progress", help="append a long-turn progress note")
    pr.add_argument("agent", help="agent name recording the progress note")
    pr.add_argument("--run", required=True, help="run id the progress note belongs to")
    pr.add_argument("message", help="progress note text appended to the progress ledger")
    pr.set_defaults(fn=cmd_progress)

    sr = sub.add_parser("status-runtime", help="show relay status plus runtime sidecars")
    sr.add_argument("agent", nargs="?", help="optional agent name to scope the runtime summary and headroom to")
    sr.add_argument("--brief", action="store_true", help="compact human output; ignored with --json")
    sr.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    sr.set_defaults(fn=cmd_status_runtime)

    hr = sub.add_parser("headroom", help="estimate context-window headroom from local proxy signals")
    hr.add_argument("agent", nargs="?", help="agent to authorize optional pause/checkpoint actions")
    hr.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    hr.add_argument("--checkpoint", action="store_true",
                    help="write a derived session-report checkpoint and record it in runtime runs")
    hr.add_argument("--pause-on", choices=("warning", "high"), default="",
                    help="if the computed risk reaches this level, checkpoint and pause the current holder")
    hr.add_argument("--reason", default="", help="required with --pause-on; recorded in checkpoint/pause audit")
    hr.add_argument("--window-status", choices=("ok", "warning", "high"), default="",
                    help="optional harness-provided exact context-window signal")
    hr.add_argument("--window-reason", default="", help="reason attached to --window-status warning/high")
    hr.add_argument("--warn-after-turns-since-checkpoint", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_turns_since_checkpoint"],
                    help="turns since the last checkpoint before headroom reports warning; 0 disables (default: 8)")
    hr.add_argument("--warn-after-handoff-body-bytes", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_handoff_body_bytes"],
                    help="largest handoff body size in bytes before headroom reports warning; 0 disables (default: 12000)")
    hr.add_argument("--warn-after-relay-bytes", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_relay_bytes"],
                    help="relay file size in bytes before headroom reports warning; 0 disables (default: 250000)")
    hr.add_argument("--pause-recommendation-after-turns-since-checkpoint", type=int,
                    default=HEADROOM_DEFAULTS["pause_recommendation_after_turns_since_checkpoint"],
                    help="turns since the last checkpoint before headroom reports high risk; 0 disables (default: 15)")
    hr.add_argument("--pause-recommendation-after-relay-bytes", type=int,
                    default=HEADROOM_DEFAULTS["pause_recommendation_after_relay_bytes"],
                    help="relay file size in bytes before headroom reports high risk; 0 disables (default: 500000)")
    hr.set_defaults(fn=cmd_headroom)

    dr = sub.add_parser("doctor", help="read-only runtime sidecar diagnostics")
    dr.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    dr.add_argument("--stale-after", type=int, default=300,
                    help="seconds after which a runtime presence lane counts as stale (default: 300)")
    dr.set_defaults(fn=cmd_doctor)

    pv = sub.add_parser("providers", help="local provider/agent registry")
    pv_sub = pv.add_subparsers(dest="verb", required=True)
    pvi = pv_sub.add_parser("init", help="write .m8shift/providers.json")
    pvi.add_argument("--agents", default="", help="comma-separated roster for provider defaults")
    pvi.add_argument("--force", action="store_true", help="overwrite an existing .m8shift/providers.json")
    pvi.set_defaults(fn=cmd_providers_init)
    pvl = pv_sub.add_parser("list", help="list provider entries")
    pvl.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    pvl.set_defaults(fn=cmd_providers_list)
    pvs = pv_sub.add_parser("show", help="show one provider entry as JSON")
    pvs.add_argument("agent", help="agent name whose provider entry to print")
    pvs.set_defaults(fn=cmd_providers_show)
    pvc = pv_sub.add_parser("check", help="validate provider registry")
    pvc.add_argument("agent", nargs="?", help="optional agent name to filter validation findings")
    pvc.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    pvc.set_defaults(fn=cmd_providers_check)
    pvr = pv_sub.add_parser("render", help="render one provider argv array without shell interpolation")
    pvr.add_argument("agent", help="agent name whose provider argv to render")
    pvr.add_argument("--prompt", required=True,
                     help="prompt text substituted for the $M8SHIFT_PROMPT placeholder")
    pvr.add_argument("--run", default="",
                     help="optional run id substituted for the $M8SHIFT_RUN_ID placeholder")
    pvr.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    pvr.set_defaults(fn=cmd_providers_render)

    route = sub.add_parser("route", help="advisory model/task routing")
    route_sub = route.add_subparsers(dest="route_verb", required=True)
    rr = route_sub.add_parser("recommend", help="recommend a capable-enough model without launching")
    rr.add_argument("--task-type", required=True,
                    help="task type key from the routing skills manifest that selects floor/optimum models")
    rr.add_argument("--skill", default="", help="optional skill label recorded in the recommendation output")
    rr.add_argument("--input-tokens", type=int, default=0,
                    help="estimated input size in tokens used to raise the required context class (default: 0)")
    rr.add_argument("--self", dest="self_model", default="", help="explicit pen-holder model id for fail-safe")
    rr.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rr.set_defaults(fn=cmd_route_recommend)

    roles = sub.add_parser("roles", help="runtime role contracts")
    roles_sub = roles.add_subparsers(dest="verb", required=True)
    rl = roles_sub.add_parser("list", help="list role contracts found under .m8shift/roles/")
    rl.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rl.set_defaults(fn=cmd_roles_list)
    rs = roles_sub.add_parser("show", help="print one role contract")
    rs.add_argument("name", help="role contract name (file stem under .m8shift/roles/)")
    rs.set_defaults(fn=cmd_roles_show)

    workflows = sub.add_parser("workflows", help="runtime workflow definitions")
    workflows_sub = workflows.add_subparsers(dest="verb", required=True)
    wl = workflows_sub.add_parser("list", help="list workflow definitions found under .m8shift/workflows/")
    wl.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    wl.set_defaults(fn=cmd_workflows_list)
    ws = workflows_sub.add_parser("show", help="print one workflow definition as JSON")
    ws.add_argument("name", help="workflow definition name (file stem under .m8shift/workflows/)")
    ws.set_defaults(fn=cmd_workflows_show)

    ap = sub.add_parser("approve", help="append one local approval decision")
    ap.add_argument("run", help="run id the approval applies to")
    ap.add_argument("gate", help="gate id being decided")
    ap.add_argument("--by", required=True, help="agent or operator name recording the decision")
    ap.add_argument("--decision", choices=("approved", "rejected", "waived"), required=True,
                    help="decision recorded for the gate")
    ap.add_argument("--reason", default="", help="optional free-text reason stored with the decision")
    ap.set_defaults(fn=cmd_approve)

    rp = sub.add_parser("report", help="summarize one local runtime run")
    rp.add_argument("run", help="run id to summarize from the runtime ledgers")
    rp.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rp.add_argument("--write", action="store_true", help="write .m8shift/runs/<run>/report.md")
    rp.set_defaults(fn=cmd_report)

    retention = sub.add_parser("retention", help="bounded runtime sidecar retention")
    ret_sub = retention.add_subparsers(dest="verb", required=True)
    rprune = ret_sub.add_parser("prune", help="prune runtime JSONL ledgers to a fixed row cap")
    rprune.add_argument("--keep", type=int, default=1000, help="rows to retain per ledger (default: 1000)")
    rprune.add_argument("--no-archive", action="store_true",
                        help="discard pruned rows instead of appending them under .m8shift/runtime/archive/")
    rprune.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rprune.set_defaults(fn=cmd_retention_prune)
    rapp = ret_sub.add_parser("apply", help="apply .m8shift/runtime/retention.json policy")
    rapp.add_argument("--dry-run", action="store_true", help="show planned pruning without changing files")
    rapp.add_argument("--no-archive", action="store_true",
                      help="discard pruned rows instead of archiving them")
    rapp.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rapp.set_defaults(fn=cmd_retention_apply)
    rpolicy = ret_sub.add_parser("policy", help="inspect runtime retention policy")
    rpolicy_sub = rpolicy.add_subparsers(dest="policy_verb", required=True)
    rpshow = rpolicy_sub.add_parser("show", help="show effective retention policy")
    rpshow.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of human output")
    rpshow.set_defaults(fn=cmd_retention_policy_show)

    listener = sub.add_parser(
        "listener",
        help="supervise headless runner lifecycles (RFC 047: local/launchd/systemd/windows backends)")
    listener_sub = listener.add_subparsers(dest="verb", required=True)
    lst = listener_sub.add_parser(
        "start", help="start (or dry-run plan) one agent's listener loop")
    lst.add_argument("--agent", required=True, help="agent name whose listener lane to start")
    lst.add_argument("--cmd-file", default="",
                     help="path to a m8shift.listener.profile.v1 JSON provider profile (argv array only)")
    lst.add_argument("--provider", action="store_true",
                     help="build the profile from this agent's .m8shift/providers.json entry instead of --cmd-file")
    lst.add_argument("--backend", choices=LISTENER_BACKENDS, default="auto",
                     help="lifecycle backend: local detach, launchd LaunchAgent (macOS), "
                          "systemd user unit (Linux), or schtasks (Windows); auto probes the "
                          "host and falls back to local with a printed reason (probe facts "
                          "injectable via M8SHIFT_LISTENER_BACKEND_PROBE as a JSON object — "
                          "test seam, never touches a real service manager)")
    lst.add_argument("--restart", action="store_true",
                     help="replace a live listener and clear a persisted halted phase")
    lst.add_argument("--service-payload", action="store_true",
                     help="internal (written into generated service definitions): mark this "
                          "foreground loop as an OS-service payload that owns its own pid file "
                          "and log file (writer-side rotation); not for interactive use")
    lst.add_argument("--dry-run", action="store_true",
                     help="validate the profile and print the launch plan; writes no pid/state/log file")
    lst.add_argument("--poll-interval", type=float, default=LISTENER_DEFAULT_POLL_S,
                     help="seconds between relay polls; fractional values allowed (default: 20)")
    lst.add_argument("--max-ticks", type=int, default=0,
                     help="bound the loop to N iterations (test seam; 0 = unbounded)")
    lst.add_argument("--max-retries", type=int, default=LISTENER_DEFAULT_MAX_RETRIES,
                     help="consecutive failed turns before the listener persists a halted phase (default: 3)")
    lst.add_argument("--max-backoff", type=int, default=LISTENER_MAX_BACKOFF_S,
                     help="cap in seconds on the 20/40/80/160/... failure backoff ladder (default: 300)")
    lst.add_argument("--foreground", action="store_true",
                     help="run the listener loop in this process instead of detaching")
    lst.add_argument("--runner", default="",
                     help="path to the headless runner script the listener supervises "
                          "(default: examples/headless_runner.py beside this companion)")
    lst.set_defaults(fn=cmd_listener_start)
    lsp = listener_sub.add_parser(
        "stop", help="terminate one agent's listener process group and remove its pid file")
    lsp.add_argument("--agent", required=True, help="agent name whose listener lane to stop")
    lsp.add_argument("--grace", type=float, default=10.0,
                     help="seconds to wait after TERM before the group KILL (default: 10)")
    lsp.set_defaults(fn=cmd_listener_stop)
    lss = listener_sub.add_parser(
        "status", help="show alive/stale/dead/HALTED listener state for one agent")
    lss.add_argument("--agent", required=True, help="agent name whose listener lane to inspect")
    lss.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    lss.add_argument("--repair", action="store_true",
                     help="remove the pid file when it is stale (process dead); never touches a live listener")
    lss.set_defaults(fn=cmd_listener_status)
    lsl = listener_sub.add_parser("logs", help="print the tail of one agent's listener log")
    lsl.add_argument("--agent", required=True, help="agent name whose listener log to print")
    lsl.add_argument("--tail", type=int, default=50,
                     help="number of trailing log lines to print (default: 50)")
    lsl.set_defaults(fn=cmd_listener_logs)

    usage = sub.add_parser(
        "usage",
        help="AI session usage monitoring (RFC 040: read-only snapshots + advisory "
             "guard family; the relay is only ever parked THROUGH core cooldown/resume)")
    usage_sub = usage.add_subparsers(dest="verb", required=True)

    def usage_threshold_flags(sp):
        sp.add_argument("--warn-threshold", type=float, default=USAGE_WARN_THRESHOLD_DEFAULT,
                        help="decision_ratio at or above which the verdict is near_limit (default: 0.80)")
        sp.add_argument("--limit-threshold", type=float, default=USAGE_LIMIT_THRESHOLD_DEFAULT,
                        help="decision_ratio at or above which the verdict is limit_hit (default: 1.0)")
        sp.add_argument("--stale-after-minutes", type=int, default=USAGE_STALE_AFTER_MINUTES_DEFAULT,
                        help="ledger snapshots older than this degrade to unknown/fail-open (default: 30)")

    uin = usage_sub.add_parser(
        "init", help="scaffold .m8shift/usage/adapters.json with disabled example adapters (no clobber)")
    uin.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    uin.set_defaults(fn=cmd_usage_init)
    uad = usage_sub.add_parser("adapters", help="inspect and validate the usage adapter registry")
    uad_sub = uad.add_subparsers(dest="adapters_verb", required=True)
    ual = uad_sub.add_parser("list", help="list usage adapter entries with enabled/identity state")
    ual.add_argument("--agent", default="", help="only list adapters for this agent")
    ual.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    ual.set_defaults(fn=cmd_usage_adapters_list)
    uac = uad_sub.add_parser(
        "check", help="validate the adapter config and probe ONLY enabled adapters (bounded argv run)")
    uac.add_argument("--agent", default="", help="only check adapters for this agent")
    uac.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    uac.set_defaults(fn=cmd_usage_adapters_check)
    usn = usage_sub.add_parser(
        "snapshot",
        help="read enabled adapters, normalize to m8shift.usage.snapshot.v1, append to usage.jsonl")
    usn.add_argument("--agent", default="", help="only snapshot adapters for this agent")
    usn.add_argument("--warn-threshold", type=float, default=USAGE_WARN_THRESHOLD_DEFAULT,
                     help="decision_ratio at or above which the advisory near_limit exit 30 fires (default: 0.80)")
    usn.add_argument("--limit-threshold", type=float, default=USAGE_LIMIT_THRESHOLD_DEFAULT,
                     help="decision_ratio at or above which the advisory limit_hit exit 40 fires (default: 1.0)")
    usn.add_argument("--raw-excerpt", action="store_true",
                     help="include a size-capped REDACTED raw excerpt in the stored snapshot")
    usn.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    usn.set_defaults(fn=cmd_usage_snapshot)
    ust = usage_sub.add_parser(
        "status", help="latest snapshot per agent from the ledger with freshness and advisory classification")
    ust.add_argument("--agent", default="", help="only report this agent")
    ust.add_argument("--stale-after-minutes", type=int, default=USAGE_STALE_AFTER_MINUTES_DEFAULT,
                     help="snapshots older than this degrade to unknown/fail-open (default: 30)")
    ust.add_argument("--warn-threshold", type=float, default=USAGE_WARN_THRESHOLD_DEFAULT,
                     help="decision_ratio at or above which the advisory near_limit exit 30 fires (default: 0.80)")
    ust.add_argument("--limit-threshold", type=float, default=USAGE_LIMIT_THRESHOLD_DEFAULT,
                     help="decision_ratio at or above which the advisory limit_hit exit 40 fires (default: 1.0)")
    ust.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    ust.set_defaults(fn=cmd_usage_status)
    ugd = usage_sub.add_parser(
        "guard",
        help="advisory verdict from the freshest ledger snapshots (RFC 040 PR B); "
             "--apply parks the relay ONLY through the core cooldown command")
    ugd.add_argument("--agent", default="",
                     help="agent whose usage verdict to evaluate (required with --apply)")
    ugd.add_argument("--apply", action="store_true",
                     help="on limit_hit only: write usage-hold.json and call core cooldown "
                          "via argv (cooperative: a WORKING_* relay is never mutated; "
                          "near_limit/unknown never apply)")
    usage_threshold_flags(ugd)
    ugd.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    ugd.set_defaults(fn=cmd_usage_guard)
    uwt = usage_sub.add_parser(
        "watch",
        help="poll loop: re-snapshot enabled adapters each tick, then evaluate the guard "
             "verdict (never resumes anything)")
    uwt.add_argument("--agent", default="",
                     help="agent to snapshot and guard (required with --apply)")
    uwt.add_argument("--interval", type=float, default=USAGE_WATCH_INTERVAL_DEFAULT_S,
                     help="seconds between ticks; fractional values allowed (default: 60)")
    uwt.add_argument("--max-ticks", type=int, default=0,
                     help="bound the loop to N ticks (test seam; 0 = unbounded); exit code "
                          "is the final tick's guard code")
    uwt.add_argument("--apply", action="store_true",
                     help="apply the guard --apply rules on each tick (limit_hit only)")
    usage_threshold_flags(uwt)
    uwt.add_argument("--json", action="store_true",
                     help="emit one machine-readable JSON line per tick")
    uwt.set_defaults(fn=cmd_usage_watch)
    uwa = usage_sub.add_parser(
        "wait",
        help="token-free local blocker: re-read the ledger verdict each tick until it "
             "releases (writes nothing, calls nothing)")
    uwa.add_argument("--agent", default="", help="only wait on this agent's verdict")
    uwa.add_argument("--until-ok", action="store_true",
                     help="release only on a genuine ok verdict (default also releases on "
                          "unknown, fail-open)")
    uwa.add_argument("--interval", type=float, default=USAGE_WAIT_INTERVAL_DEFAULT_S,
                     help="seconds between ticks; fractional values allowed (default: 30)")
    uwa.add_argument("--max-ticks", type=int, default=0,
                     help="exit 75 after N ticks while still held (test seam; 0 = unbounded)")
    usage_threshold_flags(uwa)
    uwa.add_argument("--json", action="store_true",
                     help="emit one machine-readable JSON line per tick")
    uwa.set_defaults(fn=cmd_usage_wait)
    urs = usage_sub.add_parser(
        "resume",
        help="explicitly clear the usage hold and resume a usage cooldown through core "
             "resume (the ONLY road back; never automatic)")
    urs.add_argument("--agent", default="",
                     help="agent to resume for (default: the cooldown note's resume_for, "
                          "then the hold's agent)")
    usage_threshold_flags(urs)
    urs.add_argument("--json", action="store_true",
                     help="emit machine-readable JSON instead of human output")
    urs.set_defaults(fn=cmd_usage_resume)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
