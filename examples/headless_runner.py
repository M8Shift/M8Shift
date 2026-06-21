#!/usr/bin/env python3
"""Example headless runner for CoWork — REFERENCE, not part of `cowork.py`.

`cowork.py` is a passive coordinator: `wait` blocks a *process*, it cannot wake an
interactive agent UI (VS Code, …). The only way to a fully hands-off relay is to drive
a **headless** agent (e.g. `claude -p "<prompt>"`, `codex exec "<prompt>"`) in a loop.
This script is that loop, for ONE agent. Run one instance per headless agent; if the
other side is an interactive UI, a human still resumes it (that side stays manual).

Design (the points a naive `while wait; do …` loop gets wrong):
  * It reads the LOCK `state` directly (a stable `key: value`) instead of `wait`'s
    return code, because `wait` returns rc 0 for BOTH "your turn" and `DONE` — a naive
    loop would relaunch forever at `DONE`.
  * A **designated IDLE starter** (`--start-on-idle`) avoids two agents both starting
    from `IDLE`.
  * **Post-run validation**: if the agent process exits while the pen is still
    `WORKING_<me>` (it claimed then died without `append`), that is a crash → retry,
    up to a cap, then stop and leave the pen for manual recovery (never force-steals).
  * **Bounded backoff + retry cap**, and **static argv** (no shell eval).

Usage:
  examples/headless_runner.py claude --cmd claude -p "Apply COWORK.protocol.md: take your
      turn (claim, work, append)." [--start-on-idle] [--interval 30] [--max-retries 3]

The agent command (everything after --cmd) is run verbatim as argv; it must, by itself,
perform exactly one turn against this project's COWORK.md (claim → work → append).
"""
import argparse
import os
import re
import subprocess
import sys
import time

LOCK_BEGIN = "<!-- COWORK:LOCK:BEGIN -->"
LOCK_END = "<!-- COWORK:LOCK:END -->"


def read_lock(cowork_path):
    """Return the LOCK fields as a dict, or None if the file/markers are missing."""
    try:
        with open(cowork_path, encoding="utf-8") as f:
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
    print(f"[cowork-runner] {msg}", flush=True)


def main():
    p = argparse.ArgumentParser(description="Headless CoWork runner for one agent.")
    p.add_argument("agent", help="your agent name (must be in the COWORK.md roster)")
    p.add_argument("--cowork", default="COWORK.md", help="path to COWORK.md")
    p.add_argument("--start-on-idle", action="store_true",
                   help="this agent starts the relay when state is IDLE (designate ONE)")
    p.add_argument("--interval", type=int, default=30, help="poll seconds when waiting")
    p.add_argument("--max-retries", type=int, default=3,
                   help="consecutive failed turns before giving up")
    p.add_argument("--max-backoff", type=int, default=120, help="cap on backoff seconds")
    p.add_argument("--cmd", nargs=argparse.REMAINDER, required=True,
                   help="the headless agent command (static argv; runs ONE turn)")
    args = p.parse_args()
    if not args.cmd:
        p.error("--cmd requires the agent command (e.g. --cmd claude -p \"...\")")

    me = args.agent.lower()
    me_working = f"WORKING_{me.upper()}"
    me_awaiting = f"AWAITING_{me.upper()}"
    fails = 0

    while True:
        lk = read_lock(args.cowork)
        if lk is None:
            log(f"{args.cowork}: not found / invalid LOCK — is the project init'd? waiting.")
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
        try:
            subprocess.run(args.cmd, check=False)
        except OSError as e:
            log(f"could not launch the agent: {e}")
            return 2

        # Post-run validation against the new state.
        after = read_lock(args.cowork) or {}
        progressed = (after.get("turn") != lk.get("turn")
                      or after.get("state") not in (state, me_working))
        if after.get("state") == me_working and after.get("holder") == me:
            # claimed but exited without append → crashed mid-turn.
            fails += 1
            log(f"agent exited holding the pen (crash {fails}/{args.max_retries}).")
        elif progressed:
            fails = 0  # a turn was posted / the state advanced — real progress.
        else:
            fails += 1
            log(f"agent ran but did not take the turn ({fails}/{args.max_retries}).")

        if fails >= args.max_retries:
            log("retry cap reached — stopping; leaving the pen for manual recovery.")
            return 1
        if fails:
            time.sleep(min(args.interval * (2 ** fails), args.max_backoff))


if __name__ == "__main__":
    sys.exit(main())
