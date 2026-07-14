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
import textwrap
import time
from datetime import datetime, timezone

try:
    import termios
    import tty as tty_module
except ImportError:  # pragma: no cover - unavailable on Windows
    termios = None
    tty_module = None

VERSION = "3.60.0"  # lockstep with m8shift.py; required for companion install/update

ALT_ON = "\x1b[?1049h\x1b[?25l"
ALT_OFF = "\x1b[?25h\x1b[?1049l"
HOME = "\x1b[H"
SCHEMA_MAJOR = 1
ACTIVITY_VIEWPORT_MAX = 20
ACTIVITY_SCROLL_HEADROOM = 180
ACTIVITY_PROVISION_MAX = 200
ACTIVITY_BUFFER_EDGE = "<older turns on disk — peek/journal>"
TURN_SCHEMA = "m8shift.turn/1"
_active = False
_keyboard_fd = None
_keyboard_attrs = None


def _enable_keyboard(stream=None):
    """Put an interactive stdin in cbreak mode, retaining its original state."""
    global _keyboard_fd, _keyboard_attrs
    stream = stream or sys.stdin
    if _keyboard_fd is not None or termios is None or tty_module is None:
        return
    try:
        if not stream.isatty():
            return
        fd = stream.fileno()
        attrs = termios.tcgetattr(fd)
        tty_module.setcbreak(fd, termios.TCSANOW)
    except (AttributeError, OSError, termios.error):
        return
    _keyboard_fd, _keyboard_attrs = fd, attrs


def _restore_keyboard():
    """Restore stdin exactly once after quit, failure, or job-control suspend."""
    global _keyboard_fd, _keyboard_attrs
    fd, attrs = _keyboard_fd, _keyboard_attrs
    _keyboard_fd = _keyboard_attrs = None
    if fd is None or attrs is None or termios is None:
        return
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except (OSError, termios.error):
        pass


def _open_self_pipe():
    """Return a nonblocking pipe suitable for signal wakeups."""
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    os.set_blocking(write_fd, False)
    return read_fd, write_fd


def _drain_self_pipe(read_fd):
    """Coalesce all queued wakeup bytes without blocking."""
    drained = 0
    while True:
        try:
            chunk = os.read(read_fd, 4096)
        except BlockingIOError:
            break
        if not chunk:
            break
        drained += len(chunk)
    return drained


def restore(stream=None):
    global _active
    _restore_keyboard()
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
    _enable_keyboard()


def clean(value, width):
    text = value if isinstance(value, str) and value else "unavailable"
    text = "".join(c for c in text if ord(c) >= 32 and not 127 <= ord(c) <= 159)
    return text[:max(0, width)]


def _value(value):
    return "unavailable" if value is None else str(value)


def _pen_turn_label(snapshot):
    """Describe the holder's live/next turn without misattributing the last one."""
    try:
        next_turn = "turn %s" % (int(snapshot.get("turn")) + 1)
    except (TypeError, ValueError):
        next_turn = "next turn"
    state = str(snapshot.get("state") or "")
    if state.startswith(("WORKING_", "AWAITING_")):
        # Holder + state are already adjacent: "codex [WORKING_CODEX] → turn 8".
        return "→ %s" % next_turn
    return "last #%s" % _value(snapshot.get("turn"))


def _color(code, text, enabled):
    return "\x1b[%sm%s\x1b[0m" % (code, text) if enabled else text


_SEMANTIC_COLOURS = {
    # GitHub Dark Dimmed terminal palette. ANSI-16 fallbacks are semantic slots,
    # deliberately not RGB-nearest approximations: safety meaning must survive.
    "green": ((87, 171, 90), "32"),
    "red": ((244, 112, 103), "31"),
    "yellow": ((198, 144, 38), "33"),
    "cyan": ((57, 197, 207), "36"),
    "magenta": ((176, 131, 240), "35"),
    "dim": ((99, 110, 123), "90"),
    "badge": ((205, 217, 229), "97"),
}


def _colour_tier(enabled=True):
    """Return plain, ansi16, 256, or truecolor for the current terminal."""
    if not enabled or "NO_COLOR" in os.environ:
        return "plain"
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return "plain"
    capability = os.environ.get("COLORTERM", "").strip().lower()
    if capability in ("truecolor", "24bit"):
        return "truecolor"
    if "256color" in os.environ.get("TERM", "").strip().lower():
        return "256"
    return "ansi16"


def _xterm_256(rgb):
    """Return the deterministic nearest xterm-256 cube/grayscale index."""
    levels = (0, 95, 135, 175, 215, 255)
    palette = [
        (16 + 36 * r + 6 * g + b, (levels[r], levels[g], levels[b]))
        for r in range(6) for g in range(6) for b in range(6)
    ]
    palette += [(232 + i, (8 + 10 * i,) * 3) for i in range(24)]
    return min(
        palette,
        key=lambda item: (sum((left - right) ** 2
                              for left, right in zip(rgb, item[1])), item[0]),
    )[0]


def _brand(rgb, text, enabled, ansi16, bold=False, inverse=False,
           fallback_256=None):
    """Paint one role through truecolor, xterm-256, or semantic ANSI-16."""
    tier = _colour_tier(enabled)
    if tier == "plain":
        return text
    if tier == "truecolor":
        colour = "38;2;%d;%d;%d" % rgb
    elif tier == "256":
        colour = "38;5;%d" % (fallback_256 if fallback_256 is not None
                               else _xterm_256(rgb))
    else:
        colour = ansi16
    attributes = (["1"] if bold else []) + (["7"] if inverse else []) + [colour]
    return _color(";".join(attributes), text, True)


def _semantic(role, text, enabled=True):
    rgb, ansi16 = _SEMANTIC_COLOURS[role]
    return _brand(rgb, text, enabled, ansi16, inverse=(role == "badge"))


def _paint_wordmark(plain, enabled):
    """Bold the header wordmark with the M8Shift brand colours."""
    if not enabled or "M8SHIFT" not in plain:
        return plain
    left, right = plain.split("M8SHIFT", 1)
    wordmark = (
        _brand((255, 122, 24), "M", True, "33", bold=True,
               fallback_256=208)
        + _brand((93, 38, 242), "8", True, "35", bold=True,
                 fallback_256=99)
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
        value += " reset " + _display_time(reset, utc, "%a %m-%d %H:%M")
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


def _heartbeat_display(snapshot, current, slim=False):
    """Return relative heartbeat text and its RFC 049 semantic colour role."""
    stamp = _stamp((snapshot.get("pen") or {}).get("heartbeat"))
    if stamp is None:
        return ("hb —" if slim else "heartbeat —"), "dim"
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = max(0, int((current - stamp).total_seconds()))
    if age < 60:
        amount, unit = age, "s"
    elif age < 3600:
        amount, unit = age // 60, "m"
    else:
        amount, unit = age // 3600, "h"
    text = ("hb %d %s" if slim else "heartbeat %d %s ago") % (amount, unit)

    # The words/age carry meaning without colour.  Colour mirrors the existing
    # RFC 049 states instead of inventing a second liveness threshold model.
    liveness = snapshot.get("liveness")
    if liveness == "ordinary-stale":
        role = "red"
    elif liveness == "alive-expired":
        role = "yellow"
    elif liveness == "fresh":
        role = "green"
    else:
        expires = _stamp(snapshot.get("expires"))
        role = "red" if expires is not None and current > expires else "green"
    return text, role


def _ledger_display(ledger, slim=False):
    """Return readable ledger text plus uniquely addressable styled segments."""
    values = tuple(_value(ledger.get(key)) for key in
                   ("tasks_open", "decisions_pending", "doctor_findings"))
    raw_gate = ledger.get("gate_armed")
    if raw_gate is True or str(raw_gate).lower() in ("true", "yes", "armed"):
        gate = "armed"
    elif raw_gate is False or str(raw_gate).lower() in ("false", "no", "disarmed"):
        gate = "disarmed"
    else:
        gate = "unavailable"
    if slim:
        segments = ("tasks %s" % values[0], "decisions %s" % values[1],
                    "doctor %s" % values[2], "gate %s" % gate)
        payload = " . ".join(segments)
    else:
        segments = ("tasks %s open" % values[0],
                    "decisions %s pending" % values[1],
                    "doctor %s findings" % values[2], "gate %s" % gate)
        payload = "   ".join(segments)
    return payload, segments, values + (gate,)


def _paint_segment_value(plain, segment, value, style, enabled=True):
    """Paint only a value inside one labelled segment, preserving geometry."""
    if not enabled or not segment or segment not in plain or value not in segment:
        return plain
    left, rest = plain.split(segment, 1)
    before, after = segment.split(value, 1)
    return left + before + style(value) + after + rest


def _fmt_dur(seconds):
    # pen-hold duration for one turn; "—" when unknown (no timestamps yet).
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    return "%dh%02dm" % (m // 60, m % 60) if m >= 60 else "%02d:%02d" % (m, s)


def _activity_capacity(snapshot, width, height):
    """Physical activity-zone rows available inside the terminal frame."""
    if height is None:
        return None
    agent_rows = len(snapshot.get("agents") or [])
    fixed_rows = (13 if max(24, width) >= 100 else 16) + agent_rows
    return max(0, height - fixed_rows)


def _activity_limit(snapshot, width, height):
    """Readable event viewport; taller frames retain structural blank fill."""
    capacity = _activity_capacity(snapshot, width, height)
    return None if capacity is None else min(capacity, ACTIVITY_VIEWPORT_MAX)


def _activity_request_limit(width, height, agent_count=2):
    """Ask core for the viewport plus bounded scroll headroom."""
    surrogate = {"agents": [None] * max(0, agent_count)}
    viewport = _activity_limit(surrogate, width, height)
    viewport = ACTIVITY_VIEWPORT_MAX if viewport is None else viewport
    return min(ACTIVITY_PROVISION_MAX, viewport + ACTIVITY_SCROLL_HEADROOM)


def _activity_window(events, offset, limit):
    if limit is None:
        return events, 0
    maximum = max(0, len(events) - limit)
    offset = min(max(0, offset), maximum)
    return events[offset:offset + limit], offset


def _activity_label(events, visible, upper=False, buffer_edge=False):
    name = "ACTIVITY" if upper else "activity"
    numbers = [event.get("turn") for event in events
               if isinstance(event, dict)
               and isinstance(event.get("turn"), int)
               and not isinstance(event.get("turn"), bool)]
    shown_numbers = [event.get("turn") for event in visible
                     if isinstance(event, dict)
                     and isinstance(event.get("turn"), int)
                     and not isinstance(event.get("turn"), bool)]
    total = max(numbers) if numbers else 0
    if shown_numbers:
        label = "%s turns %d-%d / %d" % (
            name, min(shown_numbers), max(shown_numbers), total)
    else:
        label = "%s turns 0 / %d" % (name, total)
    if buffer_edge:
        label += "  " + ACTIVITY_BUFFER_EDGE
    return label


def _activity_buffer_edge(snapshot, events, offset, shown):
    """True only when the visible window reaches a truncated buffer's floor."""
    return bool(snapshot.get("activity_truncated") and events and shown
                and offset >= max(0, len(events) - shown))


def activity_max_scroll(snapshot, width, height):
    limit = _activity_limit(snapshot, width, height)
    if limit is None:
        return 0
    return max(0, len(snapshot.get("activity") or []) - limit)


def _activity_navigation(snapshot):
    """Return snapshot events newest-first; immutable turn numbers are cursors."""
    return list(reversed(snapshot.get("activity") or []))


def _display_text(value):
    """Sanitize terminal controls without imposing the snapshot's text bound."""
    if not isinstance(value, str) or not value:
        return "—"
    return "".join(c if ord(c) >= 32 and not 127 <= ord(c) <= 159 else " "
                   for c in value)


def _activity_reader_lines(record, width):
    """Word-wrap the complete on-demand done text; never truncate it."""
    available = max(1, max(24, width) - 6)
    return textwrap.wrap(
        _display_text((record or {}).get("done")), width=available,
        replace_whitespace=True, drop_whitespace=True,
        break_long_words=True, break_on_hyphens=False,
    ) or ["—"]


def _activity_reader_window(snapshot, record, width, height, text_offset=0):
    lines = _activity_reader_lines(record, width)
    capacity = _activity_capacity(snapshot, max(24, width), height)
    if capacity is None:
        return lines, 0, len(lines)
    maximum = ((len(lines) - 1) // max(1, capacity)) * max(1, capacity)
    offset = min(max(0, text_offset), maximum)
    return lines[offset:offset + capacity], offset, len(lines)


def activity_text_page(snapshot, record, width, height, text_offset, direction):
    """Move one physical page while retaining access to every wrapped line."""
    lines = _activity_reader_lines(record, width)
    capacity = _activity_capacity(snapshot, max(24, width), height) or 1
    maximum = ((len(lines) - 1) // capacity) * capacity
    return min(maximum, max(0, text_offset + direction * capacity))


def activity_adjacent_turn(snapshot, selected_turn, direction):
    """Navigate one activity block (direction -1 newer, +1 older)."""
    numbers = [event.get("turn") for event in _activity_navigation(snapshot)
               if isinstance(event, dict)
               and isinstance(event.get("turn"), int)
               and not isinstance(event.get("turn"), bool)]
    if not numbers:
        return None
    try:
        index = numbers.index(selected_turn)
    except ValueError:
        index = 0
    return numbers[min(len(numbers) - 1, max(0, index + direction))]


def _expanded_activity_label(record, offset, visible_count, total):
    start = offset + 1 if total else 0
    end = offset + visible_count
    return "ACTIVITY · EXPANDED #%s  %s → %s  text %d-%d / %d" % (
        _value((record or {}).get("turn")),
        _value((record or {}).get("agent")),
        _value((record or {}).get("to")), start, end, total)


def _flex_track_widths(width, baseline, weights):
    """Grow a 120-column track plan by weighted largest remainder."""
    if width < 120 or len(baseline) != len(weights):
        raise ValueError("flex tracks require width >= 120 and paired declarations")
    if sum(baseline) != 118 or any(value <= 0 for value in baseline):
        raise ValueError("flex track baseline must be positive and sum to 118")
    if any(weight < 0 for weight in weights) or not any(weights):
        raise ValueError("flex track weights must include a positive value")
    extra = width - 120
    total_weight = sum(weights)
    additions = [extra * weight // total_weight for weight in weights]
    residual = extra - sum(additions)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(extra * weights[index] % total_weight), index),
    )
    for index in order[:residual]:
        additions[index] += 1
    result = [base + addition for base, addition in zip(baseline, additions)]
    if sum(result) != width - 2:
        raise AssertionError("flex tracks do not fill the inner frame")
    return result


def _track_cells(values, widths):
    """Render values into exact tracks, reserving one separator column each."""
    if len(values) != len(widths):
        raise ValueError("track values and widths must have equal length")
    return "".join(
        ("" if value == "" else clean(value, track - 1)).ljust(track)
        for value, track in zip(values, widths)
    )


def render(snapshot, width, now=None, interval=2, utc=False, height=None,
           activity_offset=0, expanded_activity=None, text_offset=0):
    # Use the real terminal width. The 100-column breakpoint is stable; the wide
    # layout grows deterministically above its byte-stable 120-column baseline.
    width = max(24, width)
    if width >= 100:
        return _render_wide(snapshot, width, now, interval, utc, height,
                            activity_offset, expanded_activity, text_offset)
    return _render_stacked(snapshot, width, now, interval, utc, height,
                           activity_offset, expanded_activity, text_offset)


def _render_stacked(snapshot, width, now=None, interval=2, utc=False,
                    height=None, activity_offset=0, expanded_activity=None,
                    text_offset=0):
    width = max(24, width)
    inner = width - 2
    colored = _colour_tier() != "plain"
    amber = lambda text: _semantic("yellow", text, colored)
    green = lambda text: _semantic("green", text, colored)
    red = lambda text: _semantic("red", text, colored)
    cyan = lambda text: _semantic("cyan", text, colored)
    magenta = lambda text: _semantic("magenta", text, colored)
    dim = lambda text: _semantic("dim", text, colored)
    badge = lambda text: _semantic("badge", text, colored)

    def usage_style(ratio):
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

    def row(text="", style=None):
        plain = "" if text == "" else clean(str(text), inner)
        padded = plain.ljust(inner)
        return "│" + (style(padded) if style else padded) + "│"

    top = "┌" + "─" * inner + "┐"
    sep = "├" + "─" * inner + "┤"
    bottom = "└" + "─" * inner + "┘"
    clock = _display_time(now or datetime.now(timezone.utc), utc, "%H:%M:%S")
    version = _value(snapshot.get("m8shift_version"))
    header = "M8SHIFT · %s · %s · session %s · %s" % (
        _value(snapshot.get("project")), version,
        _value(snapshot.get("session")), clock)
    header_row = paint(row(header), version, cyan)
    lines = [top, _paint_wordmark(header_row, colored)]

    holder = _value(snapshot.get("holder"))
    state = _value(snapshot.get("state"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    claimed = _display_time(snapshot.get("since"), utc, "%Y-%m-%d %H:%M") or "—"
    heartbeat, heartbeat_role = _heartbeat_display(snapshot, current, slim=True)
    heartbeat_style = {"green": green, "yellow": amber, "red": red}.get(
        heartbeat_role, dim)
    pen_prefix = "PEN %s  " % holder
    pen_suffix = "  %s  claimed %s  %s" % (
        _pen_turn_label(snapshot), claimed, heartbeat)
    # Compose styles after padding so ANSI bytes never affect border alignment.
    pen_plain = clean(pen_prefix + "[%s]" % state + pen_suffix, inner).ljust(inner)
    pen_plain = paint(pen_plain, holder, amber)
    pen_plain = paint(pen_plain, "[%s]" % state, badge)
    pen_plain = paint(pen_plain, _pen_turn_label(snapshot), magenta)
    pen_plain = paint(pen_plain, heartbeat, heartbeat_style)
    lines.append("│" + pen_plain + "│")

    expires = _stamp(snapshot.get("expires"))
    remaining = max(0, int((expires - current).total_seconds())) if expires else 0
    alive = bool(expires and remaining > 0)
    # The pen lease is 30 minutes; cap protects the gauge after clock skew.
    filled = min(10, max(0, round(10 * remaining / 1800)))
    gauge = "█" * filled + "░" * (10 - filled)
    left_seg = "%02d:%02d left" % (remaining // 60, remaining % 60)
    status_seg = "alive" if alive else "stale"
    ttl = "TTL <%s>  %s  expires %s (%s)" % (
        gauge, left_seg,
        _display_time(expires, utc, "%Y-%m-%d %H:%M") or "—",
        status_seg)
    ttl_row = clean(ttl, inner).ljust(inner)
    ttl_row = paint(paint(ttl_row, gauge, amber), left_seg, amber)
    ttl_row = paint(ttl_row, status_seg, green if alive else red)
    lines += ["│" + ttl_row + "│", sep, row("AGENTS", dim)]
    for agent in snapshot.get("agents") or []:
        name = clean(agent.get("id"), 18)
        model = clean(agent.get("model") or "—", 24) + ("*" if agent.get("model") else "")
        state = clean(agent.get("role_state") or "unknown", 14)
        usage = agent.get("usage") or {}
        windows = usage.get("windows") or {}
        bits, ratios = [], []
        for label in ("session_5h", "weekly"):
            bit, ratio = _usage_cell(windows, label, label, utc)
            bits.append(bit)
            ratios.append(ratio)
        marker = "✦" if agent.get("id") == snapshot.get("holder") else " "
        agent_plain = clean("%s %s | %s | ● %s | %s" %
                            (marker, name, model, state, "  ".join(bits)),
                            inner).ljust(inner)
        agent_plain = paint(agent_plain, marker.strip(), amber)
        agent_plain = paint(agent_plain, "●", dot_style(state))
        for bit, ratio in zip(bits, ratios):
            agent_plain = paint(agent_plain, bit, usage_style(ratio))
        lines.append("│" + agent_plain + "│")
    lines.append(row("* model self-declared (unverified)", dim))
    ledger = snapshot.get("ledger") or {}
    listeners = snapshot.get("listeners")
    listen_row = row("LISTENERS  %s" % _value(listeners))
    listen_row = paint(listen_row, "ALIVE", green)
    ledger_payload, ledger_segments, lg = _ledger_display(ledger, slim=True)
    ledger_row = row("LEDGER  " + ledger_payload)
    ledger_row = _paint_segment_value(
        ledger_row, ledger_segments[0], lg[0], cyan, colored)
    ledger_row = _paint_segment_value(
        ledger_row, ledger_segments[1], lg[1], cyan, colored)
    ledger_row = _paint_segment_value(
        ledger_row, ledger_segments[2], lg[2],
        green if lg[2] == "0" else dim if lg[2] == "unavailable" else red,
        colored)
    ledger_row = _paint_segment_value(
        ledger_row, ledger_segments[3], lg[3],
        green if lg[3] == "armed" else amber if lg[3] == "disarmed" else dim,
        colored)
    lines += [sep, listen_row, ledger_row]
    last = snapshot.get("last_turn") or {}
    last_model = ((last.get("model") or "—") + ("*" if last.get("model") else ""))
    lines.append(row("LAST TURN  #%s %s/%s → %s  %s" %
                     (_value(last.get("n")), _value(last.get("agent")), last_model,
                      _value(last.get("to")), _value(last.get("ask_excerpt")))))
    events = _activity_navigation(snapshot)
    if expanded_activity is not None:
        visible, text_offset, text_total = _activity_reader_window(
            snapshot, expanded_activity, width, height, text_offset)
        lines += [sep, row(_expanded_activity_label(
            expanded_activity, text_offset, len(visible), text_total), dim)]
        lines.extend(row("  " + text) for text in visible)
    else:
        visible, activity_offset = _activity_window(
            events, activity_offset, _activity_limit(snapshot, width, height))
        at_buffer_edge = _activity_buffer_edge(
            snapshot, events, activity_offset, len(visible))
        lines += [sep, row(_activity_label(
            events, visible, upper=True, buffer_edge=at_buffer_edge), dim)]
        for event in visible:
            event_model = ((event.get("model") or "—") + ("*" if event.get("model") else ""))
            lines.append(row("  #%s  %s/%s  %s" % (_value(event.get("turn")),
                                                 _value(event.get("agent")), event_model,
                                                 _value(event.get("summary")))))
    capacity = _activity_capacity(snapshot, width, height)
    if capacity is not None:
        lines.extend(row("") for _ in range(capacity - len(visible)))
    footer = ("q quit  ? help  e compact  ↑/↓ block  ←/→ text  auto-refresh %ss" % interval
              if expanded_activity is not None else
              "q quit  ? help  e expand  r/Esc refresh  ↑/↓ navigate  auto-refresh %ss" % interval)
    lines += [sep, row(footer, dim), bottom]
    return "\n".join(lines)


def _render_wide(snapshot, width, now=None, interval=2, utc=False,
                 height=None, activity_offset=0, expanded_activity=None,
                 text_offset=0):
    # Tabulated layout for wide terminals: sections lay out in aligned columns,
    # the dash-filled header/separators pin the right edge. Colour is composed
    # AFTER padding (paint replaces a plain segment with an equal-width coloured
    # one), so ANSI bytes never shift a border. Amber is reserved for the pen and
    # the TTL gauge; state carries an inverse badge, never colour alone.
    inner = width - 2
    colored = _colour_tier() != "plain"
    amber = lambda text: _semantic("yellow", text, colored)
    green = lambda text: _semantic("green", text, colored)
    red = lambda text: _semantic("red", text, colored)
    cyan = lambda text: _semantic("cyan", text, colored)
    magenta = lambda text: _semantic("magenta", text, colored)
    dim = lambda text: _semantic("dim", text, colored)
    badge = lambda text: _semantic("badge", text, colored)

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

    def adaptive_cells(values, starts, baseline, weights):
        if width < 120:
            return cells(list(zip(values, starts)))
        widths = _flex_track_widths(width, baseline, weights)
        return _track_cells(values, widths)

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
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    turn_seg = _pen_turn_label(snapshot)
    claimed = _display_time(snapshot.get("since"), utc, "%Y-%m-%d %H:%M") or "—"
    hb_seg, heartbeat_role = _heartbeat_display(snapshot, current)
    heartbeat_style = {"green": green, "yellow": amber, "red": red}.get(
        heartbeat_role, dim)
    pen_row = adaptive_cells(
        ("  PEN", holder, "[%s]" % state, turn_seg,
         "claimed %s" % claimed, hb_seg),
        (0, 7, 14, 31, 44, 70),
        # The live-turn track stays fixed as the frame grows.  Reserve room for
        # five-digit turns plus two spare characters; claimed/heartbeat absorb
        # all flex so wider terminals cannot distort the turn label.
        (9, 8, 17, 15, 26, 43),
        (0, 0, 0, 0, 1, 1),
    )
    pen_row = paint(pen_row, holder, amber)
    pen_row = paint(pen_row, "[%s]" % state, badge)
    pen_row = paint(pen_row, turn_seg, magenta)
    pen_row = paint(pen_row, hb_seg, heartbeat_style)
    lines.append("│" + pen_row + "│")

    expires = _stamp(snapshot.get("expires"))
    remaining = max(0, int((expires - current).total_seconds())) if expires else 0
    alive = bool(expires and remaining > 0)
    gw = max(12, min(28, inner - 70)) if width < 120 else 28
    filled = min(gw, max(0, round(gw * remaining / 1800)))
    gauge = "█" * filled + "░" * (gw - filled)
    left_seg = "%02d:%02d left" % (remaining // 60, remaining % 60)
    status_seg = "alive" if alive else "stale"
    ttl_expiry = "expires %s (%s)" % (
        _display_time(expires, utc, "%Y-%m-%d %H:%M") or "—", status_seg)
    ttl_row = adaptive_cells(
        ("  TTL", gauge, left_seg, ttl_expiry),
        (0, 10, 12 + gw, 24 + gw),
        (10, 30, 12, 66),
        (0, 0, 0, 1),
    )
    ttl_row = paint(paint(ttl_row, gauge, amber), left_seg, amber)
    ttl_row = paint(ttl_row, status_seg, green if alive else red)
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
        arow = adaptive_cells(
            ("  AGENTS" if i == 0 else "        ",
             "%s %s" % (marker, name), model, "● %s" % astate,
             bits[0], bits[1]),
            (0, 10, 20, 38, 52, 73),
            (10, 10, 20, 14, 30, 34),
            (0, 1, 1, 0, 2, 2),
        )
        arow = paint(arow, "●", dot_style(astate))
        arow = paint(arow, bits[0], usage_style(ratios[0]))
        arow = paint(arow, bits[1], usage_style(ratios[1]))
        lines.append("│" + arow + "│")
    lines.append(content([("        * model self-declared (unverified)", 0)]))

    ledger = snapshot.get("ledger") or {}
    last = snapshot.get("last_turn") or {}
    listen_val = _value(snapshot.get("listeners"))
    listen_line = "│" + adaptive_cells(
        ("  LISTEN", listen_val), (0, 10), (10, 108), (0, 1)) + "│"
    listen_line = paint(listen_line, "ALIVE", green)
    if listen_val == "unavailable":
        listen_line = paint(listen_line, listen_val, dim)
    ledger_payload, ledger_segments, lg = _ledger_display(ledger)
    ledger_line = "│" + adaptive_cells(
        ("  LEDGER", ledger_payload), (0, 10), (10, 108), (0, 1)) + "│"
    ledger_line = _paint_segment_value(
        ledger_line, ledger_segments[0], lg[0], cyan, colored)
    ledger_line = _paint_segment_value(
        ledger_line, ledger_segments[1], lg[1], cyan, colored)
    ledger_line = _paint_segment_value(
        ledger_line, ledger_segments[2], lg[2],
        green if lg[2] == "0" else dim if lg[2] == "unavailable" else red,
        colored)
    ledger_line = _paint_segment_value(
        ledger_line, ledger_segments[3], lg[3],
        green if lg[3] == "armed" else amber if lg[3] == "disarmed" else dim,
        colored)
    last_model = ((last.get("model") or "—") + ("*" if last.get("model") else ""))
    turn_payload = "#%s %s/%s → %s  %s" % (
        _value(last.get("n")), _value(last.get("agent")), last_model,
        _value(last.get("to")), _value(last.get("ask_excerpt")))
    turn_line = "│" + adaptive_cells(
        ("  TURN", turn_payload), (0, 10), (10, 108), (0, 1)) + "│"
    lines += [blank, listen_line, ledger_line, turn_line, blank]
    # ACTIVITY: recent -> oldest, tabulated (turn | ts-local | hold-dur | agent | action | note).
    stamped = [(_stamp(e.get("ts")), e) for e in (snapshot.get("activity") or [])]
    if any(t for t, _ in stamped):
        stamped.sort(key=lambda p: p[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    else:
        stamped.reverse()  # no ts yet: core is oldest-first, show newest on top
    if expanded_activity is not None:
        expanded_lines, text_offset, text_total = _activity_reader_window(
            snapshot, expanded_activity, width, height, text_offset)
        lines.append(framed("├", "┤", "─ %s " % _expanded_activity_label(
            expanded_activity, text_offset, len(expanded_lines), text_total)))
        for expanded_line in expanded_lines:
            lines.append(content([("  " + expanded_line, 0)]))
        visible = expanded_lines
    else:
        visible, activity_offset = _activity_window(
            stamped, activity_offset, _activity_limit(snapshot, width, height))
        visible_events = [event for _, event in visible]
        at_buffer_edge = _activity_buffer_edge(
            snapshot, stamped, activity_offset, len(visible))
        lines.append(framed("├", "┤", "─ %s " % _activity_label(
            [event for _, event in stamped], visible_events,
            buffer_edge=at_buffer_edge)))
        for idx, (dt, e) in enumerate(visible):
            ts_s = _display_time(dt, utc) if dt else "—"
            absolute_index = activity_offset + idx
            older = stamped[absolute_index + 1][0] if absolute_index + 1 < len(stamped) else None
            dur = _fmt_dur((dt - older).total_seconds()) if (dt and older) else "—"
            parts = (_value(e.get("summary")) or "").split(None, 1)
            action = (parts[0][:1].upper() + parts[0][1:])[:13] if parts and parts[0] != "unavailable" else "—"
            note = parts[1] if len(parts) > 1 else ""
            model = clean(e.get("model") or "—", 19) + ("*" if e.get("model") else "")
            activity_row = adaptive_cells(
                ("  %s" % _value(e.get("turn")), ts_s, dur,
                 clean(e.get("agent"), 8), model, action, note),
                (0, 8, 29, 37, 47, 69, 83),
                (8, 21, 8, 10, 22, 14, 35),
                (0, 0, 0, 0, 1, 1, 2),
            )
            lines.append("│" + activity_row + "│")
    capacity = _activity_capacity(snapshot, width, height)
    if capacity is not None:
        lines.extend(blank for _ in range(capacity - len(visible)))
    footer = ("─ q quit  ? help  e compact  ↑/↓ block  ←/→ text  auto-refresh %ss " % interval
              if expanded_activity is not None else
              "─ q quit  ? help  e expand  r/Esc refresh  ↑/↓ navigate  auto-refresh %ss " % interval)
    lines.append(framed("└", "┘", footer))
    return "\n".join(lines)


def load_snapshot(engine, root, activity_limit=8):
    env = dict(os.environ, M8SHIFT_ROOT=root)
    proc = subprocess.run([sys.executable, engine, "status", "--json",
                           "--activity-limit", str(activity_limit)], env=env,
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


def load_activity_turn(engine, root, turn):
    """Fetch exactly one full done-text record by immutable turn number."""
    env = dict(os.environ, M8SHIFT_ROOT=root)
    proc = subprocess.run([sys.executable, engine, "turn", str(turn), "--json"],
                          env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "turn fetch failed")
    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict) or payload.get("schema") != TURN_SCHEMA \
            or payload.get("turn") != turn or not isinstance(payload.get("done"), str):
        raise RuntimeError("invalid turn payload for #%s" % turn)
    return payload


def scroll_fallback(engine, root, extra):
    os.execve(sys.executable, [sys.executable, engine, "watch"] + extra,
              dict(os.environ, M8SHIFT_ROOT=root))


def read_key(stream=None, timeout=.03, selector=select.select):
    """Read one cbreak key, folding ANSI up/down sequences into one event."""
    stream = stream or sys.stdin
    first = stream.read(1)
    if not first:
        return None
    if first != "\x1b":
        return first
    ready, _, _ = selector([stream], [], [], timeout)
    if not ready:
        return "escape"
    second = stream.read(1)
    if second != "[":
        return "escape"
    ready, _, _ = selector([stream], [], [], timeout)
    if not ready:
        return "escape"
    return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(
        stream.read(1), "escape")


def key_effect(key, scroll_offset, max_scroll, help_visible):
    """Return (quit, refresh, offset, help) for one decoded key event."""
    if key == "q":
        return True, False, scroll_offset, help_visible
    if key == "?":
        return False, True, scroll_offset, not help_visible
    if key in ("r", "escape"):
        return False, True, scroll_offset, False
    if not help_visible and key == "up":
        return False, True, max(0, scroll_offset - 1), help_visible
    if not help_visible and key == "down":
        return False, True, min(max_scroll, scroll_offset + 1), help_visible
    return False, False, scroll_offset, help_visible


def render_help(width, interval=2, height=None):
    """Render the interactive key reference as a frame-fidelity overlay."""
    width = max(24, width)
    inner = width - 2

    def row(text=""):
        plain = "" if text == "" else clean(text, inner)
        return "│" + plain.ljust(inner) + "│"

    top = "┌" + "─" * inner + "┐"
    sep = "├" + "─" * inner + "┤"
    bottom = "└" + "─" * inner + "┘"
    padding = max(0, height - 15) if height is not None else 0
    lines = [
        top,
        row("M8SHIFT TOP · HELP"),
        sep,
        row("q       quit and restore the terminal"),
        row("r       reload the relay snapshot now"),
        row("Esc     close help and reload the snapshot"),
        row("?       open or close this help"),
        row("e       toggle compact / expanded activity"),
        row("↑ / ↓   scroll the activity window"),
        row("← / →   page complete text in expanded mode"),
        row(""),
        row("Automatic refresh: every %ss" % interval),
    ]
    lines.extend(row("") for _ in range(padding))
    lines += [
        sep,
        row("Press ? or Esc to return"),
        bottom,
    ]
    return "\n".join(lines)


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
    tty = sys.stdout.isatty() and sys.stdin.isatty()
    no_alt = args.plain or os.environ.get("TERM") == "dumb" or os.environ.get("M8SHIFT_NO_ALT_SCREEN")
    if not tty or no_alt or os.name == "nt":
        forwarded = (["--interval", str(args.interval)] if "--interval" not in extra else []) + extra
        return scroll_fallback(engine, args.root, forwarded)
    atexit.register(restore)
    old = {}
    resize_pending = False
    resize_read = resize_write = None
    previous_wakeup = -1
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
    def resize(signum, frame):
        # The runtime writes the wakeup byte; the handler only marks pending work.
        nonlocal resize_pending
        resize_pending = True
    for sig, handler in ((signal.SIGINT, stop), (signal.SIGTERM, stop),
                         (getattr(signal, "SIGTSTP", None), suspend),
                         (getattr(signal, "SIGCONT", None), resume)):
        if sig is not None:
            old[sig] = signal.signal(sig, handler)
    winch = getattr(signal, "SIGWINCH", None)
    if winch is not None and os.name == "posix":
        resize_read, resize_write = _open_self_pipe()
        previous_wakeup = signal.set_wakeup_fd(resize_write, warn_on_full_buffer=False)
        old[winch] = signal.signal(winch, resize)
    enter()
    previous = None
    scroll_offset = 0
    expanded = False
    selected_turn = None
    selected_activity = None
    text_offset = 0
    help_visible = False
    agent_count = 2
    try:
        while True:
            size = shutil.get_terminal_size((80, 24))
            provision = _activity_request_limit(
                size.columns, size.lines, agent_count)
            snap = load_snapshot(engine, args.root, provision)
            agent_count = len(snap.get("agents") or [])
            max_scroll = activity_max_scroll(snap, size.columns, size.lines)
            scroll_offset = min(scroll_offset, max_scroll)
            if expanded and selected_turn is None:
                selected_turn = activity_adjacent_turn(snap, None, 0)
            if expanded and selected_turn is not None and selected_activity is None:
                selected_activity = load_activity_turn(engine, args.root, selected_turn)
            reader_record = (selected_activity or {
                "turn": None, "agent": None, "to": None, "done": "",
            }) if expanded else None
            frame = (render_help(size.columns, args.interval, size.lines) if help_visible else
                     render(snap, size.columns, interval=args.interval, utc=args.utc,
                            height=size.lines, activity_offset=scroll_offset,
                            expanded_activity=reader_record,
                            text_offset=text_offset))
            if frame != previous:
                sys.stdout.write(HOME + frame + "\x1b[J")
                sys.stdout.flush()
                previous = frame
            readers = [sys.stdin] + ([resize_read] if resize_read is not None else [])
            ready, _, _ = select.select(readers, [], [], max(.1, args.interval))
            if resize_pending or (resize_read is not None and resize_read in ready):
                resize_pending = False
                _drain_self_pipe(resize_read)
                previous = None
            if sys.stdin in ready:
                key = read_key()
                if not help_visible and key == "e":
                    expanded = not expanded
                    text_offset = 0
                    if expanded:
                        events = _activity_navigation(snap)
                        selected_turn = (events[min(scroll_offset, len(events) - 1)].get("turn")
                                         if events else None)
                        selected_activity = None
                    previous = None
                    continue
                if not help_visible and expanded and key in ("up", "down"):
                    adjacent = activity_adjacent_turn(
                        snap, selected_turn, -1 if key == "up" else 1)
                    if adjacent != selected_turn:
                        selected_turn, selected_activity = adjacent, None
                    text_offset = 0
                    previous = None
                    continue
                if not help_visible and expanded and key in ("left", "right"):
                    text_offset = activity_text_page(
                        snap, selected_activity, size.columns, size.lines,
                        text_offset, -1 if key == "left" else 1)
                    previous = None
                    continue
                quit_requested, refresh, scroll_offset, help_visible = key_effect(
                    key, scroll_offset, max_scroll, help_visible)
                if quit_requested:
                    break
                if refresh:
                    previous = None
    finally:
        if resize_write is not None:
            signal.set_wakeup_fd(previous_wakeup)
        for sig, handler in old.items():
            signal.signal(sig, handler)
        for fd in (resize_read, resize_write):
            if fd is not None:
                os.close(fd)
        restore()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        restore()
        print("m8shift-top: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
