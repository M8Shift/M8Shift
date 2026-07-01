#!/usr/bin/env python3
"""m8shift-runtime.py — optional local runtime companion for M8Shift.

The companion records local presence, operator messages, progress, and run lifecycle
sidecars under `.m8shift/runtime/`. It never edits `M8SHIFT.md` directly and never becomes
an authority for the pen; all routing remains owned by `m8shift.py`.
"""
import argparse
import datetime as dt
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

VERSION = "3.34.1"
RUNTIME_EVENT_SCHEMA = "m8shift.runtime.event.v1"
PRESENCE_SCHEMA = "m8shift.runtime.presence.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
CORE_PATH = os.path.join(HERE, "m8shift.py")
RUNTIME_DIR = os.path.join(HERE, ".m8shift", "runtime")
PROJECT_DIR = os.path.join(HERE, ".m8shift")
PROVIDERS = os.path.join(PROJECT_DIR, "providers.json")
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
PROVIDER_MODES = {"interactive", "headless", "hybrid", "local"}
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


RUNTIME_README = """# M8Shift runtime companion

This directory is optional. It belongs to `m8shift-runtime.py`, not to the passive
core relay.

- `providers.json`: host-side agent/provider registry. Keep secrets out of it.
  Generated registries include opt-in `examples` for cooperative headless CLIs;
  copy/adapt them into active agents before use.
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
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl_rows(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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
        if not isinstance(pattern, str) or pattern.startswith(("/", "\\")) or ".." in pattern.split("/"):
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
    if args.json:
        print(json.dumps({
            "m8shift_version": status.get("m8shift_version"),
            "runtime_version": VERSION,
            "relay": status,
            "runtime": summary,
            "headroom": headroom,
            "runtime_findings": findings,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"m8shift-runtime.py v{VERSION}")
    print(f"relay: {status.get('state')} holder={status.get('holder')} turn={status.get('turn')}")
    reasons = "; ".join(headroom.get("reasons") or ["-"])
    print(f"headroom: {headroom.get('status')} — {reasons}")
    if not args.brief:
        print(f"  next: {headroom.get('next')}")
    for ag, data in summary.items():
        pres = data.get("presence") or {}
        print(
            f"{ag}: presence={pres.get('state', '-')} session={pres.get('session_id', '-')} "
            f"inbox={data.get('inbox_count', 0)}"
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
    if os.path.exists(PROVIDERS):
        findings.extend(provider_findings(load_provider_registry()))
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


def main():
    p = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        description="Local runtime companion for M8Shift sidecars.")
    p.add_argument("--version", action="version", version=f"m8shift-runtime.py {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ri = sub.add_parser("init", help="scaffold optional local runtime companion files")
    ri.add_argument("--agents", default="", help="comma-separated roster for provider defaults")
    ri.add_argument("--force", action="store_true", help="overwrite existing companion config files")
    ri.add_argument("--json", action="store_true")
    ri.set_defaults(fn=cmd_runtime_init)

    w = sub.add_parser("watch", help="update local presence while watching relay state")
    w.add_argument("agent")
    w.add_argument("--session", default="", help="stable UI/session id for this agent lane")
    w.add_argument("--run", default="", help="optional run id")
    w.add_argument("--interval", type=int, default=5)
    w.add_argument("--stale-after", type=int, default=300)
    w.add_argument("--no-progress-warn-after", type=int, default=0,
                   help="warn when no progress/run event advances within N seconds (0 disables)")
    w.add_argument("--no-progress-block-after", type=int, default=0,
                   help="block this companion loop when no progress/run event advances within N seconds (0 disables)")
    w.add_argument("--once", action="store_true")
    w.add_argument("--takeover-stale", action="store_true",
                   help="explicitly take over a different session only when its lane is stale")
    w.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    w.add_argument("--no-notify", action="store_true",
                   help="do not emit local notifications from this watch loop")
    w.add_argument("--json", action="store_true")
    w.set_defaults(fn=cmd_watch)

    nt = sub.add_parser("notify", help="one-shot local notification or notification config")
    nt.add_argument("target", help="agent name, or 'config' for notification settings")
    nt.add_argument("--event", choices=tuple(sorted(NOTIFY_EVENTS)), default="")
    nt.add_argument("--message", default="")
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
    nt.add_argument("--json", action="store_true")
    nt.set_defaults(fn=cmd_notify)

    op = sub.add_parser("operator", help="queue an operator message for one agent lane")
    op.add_argument("agent")
    op.add_argument("--mode", choices=("followup", "collect", "interrupt", "status"), required=True)
    op.add_argument("--idempotency-key", default="")
    op.add_argument("message")
    op.set_defaults(fn=cmd_operator)

    pr = sub.add_parser("progress", help="append a long-turn progress note")
    pr.add_argument("agent")
    pr.add_argument("--run", required=True)
    pr.add_argument("message")
    pr.set_defaults(fn=cmd_progress)

    sr = sub.add_parser("status-runtime", help="show relay status plus runtime sidecars")
    sr.add_argument("agent", nargs="?")
    sr.add_argument("--brief", action="store_true", help="compact human output; ignored with --json")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(fn=cmd_status_runtime)

    hr = sub.add_parser("headroom", help="estimate context-window headroom from local proxy signals")
    hr.add_argument("agent", nargs="?", help="agent to authorize optional pause/checkpoint actions")
    hr.add_argument("--json", action="store_true")
    hr.add_argument("--checkpoint", action="store_true",
                    help="write a derived session-report checkpoint and record it in runtime runs")
    hr.add_argument("--pause-on", choices=("warning", "high"), default="",
                    help="if the computed risk reaches this level, checkpoint and pause the current holder")
    hr.add_argument("--reason", default="", help="required with --pause-on; recorded in checkpoint/pause audit")
    hr.add_argument("--window-status", choices=("ok", "warning", "high"), default="",
                    help="optional harness-provided exact context-window signal")
    hr.add_argument("--window-reason", default="", help="reason attached to --window-status warning/high")
    hr.add_argument("--warn-after-turns-since-checkpoint", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_turns_since_checkpoint"])
    hr.add_argument("--warn-after-handoff-body-bytes", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_handoff_body_bytes"])
    hr.add_argument("--warn-after-relay-bytes", type=int,
                    default=HEADROOM_DEFAULTS["warn_after_relay_bytes"])
    hr.add_argument("--pause-recommendation-after-turns-since-checkpoint", type=int,
                    default=HEADROOM_DEFAULTS["pause_recommendation_after_turns_since_checkpoint"])
    hr.add_argument("--pause-recommendation-after-relay-bytes", type=int,
                    default=HEADROOM_DEFAULTS["pause_recommendation_after_relay_bytes"])
    hr.set_defaults(fn=cmd_headroom)

    dr = sub.add_parser("doctor", help="read-only runtime sidecar diagnostics")
    dr.add_argument("--json", action="store_true")
    dr.add_argument("--stale-after", type=int, default=300)
    dr.set_defaults(fn=cmd_doctor)

    pv = sub.add_parser("providers", help="local provider/agent registry")
    pv_sub = pv.add_subparsers(dest="verb", required=True)
    pvi = pv_sub.add_parser("init", help="write .m8shift/providers.json")
    pvi.add_argument("--agents", default="", help="comma-separated roster for provider defaults")
    pvi.add_argument("--force", action="store_true")
    pvi.set_defaults(fn=cmd_providers_init)
    pvl = pv_sub.add_parser("list", help="list provider entries")
    pvl.add_argument("--json", action="store_true")
    pvl.set_defaults(fn=cmd_providers_list)
    pvs = pv_sub.add_parser("show", help="show one provider entry as JSON")
    pvs.add_argument("agent")
    pvs.set_defaults(fn=cmd_providers_show)
    pvc = pv_sub.add_parser("check", help="validate provider registry")
    pvc.add_argument("agent", nargs="?")
    pvc.add_argument("--json", action="store_true")
    pvc.set_defaults(fn=cmd_providers_check)
    pvr = pv_sub.add_parser("render", help="render one provider argv array without shell interpolation")
    pvr.add_argument("agent")
    pvr.add_argument("--prompt", required=True)
    pvr.add_argument("--run", default="")
    pvr.add_argument("--json", action="store_true")
    pvr.set_defaults(fn=cmd_providers_render)

    roles = sub.add_parser("roles", help="runtime role contracts")
    roles_sub = roles.add_subparsers(dest="verb", required=True)
    rl = roles_sub.add_parser("list")
    rl.add_argument("--json", action="store_true")
    rl.set_defaults(fn=cmd_roles_list)
    rs = roles_sub.add_parser("show")
    rs.add_argument("name")
    rs.set_defaults(fn=cmd_roles_show)

    workflows = sub.add_parser("workflows", help="runtime workflow definitions")
    workflows_sub = workflows.add_subparsers(dest="verb", required=True)
    wl = workflows_sub.add_parser("list")
    wl.add_argument("--json", action="store_true")
    wl.set_defaults(fn=cmd_workflows_list)
    ws = workflows_sub.add_parser("show")
    ws.add_argument("name")
    ws.set_defaults(fn=cmd_workflows_show)

    ap = sub.add_parser("approve", help="append one local approval decision")
    ap.add_argument("run")
    ap.add_argument("gate")
    ap.add_argument("--by", required=True)
    ap.add_argument("--decision", choices=("approved", "rejected", "waived"), required=True)
    ap.add_argument("--reason", default="")
    ap.set_defaults(fn=cmd_approve)

    rp = sub.add_parser("report", help="summarize one local runtime run")
    rp.add_argument("run")
    rp.add_argument("--json", action="store_true")
    rp.add_argument("--write", action="store_true", help="write .m8shift/runs/<run>/report.md")
    rp.set_defaults(fn=cmd_report)

    retention = sub.add_parser("retention", help="bounded runtime sidecar retention")
    ret_sub = retention.add_subparsers(dest="verb", required=True)
    rprune = ret_sub.add_parser("prune", help="prune runtime JSONL ledgers to a fixed row cap")
    rprune.add_argument("--keep", type=int, default=1000, help="rows to retain per ledger (default: 1000)")
    rprune.add_argument("--no-archive", action="store_true",
                        help="discard pruned rows instead of appending them under .m8shift/runtime/archive/")
    rprune.add_argument("--json", action="store_true")
    rprune.set_defaults(fn=cmd_retention_prune)
    rapp = ret_sub.add_parser("apply", help="apply .m8shift/runtime/retention.json policy")
    rapp.add_argument("--dry-run", action="store_true", help="show planned pruning without changing files")
    rapp.add_argument("--no-archive", action="store_true",
                      help="discard pruned rows instead of archiving them")
    rapp.add_argument("--json", action="store_true")
    rapp.set_defaults(fn=cmd_retention_apply)
    rpolicy = ret_sub.add_parser("policy", help="inspect runtime retention policy")
    rpolicy_sub = rpolicy.add_subparsers(dest="policy_verb", required=True)
    rpshow = rpolicy_sub.add_parser("show", help="show effective retention policy")
    rpshow.add_argument("--json", action="store_true")
    rpshow.set_defaults(fn=cmd_retention_policy_show)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
