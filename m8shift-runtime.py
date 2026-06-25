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
import subprocess
import sys
import time
import uuid

VERSION = "3.15.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CORE_PATH = os.path.join(HERE, "m8shift.py")
RUNTIME_DIR = os.path.join(HERE, ".m8shift", "runtime")
PRESENCE = os.path.join(RUNTIME_DIR, "presence.json")
RUNS = os.path.join(RUNTIME_DIR, "runs.jsonl")
PROGRESS = os.path.join(RUNTIME_DIR, "progress.jsonl")
IDEMPOTENCY = os.path.join(RUNTIME_DIR, "idempotency.jsonl")
INBOX_DIR = os.path.join(RUNTIME_DIR, "inbox")
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")


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
            return any(line.strip() == ".m8shift/" for line in fh)
    except OSError:
        return False


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

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
