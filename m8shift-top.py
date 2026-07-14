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


def _paint_wordmark(plain, enabled):
    """Bold the header wordmark with the M8Shift brand colours."""
    if not enabled or "M8SHIFT" not in plain:
        return plain
    left, right = plain.split("M8SHIFT", 1)
    wordmark = (
        _color("1;38;2;255;122;24", "M", True)
        + _color("1;38;2;93;38;242", "8", True)
        + _color("1", "SHIFT", True)
    )
    return left + wordmark + right


def _usage_cell(windows, label, short, utc=False):
    """Render exhaustion or usage, plus the provider-supplied reset time."""
    row = windows.get(label) or {}
    ratio = row.get("used_ratio")
    model = row.get("model") if isinstance(row.get("model"), str) else ""
    model = clean(model, 18) if model else ""
    if ratio == 1 and model:
        value = "%s EXHAUSTED [%s]" % (short, model)
    else:
        missing = "n/a" if row.get("not_provided") is True else "unavailable"
        value = "%s %s" % (short, missing if ratio is None else "%d%%" % round(ratio * 100))
    reset = _stamp(row.get("resets_at"))
    if reset is not None:
        value += " reset " + _display_time(reset, utc, "%H:%M")
    return value, ratio


def _stamp(value):
    if not value or value == "-":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _display_time(value, utc=False, fmt="%Y-%m-%dT%H:%M:%S"):
    """Render one instant through the invocation's single display timezone."""
    stamp = value if isinstance(value, datetime) else _stamp(value)
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    shown = stamp.astimezone(timezone.utc) if utc else stamp.astimezone()
    return shown.strftime(fmt) + ("Z" if utc else "")


def _fmt_dur(seconds):
    # pen-hold duration for one turn; "—" when unknown (no timestamps yet).
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    return "%dh%02dm" % (m // 60, m % 60) if m >= 60 else "%02d:%02d" % (m, s)


def render(snapshot, width, now=None, interval=2, utc=False):
    # Operator policy: cap the frame near 120 columns, and tabulate into aligned
    # columns once there is room (>=100 cols); below that keep the stacked narrow
    # layout. Frame fidelity (every line == width) holds in both.
    width = min(max(24, width), 120)
    if width >= 100:
        return _render_wide(snapshot, width, now, interval, utc)
    return _render_stacked(snapshot, width, now, interval, utc)


def _render_stacked(snapshot, width, now=None, interval=2, utc=False):
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
    clock = _display_time(now or datetime.now(timezone.utc), utc, "%H:%M:%S")
    header = "M8SHIFT · %s · %s · session %s · %s" % (
        _value(snapshot.get("project")), _value(snapshot.get("m8shift_version")),
        _value(snapshot.get("session")), clock)
    lines = [top, _paint_wordmark(row(header), colored)]

    holder = _value(snapshot.get("holder"))
    state = _value(snapshot.get("state"))
    pen = snapshot.get("pen") or {}
    claimed = _display_time(snapshot.get("since"), utc, "%Y-%m-%d %H:%M") or "—"
    heartbeat = _display_time(pen.get("heartbeat"), utc, "%Y-%m-%d %H:%M") or "—"
    pen_prefix = "PEN %s  " % holder
    pen_suffix = "  turn %s  claimed %s  heartbeat %s" % (
        _value(snapshot.get("turn")), claimed, heartbeat)
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
        gauge, remaining // 60, remaining % 60,
        _display_time(expires, utc, "%Y-%m-%d %H:%M") or "—",
        "alive" if alive else "stale")
    lines += [row(ttl, amber), sep, row("AGENTS", dim)]
    for agent in snapshot.get("agents") or []:
        name = clean(agent.get("id"), 18)
        model = clean(agent.get("model") or "—", 24) + ("*" if agent.get("model") else "")
        state = clean(agent.get("role_state") or "unknown", 14)
        usage = agent.get("usage") or {}
        windows = usage.get("windows") or {}
        bits = []
        for label in ("session_5h", "weekly"):
            bit, _ = _usage_cell(windows, label, label, utc)
            bits.append(bit)
        marker = "✦" if agent.get("id") == snapshot.get("holder") else " "
        lines.append(row("%s %s | %s | %s | %s" %
                         (marker, name, model, state, "  ".join(bits))))
    lines.append(row("* model self-declared (unverified)", dim))
    ledger = snapshot.get("ledger") or {}
    listeners = snapshot.get("listeners")
    lines += [sep, row("LISTENERS  %s" % _value(listeners)),
              row("LEDGER  tasks_open=%s decisions_pending=%s doctor_findings=%s gate_armed=%s" %
                  tuple(_value(ledger.get(k)) for k in ("tasks_open", "decisions_pending", "doctor_findings", "gate_armed")))]
    last = snapshot.get("last_turn") or {}
    last_model = ((last.get("model") or "—") + ("*" if last.get("model") else ""))
    lines.append(row("LAST TURN  #%s %s/%s → %s  %s" %
                     (_value(last.get("n")), _value(last.get("agent")), last_model,
                      _value(last.get("to")), _value(last.get("ask_excerpt")))))
    lines += [sep, row("ACTIVITY", dim)]
    for event in snapshot.get("activity") or []:
        event_model = ((event.get("model") or "—") + ("*" if event.get("model") else ""))
        lines.append(row("  #%s  %s/%s  %s" % (_value(event.get("turn")),
                                             _value(event.get("agent")), event_model,
                                             _value(event.get("summary")))))
    lines += [sep, row("q quit  ? help  r refresh  ↑/↓ navigate  tick %ss" % interval, dim), bottom]
    return "\n".join(lines)


def _render_wide(snapshot, width, now=None, interval=2, utc=False):
    # Tabulated layout for wide terminals: sections lay out in aligned columns,
    # the dash-filled header/separators pin the right edge. Colour is composed
    # AFTER padding (paint replaces a plain segment with an equal-width coloured
    # one), so ANSI bytes never shift a border. Amber is reserved for the pen and
    # the TTL gauge; state carries an inverse badge, never colour alone.
    inner = width - 2
    colored = "NO_COLOR" not in os.environ
    amber = lambda text: _color("33", text, colored)
    green = lambda text: _color("32", text, colored)
    red = lambda text: _color("31", text, colored)
    cyan = lambda text: _color("36", text, colored)
    dim = lambda text: _color("2", text, colored)
    badge = lambda text: _color("7", text, colored)

    def usage_style(ratio):
        # green ok · amber elevated · red near-limit · dim when unknown.
        if ratio is None:
            return dim
        return red if ratio >= 0.85 else amber if ratio >= 0.60 else green

    def dot_style(role):
        return green if role == "idle" else amber if role == "working" else dim

    def paint(plain, seg, style):
        if not colored or not seg or seg not in plain:
            return plain
        left, rest = plain.split(seg, 1)
        return left + style(seg) + rest

    def cells(pairs):
        out = ""
        for index, (text, col) in enumerate(pairs):
            if col > len(out):
                out += " " * (col - len(out))
            # A cell may grow when a model name, reset time, or timestamp is
            # unusually long.  Reserve one column before the next fixed start
            # instead of letting this value collide with (or push) its peer.
            next_col = pairs[index + 1][1] if index + 1 < len(pairs) else inner
            available = max(0, next_col - max(col, len(out)) - 1)
            out += text[:available]
        return clean(out, inner).ljust(inner)

    def content(pairs):
        return "│" + cells(pairs) + "│"

    def framed(lc, rc, left, right=""):
        fill = inner - len(left) - len(right)
        if fill < 0:
            body = clean(left + right, inner).ljust(inner, "─")
        else:
            body = left + "─" * fill + right
        return lc + body + rc

    # A structural blank must stay blank; clean() turns "" into "unavailable".
    blank = "│" + " " * inner + "│"

    clock = _display_time(now or datetime.now(timezone.utc), utc, "%H:%M:%S")
    version = _value(snapshot.get("m8shift_version"))
    header = framed("┌", "┐", "─ M8SHIFT · %s · %s · session %s " % (
        _value(snapshot.get("project")), version,
        _value(snapshot.get("session"))), " %s ─" % clock)
    if version != "unavailable":
        header = paint(header, version, cyan)
    lines = [_paint_wordmark(header, colored), blank]

    holder = _value(snapshot.get("holder"))
    state = _value(snapshot.get("state"))
    pen = snapshot.get("pen") or {}
    turn_seg = "turn %s" % _value(snapshot.get("turn"))
    claimed = _display_time(snapshot.get("since"), utc, "%Y-%m-%d %H:%M") or "—"
    heartbeat = _display_time(pen.get("heartbeat"), utc, "%Y-%m-%d %H:%M") or "—"
    hb_seg = "heartbeat %s" % heartbeat
    pen_row = cells([
        ("  PEN", 0), (holder, 9), ("[%s]" % state, 17),
        (turn_seg, 34), ("claimed %s" % claimed, 44),
        (hb_seg, 70)])
    pen_row = paint(pen_row, holder, amber)
    pen_row = paint(pen_row, "[%s]" % state, badge)
    pen_row = paint(pen_row, turn_seg, cyan)
    pen_row = paint(pen_row, hb_seg, green)
    lines.append("│" + pen_row + "│")

    expires = _stamp(snapshot.get("expires"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    remaining = max(0, int((expires - current).total_seconds())) if expires else 0
    alive = bool(expires and remaining > 0)
    gw = max(12, min(28, inner - 70))
    filled = min(gw, max(0, round(gw * remaining / 1800)))
    gauge = "█" * filled + "░" * (gw - filled)
    left_seg = "%02d:%02d left" % (remaining // 60, remaining % 60)
    ttl_row = cells([
        ("  TTL", 0), (gauge, 10), (left_seg, 12 + gw),
        ("expires %s (%s)" % (_display_time(expires, utc, "%Y-%m-%d %H:%M") or "—",
                              "alive" if alive else "stale"), 24 + gw)])
    ttl_row = paint(paint(ttl_row, gauge, amber), left_seg, amber)
    lines += ["│" + ttl_row + "│", blank]

    for i, agent in enumerate(snapshot.get("agents") or []):
        name = clean(agent.get("id"), 16)
        model = clean(agent.get("model") or "—", 17) + ("*" if agent.get("model") else "")
        astate = clean(agent.get("role_state") or "unknown", 12)
        windows = (agent.get("usage") or {}).get("windows") or {}
        ratios, bits = [], []
        for short, label in (("5h", "session_5h"), ("weekly", "weekly")):
            bit, ratio = _usage_cell(windows, label, short, utc)
            ratios.append(ratio)
            bits.append(bit)
        marker = "✦" if agent.get("id") == snapshot.get("holder") else " "
        arow = cells([("  AGENTS" if i == 0 else "        ", 0),
                      ("%s %s" % (marker, name), 10), (model, 20),
                      ("● %s" % astate, 38), (bits[0], 52), (bits[1], 73)])
        arow = paint(arow, "●", dot_style(astate))
        arow = paint(arow, bits[0], usage_style(ratios[0]))
        arow = paint(arow, bits[1], usage_style(ratios[1]))
        lines.append("│" + arow + "│")
    lines.append(content([("        * model self-declared (unverified)", 0)]))

    ledger = snapshot.get("ledger") or {}
    last = snapshot.get("last_turn") or {}
    listen_val = _value(snapshot.get("listeners"))
    listen_line = content([("  LISTEN", 0), (listen_val, 10)])
    listen_line = paint(listen_line, "ALIVE", green)
    if listen_val == "unavailable":
        listen_line = paint(listen_line, listen_val, dim)
    lg = tuple(_value(ledger.get(k)) for k in
               ("tasks_open", "decisions_pending", "doctor_findings", "gate_armed"))
    ledger_line = content([("  LEDGER", 0),
                           ("tasks_open=%s  decisions_pending=%s  doctor_findings=%s  gate_armed=%s" % lg, 10)])
    ledger_line = paint(ledger_line, "tasks_open=%s" % lg[0], cyan)
    ledger_line = paint(ledger_line, "decisions_pending=%s" % lg[1], cyan)
    ledger_line = paint(ledger_line, "doctor_findings=%s" % lg[2],
                        green if lg[2] == "0" else dim if lg[2] == "unavailable" else red)
    ledger_line = paint(ledger_line, "gate_armed=%s" % lg[3],
                        dim if lg[3] in ("unavailable", "no", "false", "False") else green)
    last_model = ((last.get("model") or "—") + ("*" if last.get("model") else ""))
    turn_line = content([("  TURN", 0),
                         ("#%s %s/%s → %s  %s" %
                          (_value(last.get("n")), _value(last.get("agent")), last_model,
                           _value(last.get("to")), _value(last.get("ask_excerpt"))), 10)])
    lines += [blank, listen_line, ledger_line, turn_line, blank, framed("├", "┤", "─ activity ")]
    # ACTIVITY: recent -> oldest, tabulated (turn | ts-local | hold-dur | agent | action | note).
    stamped = [(_stamp(e.get("ts")), e) for e in (snapshot.get("activity") or [])]
    if any(t for t, _ in stamped):
        stamped.sort(key=lambda p: p[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    else:
        stamped.reverse()  # no ts yet: core is oldest-first, show newest on top
    for idx, (dt, e) in enumerate(stamped):
        ts_s = _display_time(dt, utc) if dt else "—"
        older = stamped[idx + 1][0] if idx + 1 < len(stamped) else None
        dur = _fmt_dur((dt - older).total_seconds()) if (dt and older) else "—"
        parts = (_value(e.get("summary")) or "").split(None, 1)
        action = (parts[0][:1].upper() + parts[0][1:])[:13] if parts and parts[0] != "unavailable" else "—"
        note = parts[1] if len(parts) > 1 else ""
        model = clean(e.get("model") or "—", 19) + ("*" if e.get("model") else "")
        lines.append("│" + cells([("  %s" % _value(e.get("turn")), 0), (ts_s, 8),
                                   (dur, 29), (clean(e.get("agent"), 8), 37),
                                   (model, 47), (action, 69), (note, 83)]) + "│")
    lines.append(framed("└", "┘", "─ q quit  ? help  r refresh  ↑/↓ navigate  tick %ss " % interval))
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
    p.add_argument("--interval", type=int, default=2,
                   help="refresh interval in seconds (default: 2)")
    p.add_argument("--plain", action="store_true")
    p.add_argument("--utc", action="store_true",
                   help="render every dashboard time in UTC with a Z suffix")
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
            frame = render(snap, shutil.get_terminal_size((80, 24)).columns,
                           interval=args.interval, utc=args.utc)
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
