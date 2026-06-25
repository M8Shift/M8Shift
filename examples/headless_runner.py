#!/usr/bin/env python3
"""Example headless runner for M8Shift — REFERENCE, not part of `m8shift.py`.

`m8shift.py` is a passive coordinator: `wait` blocks a *process*, it cannot wake an
interactive agent UI (VS Code, …). The only way to a fully hands-off relay is to drive
a **headless** agent (e.g. `claude -p "<prompt>"`, `codex exec "<prompt>"`) in a loop.
This script is that loop, for ONE agent. Run one instance per headless agent; if the
other side is an interactive UI, a human still resumes it (that side stays manual).
`claude` and `codex` are only examples: the same wrapper pattern works with Gemini,
Vibe, or any cooperative agent CLI that can perform one M8Shift turn.

Design (the points a naive `while wait; do …` loop gets wrong):
  * It reads the LOCK `state` directly (a stable `key: value`) instead of `wait`'s
    return code, because `wait --once` returns rc 0 for BOTH "your turn" and `DONE` — a
    naive loop would relaunch forever at `DONE`.
  * A **designated IDLE starter** (`--start-on-idle`) avoids two agents both starting
    from `IDLE`.
  * **Heartbeat for long turns**: while the agent process is running, if this
    runner sees `WORKING_<me>` with less than 5 minutes before `expires`, it runs
    `python3 m8shift.py claim <me>` to refresh the TTL. This is a manual heartbeat:
    it extends only the holder's own lock and never steals another agent's pen.
  * **Post-run validation**: if the agent process exits while the pen is still
    `WORKING_<me>` (it claimed then died without `append`), that is a crash → retry,
    up to a cap, then stop and leave the pen for manual recovery (never force-steals).
  * **Run ledger**: every launched turn receives `M8SHIFT_RUN_ID` in the child
    environment and appends lifecycle events to `.m8shift/runtime/runs.jsonl`.
  * **Bounded backoff + retry cap**, and **static argv** (no shell eval).

Usage:
  examples/headless_runner.py claude --cmd claude -p "Apply M8SHIFT.protocol.md: take your
      turn (claim, work, append)." [--start-on-idle] [--interval 30] [--max-retries 3]

The agent command (everything after --cmd) is run verbatim as argv; it must, by itself,
perform exactly one turn against this project's M8SHIFT.md (claim → work → append).
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import uuid

LOCK_BEGIN = "<!-- M8SHIFT:LOCK:BEGIN -->"
LOCK_END = "<!-- M8SHIFT:LOCK:END -->"
VERSION = "3.18.3"
DEFAULT_HEARTBEAT_MARGIN_S = 5 * 60
AGENT_RE = re.compile(r"[a-z][a-z0-9_-]*\Z")


def read_lock(m8shift_path):
    """Return the LOCK fields as a dict, or None if the file/markers are missing."""
    try:
        with open(m8shift_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if LOCK_BEGIN not in text or LOCK_END not in text:
        return None
    body = text[text.index(LOCK_BEGIN) + len(LOCK_BEGIN):text.index(LOCK_END)]
    fields = {}
    for line in body.splitlines():
        m = re.match(r"([a-z_]+):\s*(.*)$", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def log(msg):
    print(f"[m8shift-runner] {msg}", flush=True)


def iso_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id(agent):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{agent}-{uuid.uuid4().hex[:8]}"


def append_run_event(args, event, run_id, agent, **fields):
    """Append one local runtime event.

    This is a companion-side diagnostic ledger, not core state. It never touches
    `M8SHIFT.md` and never grants or routes the pen.
    """
    if args.no_run_log:
        return
    row = {
        "event": event,
        "run_id": run_id,
        "agent": agent,
        "ts": iso_now(),
        "runner_version": VERSION,
    }
    row.update(fields)
    os.makedirs(args.runtime_dir, exist_ok=True)
    path = os.path.join(args.runtime_dir, "runs.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def validate_args(args):
    if not AGENT_RE.fullmatch(args.agent.lower()):
        raise SystemExit("invalid agent name: expected [a-z][a-z0-9_-]*")
    if args.interval < 1:
        raise SystemExit("--interval must be >= 1")
    if args.max_retries < 1:
        raise SystemExit("--max-retries must be >= 1")
    if args.max_backoff < 1:
        raise SystemExit("--max-backoff must be >= 1")
    if args.heartbeat_before_expiry < 0:
        raise SystemExit("--heartbeat-before-expiry must be >= 0")
    if args.turn_timeout < 0:
        raise SystemExit("--turn-timeout must be >= 0")
    if args.kill_grace < 0:
        raise SystemExit("--kill-grace must be >= 0")


def stop_child(proc, grace):
    """Terminate a timed-out child, then kill after the grace window."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def parse_iso_z(value):
    """Parse M8Shift's UTC `...Z` timestamp, returning None for absent/invalid values."""
    if not value or value == "-":
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        out = dt.datetime.fromisoformat(value)
        if out.tzinfo is None:
            out = out.replace(tzinfo=dt.timezone.utc)
        return out.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def maybe_refresh_ttl(args, me, me_working, run_id):
    """Refresh our own working lock when expiry is close. Never force-steals."""
    margin = max(0, args.heartbeat_before_expiry)
    if margin == 0:
        return
    lk = read_lock(args.m8shift) or {}
    if lk.get("state") != me_working or lk.get("holder") != me:
        return
    exp = parse_iso_z(lk.get("expires"))
    if exp is None:
        return
    remaining = (exp - dt.datetime.now(dt.timezone.utc)).total_seconds()
    if remaining > margin:
        return
    cmd = [sys.executable, args.m8shift_py, "claim", me]
    try:
        r = subprocess.run(cmd, check=False, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        log(f"heartbeat failed to launch {args.m8shift_py}: {e}")
        return
    if r.returncode == 0:
        log(f"heartbeat refreshed TTL ({remaining:.0f}s remained).")
        append_run_event(args, "run.heartbeat", run_id, me, remaining_seconds=int(remaining))
    else:
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        detail = detail[0] if detail else f"rc={r.returncode}"
        log(f"heartbeat refresh failed: {detail}")
        append_run_event(args, "run.heartbeat_failed", run_id, me, detail=detail)


def main():
    p = argparse.ArgumentParser(description="Headless M8Shift runner for one agent.")
    p.add_argument("--version", action="version", version=f"headless_runner.py {VERSION}")
    p.add_argument("agent", help="your agent name (must be in the M8SHIFT.md roster)")
    p.add_argument("--m8shift", default="M8SHIFT.md", help="path to M8SHIFT.md")
    p.add_argument("--start-on-idle", action="store_true",
                   help="this agent starts the relay when state is IDLE (designate ONE)")
    p.add_argument("--interval", type=int, default=30, help="poll seconds when waiting")
    p.add_argument("--max-retries", type=int, default=3,
                   help="consecutive failed turns before giving up")
    p.add_argument("--max-backoff", type=int, default=120, help="cap on backoff seconds")
    p.add_argument("--m8shift-py", default="m8shift.py",
                   help="path to m8shift.py used for heartbeat TTL refreshes")
    p.add_argument("--heartbeat-before-expiry", type=int, default=DEFAULT_HEARTBEAT_MARGIN_S,
                   help="seconds before expires to refresh while working; default 300 (5 min), 0 disables")
    p.add_argument("--turn-timeout", type=int, default=0,
                   help="maximum seconds for one agent turn; 0 disables timeout")
    p.add_argument("--kill-grace", type=int, default=10,
                   help="seconds to wait after terminate before kill on timeout")
    p.add_argument("--runtime-dir", default=os.path.join(".m8shift", "runtime"),
                   help="local runtime sidecar dir for runs.jsonl (default: .m8shift/runtime)")
    p.add_argument("--no-run-log", action="store_true",
                   help="disable .m8shift/runtime/runs.jsonl lifecycle logging")
    p.add_argument("--once", action="store_true",
                   help="run at most one eligible turn, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="validate configuration, print the command argv as JSON, then exit")
    p.add_argument("--cmd", nargs=argparse.REMAINDER, required=True,
                   help="the headless agent command (static argv; runs ONE turn)")
    args = p.parse_args()
    if not args.cmd:
        p.error("--cmd requires the agent command (e.g. --cmd claude -p \"...\")")
    validate_args(args)

    me = args.agent.lower()
    me_working = f"WORKING_{me.upper()}"
    me_awaiting = f"AWAITING_{me.upper()}"
    fails = 0
    if args.dry_run:
        print(json.dumps({"agent": me, "cmd": args.cmd, "runner_version": VERSION}, sort_keys=True))
        return 0

    while True:
        lk = read_lock(args.m8shift)
        if lk is None:
            log(f"{args.m8shift}: not found / invalid LOCK — is the project init'd? waiting.")
            time.sleep(args.interval)
            continue
        state = lk.get("state", "")

        if state == "DONE":
            log("session DONE — exiting.")
            return 0

        my_turn = state == me_awaiting or (state == "IDLE" and args.start_on_idle)
        if not my_turn:
            time.sleep(args.interval)
            continue

        # It is our turn: run the headless agent for exactly one turn (static argv).
        log(f"state={state} → running the agent for one turn.")
        run_id = new_run_id(me)
        append_run_event(args, "run.started", run_id, me, relay_state=state, relay_turn=lk.get("turn", ""))
        child_env = dict(os.environ)
        child_env.update({
            "M8SHIFT_RUN_ID": run_id,
            "M8SHIFT_AGENT": me,
            "M8SHIFT_TURN": lk.get("turn", ""),
        })
        try:
            proc = subprocess.Popen(args.cmd, env=child_env)
        except OSError as e:
            log(f"could not launch the agent: {e}")
            append_run_event(args, "run.launch_failed", run_id, me, detail=str(e))
            return 2
        started = time.monotonic()
        timed_out = False
        while True:
            elapsed = time.monotonic() - started
            if args.turn_timeout and elapsed > args.turn_timeout:
                timed_out = True
                log(f"turn timeout after {args.turn_timeout}s; terminating child.")
                stop_child(proc, args.kill_grace)
                append_run_event(args, "run.timeout", run_id, me, timeout_seconds=args.turn_timeout)
                break
            wait_for = min(args.interval, 30)
            if args.turn_timeout:
                wait_for = max(0.1, min(wait_for, args.turn_timeout - elapsed))
            try:
                proc.wait(timeout=wait_for)
                break
            except subprocess.TimeoutExpired:
                maybe_refresh_ttl(args, me, me_working, run_id)

        # Post-run validation against the new state.
        after = read_lock(args.m8shift) or {}
        progressed = (after.get("turn") != lk.get("turn")
                      or after.get("state") not in (state, me_working))
        if timed_out:
            fails += 1
            append_run_event(args, "run.ended", run_id, me, status="timeout",
                             returncode=proc.returncode, relay_state=after.get("state", ""),
                             relay_turn=after.get("turn", ""))
        elif after.get("state") == me_working and after.get("holder") == me:
            # claimed but exited without append → crashed mid-turn.
            fails += 1
            log(f"agent exited holding the pen (crash {fails}/{args.max_retries}).")
            append_run_event(args, "run.ended", run_id, me, status="stuck_working",
                             returncode=proc.returncode, relay_state=after.get("state", ""),
                             relay_turn=after.get("turn", ""))
        elif progressed:
            fails = 0  # a turn was posted / the state advanced — real progress.
            status = "ok" if proc.returncode == 0 else "progressed_with_error"
            append_run_event(args, "run.ended", run_id, me, status=status,
                             returncode=proc.returncode, relay_state=after.get("state", ""),
                             relay_turn=after.get("turn", ""))
            if args.once:
                return 0
        else:
            fails += 1
            log(f"agent ran but did not take the turn ({fails}/{args.max_retries}).")
            append_run_event(args, "run.ended", run_id, me, status="no_progress",
                             returncode=proc.returncode, relay_state=after.get("state", ""),
                             relay_turn=after.get("turn", ""))

        if fails >= args.max_retries:
            log("retry cap reached — stopping; leaving the pen for manual recovery.")
            append_run_event(args, "run.retry_cap", run_id, me, failures=fails)
            return 1
        if args.once:
            return 1
        if fails:
            time.sleep(min(args.interval * (2 ** fails), args.max_backoff))


if __name__ == "__main__":
    sys.exit(main())
