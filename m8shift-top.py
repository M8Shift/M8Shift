#!/usr/bin/env python3
"""Read-only, dependency-free dashboard for the M8Shift status snapshot."""
import argparse
import atexit
import json
import os
import shutil
import signal
import select
import subprocess
import sys
import time
from datetime import datetime, timezone

VERSION = "3.60.0"  # lockstep with m8shift.py; required for companion install/update

ALT_ON = "\x1b[?1049h\x1b[?25l"
ALT_OFF = "\x1b[?25h\x1b[?1049l"
HOME = "\x1b[H"
SCHEMA_MAJOR = 1
_active = False


def restore(stream=None):
    global _active
    if _active:
        (stream or sys.stdout).write(ALT_OFF)
        (stream or sys.stdout).flush()
        _active = False


def enter(stream=None):
    global _active
    stream = stream or sys.stdout
    stream.write(ALT_ON)
    stream.flush()
    _active = True


def clean(value, width):
    text = value if isinstance(value, str) and value else "unavailable"
    text = "".join(c for c in text if ord(c) >= 32 and not 127 <= ord(c) <= 159)
    return text[:max(0, width)]


def _value(value):
    return "unavailable" if value is None else str(value)


def _color(code, text, enabled):
    return "\x1b[%sm%s\x1b[0m" % (code, text) if enabled else text


def _stamp(value):
    if not value or value == "-":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def render(snapshot, width, now=None):
    width = max(24, width)
    inner = width - 2
    colored = "NO_COLOR" not in os.environ
    amber = lambda text: _color("33", text, colored)
    dim = lambda text: _color("2", text, colored)
    badge = lambda text: _color("7", text, colored)

    def row(text="", style=None):
        plain = clean(str(text), inner)
        padded = plain.ljust(inner)
        return "│" + (style(padded) if style else padded) + "│"

    top = "┌" + "─" * inner + "┐"
    sep = "├" + "─" * inner + "┤"
    bottom = "└" + "─" * inner + "┘"
    clock = (now or datetime.now(timezone.utc)).astimezone().strftime("%H:%M:%S")
    header = "M8SHIFT · %s · %s · session %s · %s" % (
        _value(snapshot.get("project")), _value(snapshot.get("m8shift_version")),
        _value(snapshot.get("session")), clock)
    lines = [top, row(header)]

    holder = _value(snapshot.get("holder"))
    state = _value(snapshot.get("state"))
    pen = snapshot.get("pen") or {}
    pen_prefix = "PEN %s  " % holder
    pen_suffix = "  turn %s  claimed %s  heartbeat %s" % (
        _value(snapshot.get("turn")), _value(snapshot.get("since")),
        _value(pen.get("heartbeat") or "—"))
    # Compose styles after padding so ANSI bytes never affect border alignment.
    pen_plain = clean(pen_prefix + "[%s]" % state + pen_suffix, inner).ljust(inner)
    if colored and ("[%s]" % state) in pen_plain:
        left, right = pen_plain.split("[%s]" % state, 1)
        lines.append("│" + amber(left) + badge("[%s]" % state) + amber(right) + "│")
    else:
        lines.append("│" + pen_plain + "│")

    expires = _stamp(snapshot.get("expires"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    remaining = max(0, int((expires - current).total_seconds())) if expires else 0
    alive = bool(expires and remaining > 0)
    # The pen lease is 30 minutes; cap protects the gauge after clock skew.
    filled = min(10, max(0, round(10 * remaining / 1800)))
    gauge = "█" * filled + "░" * (10 - filled)
    ttl = "TTL <%s>  %02d:%02d left  expires %s (%s)" % (
        gauge, remaining // 60, remaining % 60, _value(snapshot.get("expires")),
        "alive" if alive else "stale")
    lines += [row(ttl, amber), sep, row("AGENTS", dim)]
    for agent in snapshot.get("agents") or []:
        name = clean(agent.get("id"), 18)
        state = clean(agent.get("role_state") or "unknown", 14)
        usage = agent.get("usage") or {}
        windows = usage.get("windows") or {}
        bits = []
        for label in ("session_5h", "weekly"):
            usage_row = windows.get(label) or {}
            ratio = usage_row.get("used_ratio")
            bits.append("%s %s" % (label, "unavailable" if ratio is None else "%d%%" % round(ratio * 100)))
        marker = "✦" if agent.get("id") == snapshot.get("holder") else " "
        lines.append(row("%s %-16s [%-10s]  %s" % (marker, name, state, "  ".join(bits))))
    ledger = snapshot.get("ledger") or {}
    listeners = snapshot.get("listeners")
    lines += [sep, row("LISTENERS  %s" % _value(listeners)),
              row("LEDGER  tasks_open=%s decisions_pending=%s doctor_findings=%s gate_armed=%s" %
                  tuple(_value(ledger.get(k)) for k in ("tasks_open", "decisions_pending", "doctor_findings", "gate_armed")))]
    last = snapshot.get("last_turn") or {}
    lines.append(row("LAST TURN  #%s %s → %s  %s" % (_value(last.get("n")), _value(last.get("agent")),
                                                       _value(last.get("to")), _value(last.get("ask_excerpt")))))
    lines += [sep, row("ACTIVITY", dim)]
    for event in snapshot.get("activity") or []:
        lines.append(row("  %s  %s" % (_value(event.get("agent")), _value(event.get("summary")))))
    lines += [sep, row("q quit  ? help  r refresh  ↑/↓ navigate", dim), bottom]
    return "\n".join(lines)


def load_snapshot(engine, root):
    env = dict(os.environ, M8SHIFT_ROOT=root)
    proc = subprocess.run([sys.executable, engine, "status", "--json"], env=env,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "status failed")
    payload = json.loads(proc.stdout)
    snap = payload.get("snapshot")
    if not isinstance(snap, dict):
        raise RuntimeError("status snapshot unavailable")
    schema = snap.get("schema", "")
    try:
        major = int(schema.rsplit("/", 1)[1])
    except (ValueError, IndexError):
        raise RuntimeError("unsupported status snapshot schema: %s" % clean(schema, 80))
    if major != SCHEMA_MAJOR:
        raise RuntimeError("unsupported status snapshot major: %s" % major)
    # Snapshot owns the structured sections; status owns relay-wide flat keys.
    merged = dict(payload)
    merged.pop("snapshot", None)
    merged.update(snap)
    return merged


def scroll_fallback(engine, root, extra):
    os.execve(sys.executable, [sys.executable, engine, "watch"] + extra,
              dict(os.environ, M8SHIFT_ROOT=root))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=2)
    p.add_argument("--plain", action="store_true")
    p.add_argument("--root", default=os.environ.get("M8SHIFT_ROOT", os.getcwd()))
    p.add_argument("--engine", default=os.environ.get("M8SHIFT_ENGINE"))
    args, extra = p.parse_known_args(argv)
    engine = args.engine or os.path.join(args.root, "m8shift.py")
    tty = sys.stdout.isatty()
    no_alt = args.plain or os.environ.get("TERM") == "dumb" or os.environ.get("M8SHIFT_NO_ALT_SCREEN")
    if not tty or no_alt or os.name == "nt":
        forwarded = (["--interval", str(args.interval)] if "--interval" not in extra else []) + extra
        return scroll_fallback(engine, args.root, forwarded)
    atexit.register(restore)
    old = {}
    def stop(signum, frame):
        restore()
        raise SystemExit(128 + signum)
    def suspend(signum, frame):
        restore()
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)
    def resume(signum, frame):
        signal.signal(signal.SIGTSTP, suspend)
        enter()
    for sig, handler in ((signal.SIGINT, stop), (signal.SIGTERM, stop),
                         (getattr(signal, "SIGTSTP", None), suspend),
                         (getattr(signal, "SIGCONT", None), resume)):
        if sig is not None:
            old[sig] = signal.signal(sig, handler)
    enter()
    previous = None
    try:
        while True:
            snap = load_snapshot(engine, args.root)
            frame = render(snap, shutil.get_terminal_size((80, 24)).columns)
            if frame != previous:
                sys.stdout.write(HOME + frame + "\x1b[J")
                sys.stdout.flush()
                previous = frame
            ready, _, _ = select.select([sys.stdin], [], [], max(.1, args.interval))
            if ready:
                key = sys.stdin.read(1)
                if key == "q":
                    break
                if key == "?":
                    previous = None
                # r and navigation intentionally trigger/no-op a read-only refresh.
                if key in ("r", "\x1b"):
                    previous = None
    finally:
        restore()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        restore()
        print("m8shift-top: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
