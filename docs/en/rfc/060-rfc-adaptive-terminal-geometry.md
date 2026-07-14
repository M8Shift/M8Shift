# RFC 060 — Adaptive terminal geometry

- **Status:** implemented (#55, 2026-07-14)
- **Scope:** the interactive read-only `m8shift-top.py` dashboard.
- **Builds on:** [RFC 025](025-rfc-status-runtime.md),
  [RFC 058](058-rfc-go-forward-rfc-discipline.md), and
  [RFC 059](059-rfc-terminal-colour-capability-semantic-rendering.md).

## Decision

The interactive dashboard uses the real terminal columns and lines reported by
`shutil.get_terminal_size()`. Adaptive geometry is automatic: there is no
`--fullscreen`, `--adaptive`, or configurable maximum-width option. The minimum
effective width remains 24 columns, the stacked layout remains selected below
100 columns, and the wide tabulated layout remains selected at 100 columns or
more. Non-TTY, plain/dumb-terminal, native-Windows, and piped invocations retain
the existing core `watch` fallback.

The 120-column wide frame is the compatibility baseline. Its ANSI-stripped bytes
remain unchanged. Above 120 columns, the frame consumes every reported column;
headers, separators, content, help, and borders all expand to the same width.

## Deterministic wide tracks

Every wide row is composed from tracks whose baseline widths sum to the
118-column inner frame. For `extra = width - 120`, fixed tracks keep their
baseline width and flexible tracks receive `extra` by weighted largest
remainder: take each integer floor, then award residual columns by descending
fractional remainder with left-to-right tie-breaking. The renderer asserts that
the resulting tracks sum to `width - 2` before truncating or padding any cell.

| section | 120-column baseline tracks | flexible tracks and weights |
|---|---|---|
| PEN | `9,8,17,10,26,48` | claimed `1`, heartbeat `1` |
| TTL | `10,30,12,66` | expiry/status `1`; the gauge stays 28 cells |
| AGENTS | `10,10,18,14,21,45` | identity `1`, model `1`, 5h `2`, weekly `2` |
| LISTEN / LEDGER / TURN | `10,108` | payload `1` |
| ACTIVITY | `8,21,8,10,22,14,35` | model `1`, action `1`, note `2` |

The activity baseline corresponds to TURN 8, TIME 21, HOLD 8, AGENT 10,
MODEL 22, ACTION 14, and NOTE 35. Existing sanitization and code-point width
semantics remain unchanged; this RFC does not introduce `wcwidth` behavior.

## Height and activity viewport

The activity viewport has zero bottom margin. Its capacity is:

- wide: `max(0, height - (13 + agent_count))`;
- stacked: `max(0, height - (16 + agent_count))`.

When fewer events exist than the capacity, framed blank activity rows fill the
remainder, so a frame whose terminal can contain its fixed chrome has exactly
`height` rows and its footer occupies the last row. Blank rows do not change the
`ACTIVITY n-m/total` count. When the terminal is shorter than the fixed chrome,
activity capacity is zero and the renderer retains PEN, TTL, agent, listener,
ledger, and turn safety information; terminal viewport cropping is preferable
to silently dropping those rows.

The current activity offset is preserved across geometry changes where valid
and clamped only to the new maximum. Growing therefore reveals more rows without
jumping, while shrinking retains the same first event where possible. Help uses
the real width and fills available height with framed blank rows.

## Resize delivery

On POSIX systems with `SIGWINCH`, the interactive loop installs a nonblocking
self-pipe through `signal.set_wakeup_fd`. The signal handler only marks resize
work pending; the Python runtime writes the wakeup byte. The loop drains all queued bytes,
coalescing bursts, then reads both dimensions, recomputes tracks and capacity,
clamps scrolling, and forces one redraw without closing help. Snapshot loading
and rendering never occur in the handler. Platforms without `SIGWINCH` retain
the size check on every refresh tick.

Stop, suspend, resume, alternate-screen restoration, semantic colours,
live-turn attribution, and keyboard navigation keep their existing contracts.

## Acceptance criteria

1. Widths 24, 80, 99, 100, 120, 121, 160, and 240 preserve frame fidelity in
   plain and ANSI output across zero/multiple agents and activity events.
2. The 120-column plain frame matches its pre-RFC byte hash; wider frames equal
   the reported width and their weighted track plans sum exactly to `width - 2`.
3. At or above fixed-chrome height, frames contain exactly the reported line
   count, use the final row for the footer, and fill unused activity capacity.
4. Resize wakeups coalesce safely, immediately recompute both dimensions, and
   preserve/clamp activity offset and help visibility.
5. The 100-column breakpoint, minimum width, semantic roles, live-turn label,
   keyboard controls, and non-TTY fallback remain unchanged.
