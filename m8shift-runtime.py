#!/usr/bin/env python3
"""m8shift-runtime.py — optional local runtime companion for M8Shift.

The companion records local presence, operator messages, and progress sidecars
under `.m8shift/runtime/`. It never edits `M8SHIFT.md` directly and never becomes
an authority for the pen; all routing remains owned by `m8shift.py`.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

VERSION = "3.16.0"
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
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
AGENT_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")
ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
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
        "argv": [],
        "capabilities": DEFAULT_CAPABILITIES.get(agent, ["read_repo", "review"]),
        "requires_env": [],
        "permissions": "human-driven",
    }
    if agent == "codex":
        provider["argv"] = ["codex", "exec", "$M8SHIFT_PROMPT"]
        provider["permissions"] = "workspace-write"
    return provider


def default_provider_registry(agents):
    return {
        "schema": "m8shift.providers.v1",
        "generated_by": f"m8shift-runtime.py {VERSION}",
        "agents": [provider_template(agent) for agent in agents],
    }


RUNTIME_README = """# M8Shift runtime companion

This directory is optional. It belongs to `m8shift-runtime.py`, not to the passive
core relay.

- `providers.json`: host-side agent/provider registry. Keep secrets out of it.
- `roles/`: stable behavioral role contracts.
- `workflows/`: simple local workflow definitions.
- `policies/`: human approval and runtime policy notes.
- `runtime/`, `runs/`, `cache/`, `tmp/`: generated state; keep ignored.

The runtime companion never edits `M8SHIFT.md` directly and never owns the pen.
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


def validate_session_id(session_id):
    if not SESSION_RE.fullmatch(session_id):
        sys.exit("m8shift-runtime: unsafe --session value")
    return session_id


def load_status(core):
    text = core.load_or_die()
    lk = core.get_lock(text)
    return text, lk


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


def update_presence(core, agent, session_id, mode, state, run_id="", stale_after=300, force=False):
    validate_agent(core, agent)
    presence = read_json(PRESENCE, {})
    existing = presence.get(agent)
    if (existing and existing.get("session_id") != session_id
            and fresh_presence(existing, stale_after) and not force):
        sys.exit(
            f"m8shift-runtime: lane {agent!r} is already owned by session "
            f"{existing.get('session_id')!r}; rerun with --force after verifying it is stale"
        )
    _, lk = load_status(core)
    presence[agent] = {
        "session_id": session_id,
        "run_id": run_id,
        "mode": mode,
        "state": state,
        "relay_state": lk.get("state", ""),
        "holder": lk.get("holder", ""),
        "turn": lk.get("turn", ""),
        "last_seen": iso(),
        "cwd": HERE,
        "pid": os.getpid(),
        "m8shift_version": getattr(core, "VERSION", ""),
        "runtime_version": VERSION,
    }
    atomic_write_json(PRESENCE, presence)
    return presence[agent]


def run_core_json(*args):
    r = subprocess.run([sys.executable, CORE_PATH, *args], cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return json.loads(r.stdout)


def cmd_watch(args):
    if args.interval < 1:
        sys.exit("m8shift-runtime: --interval must be >= 1")
    core = load_core()
    agent = validate_agent(core, args.agent)
    session_id = validate_session_id(args.session or f"{agent}-{uuid.uuid4().hex[:8]}")
    run_id = args.run or f"{iso().replace('-', '').replace(':', '')}-{agent}-{uuid.uuid4().hex[:6]}"
    while True:
        _, lk = load_status(core)
        state = relay_runtime_state(lk, agent)
        row = update_presence(
            core, agent, session_id, "ui-watch", state,
            run_id=run_id, stale_after=args.stale_after, force=args.force,
        )
        prompt = ""
        if lk.get("state") in ("IDLE", f"AWAITING_{agent.upper()}"):
            prompt = f"python3 m8shift.py next {agent}"
        if args.json:
            print(json.dumps({"presence": row, "resume_prompt": prompt}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{iso()} {agent} runtime={state} relay={lk.get('state')} holder={lk.get('holder')}")
            if prompt:
                print(f"resume: {prompt}")
        if args.once:
            return 0
        time.sleep(args.interval)


def idempotency_seen(key):
    if not key:
        return False
    return any(row.get("key") == key for row in read_jsonl(IDEMPOTENCY))


def record_idempotency(key, action):
    if key:
        append_jsonl(IDEMPOTENCY, {"type": "idempotency.recorded", "key": key, "action": action, "ts": iso()})


def cmd_operator(args):
    core = load_core()
    agent = validate_agent(core, args.agent)
    if args.idempotency_key and idempotency_seen(args.idempotency_key):
        print(f"duplicate ignored: idempotency key {args.idempotency_key}")
        return 0
    row = {
        "type": "operator.message",
        "agent": agent,
        "mode": args.mode,
        "message": args.message,
        "idempotency_key": args.idempotency_key or "",
        "ts": iso(),
    }
    append_jsonl(os.path.join(INBOX_DIR, f"{agent}.jsonl"), row)
    record_idempotency(args.idempotency_key, "operator")
    print(f"✓ queued {args.mode} message for {agent}")
    return 0


def cmd_progress(args):
    core = load_core()
    agent = validate_agent(core, args.agent)
    row = {
        "type": "progress",
        "agent": agent,
        "run_id": args.run,
        "message": args.message,
        "ts": iso(),
    }
    append_jsonl(PROGRESS, row)
    print(f"✓ progress recorded for {agent}/{args.run}")
    return 0


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
        prefix = f"agents[{idx}]"
        if not isinstance(agent, dict):
            findings.append({"severity": "error", "check": "providers.agent", "message": f"{prefix} is not an object"})
            continue
        name = agent.get("name", "")
        if not isinstance(name, str) or not AGENT_RE.fullmatch(name):
            findings.append({"severity": "error", "check": "providers.name", "message": f"{prefix}.name is invalid"})
        elif name in seen:
            findings.append({"severity": "error", "check": "providers.name_duplicate", "message": f"duplicate agent {name}"})
        seen.add(name)
        if not isinstance(agent.get("provider", ""), str) or not agent.get("provider", "").strip():
            findings.append({"severity": "error", "check": "providers.provider", "message": f"{name or prefix} provider is required"})
        mode = agent.get("mode", "")
        if mode not in PROVIDER_MODES:
            findings.append({"severity": "error", "check": "providers.mode", "message": f"{name or prefix} mode must be one of {', '.join(sorted(PROVIDER_MODES))}"})
        if not isinstance(agent.get("anchor", ""), str) or not agent.get("anchor", "").strip():
            findings.append({"severity": "warning", "check": "providers.anchor", "message": f"{name or prefix} anchor is missing"})
        argv = agent.get("argv", [])
        if isinstance(argv, str):
            findings.append({"severity": "error", "check": "providers.argv_string", "message": f"{name or prefix} argv must be an array, not a shell string"})
        elif not isinstance(argv, list) or not all(isinstance(v, str) and v for v in argv):
            findings.append({"severity": "error", "check": "providers.argv", "message": f"{name or prefix} argv must be a list of non-empty strings"})
        elif mode in {"headless", "hybrid"} and not argv:
            findings.append({"severity": "warning", "check": "providers.argv_missing", "message": f"{name or prefix} has mode={mode} but no argv"})
        elif argv and "/" not in argv[0] and shutil.which(argv[0]) is None:
            findings.append({"severity": "warning", "check": "providers.executable_missing", "message": f"{name or prefix} executable {argv[0]!r} not found on PATH"})
        for field in ("capabilities", "requires_env"):
            values = agent.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
                findings.append({"severity": "error", "check": f"providers.{field}", "message": f"{name or prefix} {field} must be a list of strings"})
        for env_name in agent.get("requires_env", []):
            if not ENV_RE.fullmatch(env_name):
                findings.append({"severity": "error", "check": "providers.env_name", "message": f"{name or prefix} has invalid env var name {env_name!r}"})
            elif env_name not in os.environ:
                findings.append({"severity": "error", "check": "providers.env_missing", "message": f"{name or prefix} requires missing environment variable {env_name}"})
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
    values = {
        "$M8SHIFT_PROMPT": prompt,
        "$M8SHIFT_AGENT": row.get("name", ""),
        "$M8SHIFT_RUN_ID": run_id,
    }
    argv = []
    for arg in row.get("argv", []):
        out = arg
        for marker, value in values.items():
            out = out.replace(marker, value)
        argv.append(out)
    return argv


def cmd_providers_render(args):
    names = parse_agent_csv(args.agent)
    row = provider_by_name(names[0]) if names else None
    if not row:
        sys.exit(f"m8shift-runtime: no provider entry for {args.agent}")
    if any(f["severity"] == "error" for f in provider_findings({"schema": "m8shift.providers.v1", "agents": [row]})):
        sys.exit(f"m8shift-runtime: provider entry for {args.agent} is invalid")
    if not row.get("argv"):
        sys.exit(f"m8shift-runtime: provider entry for {args.agent} has no argv")
    argv = render_provider_argv(row, args.prompt, args.run)
    payload = {"agent": row.get("name"), "argv": argv, "mode": row.get("mode"), "provider": row.get("provider")}
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
    row = {
        "type": "approval",
        "run_id": args.run,
        "gate_id": args.gate,
        "by": by,
        "decision": args.decision,
        "reason": args.reason,
        "ts": iso(),
    }
    append_jsonl(APPROVALS, row)
    print(f"✓ approval recorded for {args.run}/{args.gate}: {args.decision}")
    return 0


def cmd_report(args):
    events = [row for row in read_jsonl(RUNS) if row.get("run_id") == args.run]
    progress = [row for row in read_jsonl(PROGRESS) if row.get("run_id") == args.run]
    approvals = [row for row in read_jsonl(APPROVALS) if row.get("run_id") == args.run]
    payload = {
        "run_id": args.run,
        "events": events,
        "progress": progress,
        "approvals": approvals,
        "runtime_version": VERSION,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    lines = [
        f"# M8Shift run report — {args.run}",
        "",
        f"- events: {len(events)}",
        f"- progress notes: {len(progress)}",
        f"- approvals: {len(approvals)}",
        "",
    ]
    for row in events:
        lines.append(f"- event `{row.get('event', row.get('type', '?'))}` at {row.get('ts', '-')}: {row.get('status', row.get('relay_state', ''))}")
    for row in progress:
        lines.append(f"- progress at {row.get('ts', '-')}: {row.get('message', '')}")
    for row in approvals:
        lines.append(f"- approval `{row.get('gate_id')}` by {row.get('by')}: {row.get('decision')} — {row.get('reason', '')}")
    report = "\n".join(lines).rstrip() + "\n"
    if args.write:
        out_dir = os.path.join(RUN_REPORTS_DIR, args.run)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(path)
    else:
        print(report, end="")
    return 0


def runtime_summary(agent=""):
    presence = read_json(PRESENCE, {})
    progress = read_jsonl(PROGRESS)
    agents = [agent] if agent else sorted(presence)
    out = {}
    for ag in agents:
        inbox = read_jsonl(os.path.join(INBOX_DIR, f"{ag}.jsonl"))
        last_progress = next((row for row in reversed(progress) if row.get("agent") == ag), None)
        out[ag] = {
            "presence": presence.get(ag),
            "inbox_count": len(inbox),
            "last_progress": last_progress,
        }
    return out


def cmd_status_runtime(args):
    core = load_core()
    agent = validate_agent(core, args.agent) if args.agent else ""
    status = run_core_json("status", "--json")
    summary = runtime_summary(agent)
    if args.json:
        print(json.dumps({
            "m8shift_version": status.get("m8shift_version"),
            "runtime_version": VERSION,
            "relay": status,
            "runtime": summary,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"m8shift-runtime.py v{VERSION}")
    print(f"relay: {status.get('state')} holder={status.get('holder')} turn={status.get('turn')}")
    for ag, data in summary.items():
        pres = data.get("presence") or {}
        print(
            f"{ag}: presence={pres.get('state', '-')} session={pres.get('session_id', '-')} "
            f"inbox={data.get('inbox_count', 0)}"
        )
        if data.get("last_progress"):
            print(f"  last progress: {data['last_progress'].get('message')} ({data['last_progress'].get('ts')})")
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
    for path in (PRESENCE,):
        if os.path.exists(path):
            try:
                read_json(path, {})
            except SystemExit as e:
                findings.append({"severity": "warning", "check": "runtime.json", "message": str(e)})
    for path in (RUNS, PROGRESS, IDEMPOTENCY):
        if os.path.exists(path):
            try:
                read_jsonl(path)
            except (OSError, ValueError) as e:
                findings.append({"severity": "warning", "check": "runtime.jsonl", "message": str(e)})
    if os.path.isdir(INBOX_DIR):
        for name in os.listdir(INBOX_DIR):
            if name.endswith(".jsonl"):
                try:
                    read_jsonl(os.path.join(INBOX_DIR, name))
                except (OSError, ValueError) as e:
                    findings.append({"severity": "warning", "check": "runtime.inbox", "message": str(e)})
    presence = read_json(PRESENCE, {})
    for agent, row in presence.items():
        if not fresh_presence(row, args.stale_after):
            findings.append({
                "severity": "info",
                "check": "runtime.presence_stale",
                "message": f"{agent} runtime presence is stale",
            })
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
    w.add_argument("--once", action="store_true")
    w.add_argument("--force", action="store_true", help="take over a fresh lane after human verification")
    w.add_argument("--json", action="store_true")
    w.set_defaults(fn=cmd_watch)

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
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(fn=cmd_status_runtime)

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

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
