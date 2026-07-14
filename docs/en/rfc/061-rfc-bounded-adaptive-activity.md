# RFC 061 — Bounded adaptive activity provision

- **Status:** implemented (#61, 2026-07-14)
- **Scope:** core status snapshot activity and the interactive read-only dashboard.
- **Builds on:** [RFC 058](058-rfc-go-forward-rfc-discipline.md) and
  [RFC 060](060-rfc-adaptive-terminal-geometry.md).

## Decision

Core keeps the backward-compatible eight-event snapshot default. The read-only
`status --activity-limit N` option lets a consumer request another bound;
requests are clamped to `0..200`. The snapshot reports the effective
`activity_limit` and whether older parsed live-relay turns were omitted through
`activity_truncated`. Plain `status` and `status --json` without the option
remain lean at eight events.

The dashboard requests its current event viewport plus 180 rows of scroll
headroom, capped at 200. It performs no archive read, journal paging, or extra
journal I/O. Optionally paging the complete history in-dashboard is additive
future work, not part of this contract; deeper history remains available via
the existing peek/journal surfaces.

## Viewport and position semantics

Let `C` be RFC 060's physical activity capacity: terminal height minus fixed
chrome. The readable event viewport is `V = min(C, 20)`. Eight rows remain the
normal minimum target when geometry permits, constrained terminals degrade to
`0..7`, and ordinary fullscreen terminals expose roughly 16–20 events. Any
physical rows beyond `V` are structural blank fill, preserving the footer and
exact frame height without turning very tall terminals into an unreadable wall.

Activity labels use immutable turn numbers, not buffer indices. They render the
oldest and newest visible positions against the greatest provided turn number,
for example `ACTIVITY turns 535-554 / 734`. Because turns are monotonic positions
in relay history and the provision includes the newest turn, 734 is the true
total without reading the archive. When scrolling reaches the oldest event in a
truncated provision, the label adds
`<older turns on disk — peek/journal>`. The marker is absent everywhere else.

Resize preserves the current offset and applies RFC 060's clamp against the new
`len(activity) - V` maximum. Core activity remains oldest-first for compatible
consumers; the dashboard presents newest-first.

## Bounded projection and expanded-reader compatibility

Every projected text field remains sanitized and bounded to 120 code points.
Malformed turn structures fail open and do not weaken the 200-event maximum.
The later expanded, word-wrapped reader (#63) will fetch the selected turn's full
text on demand by immutable turn number. It will not enlarge activity snapshot
fields or carry full turn bodies in every refresh. This preserves the bounded
status contract and avoids reworking #61 when expanded reading is added.

## Acceptance criteria

1. Core boundaries 0, 8, 199, 200, and 201 retain the newest requested turns;
   201 with a 200 limit reports truncation and turns 2 through 201.
2. No option yields eight events; limits 20 and 5000 yield at most 20 and 200,
   respectively; `status --json` stays at eight by default.
3. Malformed activity inputs fail open and all projected strings remain within
   the snapshot text bound.
4. Capacities 0, 7, 8, 16, 20, and greater than 20 preserve viewport, blank-fill,
   scrolling, resize clamp, and frame fidelity in both layouts.
5. A 200-event provision ending at turn 734 labels visible real turn positions
   with `/ 734`; the buffer-edge marker appears only at the truncated floor.
6. Python 3.8, non-TTY fallback, checksums, and the full suite remain green.
