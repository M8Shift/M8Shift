# RFC 051 — Usage advisory in the core display

Status: draft
Target: v3.54.0 candidate
Related issue: #47 follow-up (RFC 040 Phase 3)
Owner: core relay (display) + runtime usage companion (one additive schema field)

## Summary

RFC 040 Phase 3 shipped the usage numbers in the **companion**
(`m8shift-runtime.py usage status/snapshot`). A human watching the relay through
the **core** — `m8shift.py status`, `m8shift.py watch`, or `scripts/watch-status.sh`
(a thin wrapper that `exec`s `m8shift.py watch`) — sees the relay LOCK but not the
usage picture, and must run a second command in a second tool to see how much
quota is left.

The core already shows the usage-driven **pause** (the `cooldown` state → `PAUSED`
with a reason and reset time). This RFC adds a small, **read-only** usage
**advisory line** to `status` and `watch`, fed by the snapshot the companion
already wrote to a local sidecar — so the number surfaces wherever a human looks,
including `watch-status.sh`, without the core running an adapter, opening a socket,
or spawning the companion.

This is the "Voie A" of two options discussed with the operator (2026-07-05); the
richer "Voie B" (turning `watch-status.sh` into a composed watcher that calls the
companion live) is explicitly out of scope here.

## Problem

- The usage picture is one tool away from the surface a human watches.
- The core cannot run usage adapters (no network, no daemon, no subprocess for
  usage — RFC 040 design principle 1, "core remains passive"), so it cannot
  compute usage itself.
- But the companion **already writes** each normalized snapshot, append-only, to
  `.m8shift/runtime/usage.jsonl` (event `m8shift.runtime.event.v1`,
  `type: "usage.snapshot"`, `payload.snapshot` = a `m8shift.usage.snapshot.v1`).
  Reading that local file is a plain filesystem read — inside the charter.

## Goals

- Surface a one-line usage advisory per agent in `status` and `watch` (and thus
  `watch-status.sh`, for free).
- Read-only, charter-safe: a bounded local sidecar read; **never** run an adapter,
  open a socket, or spawn the companion; **never compute** — echo recorded bytes.
- Honest: show the recorded `provenance` verbatim and a **staleness** marker so a
  human never trusts an old number.
- Opt-in by construction and byte-identical when off: the sidecar only exists if
  the operator enabled usage monitoring; with no usable snapshot the display —
  human **and** `--json` — is byte-identical.

## Non-goals

- No live computation in the core. The advisory echoes recorded scalars; it never
  re-derives a ratio, an argmax, or a driving window.
- No new gating/pause logic. Pausing on usage stays the existing `cooldown`.
- No replacement for `m8shift-runtime.py usage status` (which runs adapters live).
- Voie B (composed live watcher in `watch-status.sh`) — separate, later.

## Prerequisite — one additive companion field (`decision_window`)

The snapshot records only the scalar `decision_ratio = round(max(ratios), 4)`; it
does **not** record which window produced that max. Rendering "which window / when
does it reset" from the scalar would force the core to **recompute** every
window's ratio and re-derive the argmax — exactly the live computation this RFC
forbids, with tie/rounding/top-level-fallback ambiguity.

So Part A of this work is a **schema-additive** change in the companion's
`normalize_usage_snapshot`, at the point the max is chosen: record
`decision_window: {kind, resets_at}` (the window that produced `decision_ratio`,
or `null` when the ratio came from the top-level `used_tokens/limit_tokens` or is
`unknown`). Additive and optional → existing readers and the byte-identity anchor
are unaffected. The core then **echoes** `decision_window` verbatim and computes
nothing.

**Tie rule (amendment E).** When two windows share the max ratio, the companion
picks the **first max in ratio-computation order** (deterministic), and a test
pins that behavior. A missing `decision_window` still renders **percentage-only**
in the core, with **no** core recomputation.

## Model — what the CORE adds (it owns none of this today)

The core has **no** usage stack: no `read_jsonl_diagnostic`, no snapshot fold, no
staleness helper — all of that lives only in `m8shift-runtime.py`, and the core
must **not** import the companion. So Part B adds a small, self-contained,
stdlib-only, independently unit-tested unit to `m8shift.py`:

1. **Path safety before opening (amendment A).** `lstat` the sidecar first and
   read **only a regular file**: a symlink (not followed), directory, device,
   FIFO, or unreadable path yields the no-usage display (byte-identical), never an
   open/read of a non-regular target.
2. **Bounded tolerant reader.** Open `.m8shift/runtime/usage.jsonl` with
   `encoding="utf-8", errors="replace"` (a bad byte must never raise mid-iteration
   — the companion's lazy `for line in fh` reader does **not** satisfy this) and
   **tail-read** at most the last `USAGE_TAIL_BYTES` (e.g. 256 KiB) / last N lines,
   folding backward until every roster agent is covered or the cap is hit — so a
   multi-MB sidecar is read in bounded time. **When the seek offset is > 0, discard
   the first (partial) line** (amendment D) so a tail that starts mid-line never
   mis-parses. Each line: tolerate `json.JSONDecodeError` / `RecursionError` /
   `ValueError`; skip non-dict lines; skip rows whose `schema` (of
   `payload.snapshot`) is not `m8shift.usage.snapshot.v1` (pin the dependency; a
   companion schema drift is skipped, not misrendered).
3. **Fold + agent validation (amendment B).** Render **only roster agents**;
   validate agent ids with `AGENT_RE`; require the event `agent` and
   `payload.snapshot.agent` to be present, valid, and **consistent** — skip a row
   on any mismatch (defeats a spoofed/mislabelled snapshot). Then keep the
   **file-order last** valid `usage.snapshot` per agent (last write wins, matching
   the companion).
4. **Validate before render (no computation).**
   - `decision_ratio`: rendered as a percentage only when
     `isinstance(dr, (int, float)) and not isinstance(dr, bool) and
     math.isfinite(dr)`; otherwise `—` (unknown). NaN / Infinity / string / bool →
     `—`, never a crash.
   - **Terminal/output safety (amendment C):** `provenance` and
     `decision_window.kind` are **not** arbitrary verbatim terminal output — a
     corrupt/hostile sidecar could carry ANSI escapes or control characters.
     Before human output they are sanitized to a short, safe, printable
     token-ish value: strip/refuse control characters and ANSI escapes, cap
     length, and fall back to `unknown`/omit on anything left unsafe. (This is
     display hardening only — the value still never feeds a decision.)
   - `decision_window.kind` and `.resets_at`: echoed (after the sanitization
     above); a missing / null / present-but-unparseable `resets_at` is **omitted**
     (never formatted raw).
   - staleness: `captured_at` age; missing or non-strict-`Z`-parseable → treated as
     stale/unknown (never a crash); past the fixed default (30 min, the companion's
     `--stale-after-minutes` default) the line is marked `stale`.

### Rendered line

```text
  claude   87% session_5h (official) · used 80M/5h · resets 20:00 · 2m ago
  codex    —  (local_estimate)       · used 80M/5h · 1.5B/wk · 0s ago
```

The `used …` fragment (issue #59) shows the actual token **consumption** — not
only the gating ratio — humanized per window (`used <count>/<window>`), so a
spent-only source (a `jsonl_scan`, whose ratio is `—`) still surfaces something
useful. It prefers `windows[].used`, falls back to the top-level `used_tokens`,
and — like every other field — is echo-only, bounded (`USAGE_TOKEN_DISPLAY_MAX`),
and sanitized; an implausible/invalid count is simply omitted.

A `── usage ──` block after the LOCK block in both `status` and `watch` (one
shared render helper). **Absent entirely** when the sidecar is absent **or holds
no usable snapshot** — byte-identical to today.

### `--json`

`status` / `watch` `--json` gain an **optional** `usage` array (last snapshot per
agent, plus computed `stale` boolean and `age_seconds`). The `usage` key is
**omitted entirely** whenever there is no usable snapshot (not `[]`), so a
present-but-empty/all-malformed sidecar is byte-identical to no sidecar. The array
echoes recorded values; it invents nothing. **JSON must never emit a non-finite
number (amendment C):** an invalid/NaN/Inf `decision_ratio` is serialized as
`null` (unknown), never `NaN`/`Infinity` (which is non-standard JSON).

## Charter and safety

- **Read-only**: no writes, no network, no subprocess, no adapter run, no
  companion import. The core opens exactly one local file it did not create, with
  a byte/line cap.
- **Intentional bounded exception to RFC 040 principle 1**: this is the first core
  read of a companion-authored artifact. The core remains the **sole authority for
  relay state**; the usage line is display-only and **never feeds a core
  decision** (the only usage-driven core transition stays the explicit `cooldown`).
  Because the value never gates, showing a stale number (marked `stale`) rather
  than degrading it to nothing is safe and deliberate.
- **Fail-open on every bad shape**: absent / directory / EACCES / broken-symlink
  sidecar → no block, no diagnostic line, output byte-identical; bad encoding →
  `errors="replace"`, never raises; deep nesting / bad JSON / non-dict lines →
  skipped; non-finite/non-numeric `decision_ratio` → `—`; unparseable
  `captured_at`/`resets_at` → stale/omitted. Nothing here can crash `status` or
  `watch`.
- **Honesty**: provenance verbatim; staleness marked; docs and the block state the
  numbers are "as last recorded by the usage companion", never computed by the
  core; schema-pinned so drift is skipped, not misrendered.

## Acceptance criteria

- **Part A**: the companion additively records `decision_window: {kind, resets_at}`
  (or `null`) in the snapshot; the byte-identity anchor
  `test_fixture_normalization_matches_pinned_schema_bytes` is updated once and
  stays pinned; existing readers ignore the optional field.
- With a usable sidecar, `status` and `watch` render one line per agent from the
  **file-order last** snapshot: percentage (or `—` for unknown/non-finite),
  window kind, provenance verbatim, reset time (omitted when null/unparseable),
  and a `stale` marker past the threshold.
- **Byte-identity when off**: no sidecar → human and `--json` output identical to
  today; sidecar present but empty / all-malformed / all-other-schema → identical
  too (no `── usage ──` block, no `usage` key).
- **Bad-shape, each a named test, all fail-open** (no crash, no partial garbage):
  invalid UTF-8 bytes; deeply-nested JSON (RecursionError); non-dict lines; a
  snapshot missing `decision_ratio`/`decision_window`/`provenance`/`captured_at`;
  `decision_ratio` = NaN / Infinity / `1e999` / string / bool → `—`; unparseable
  `captured_at`/`resets_at`; sidecar path is a directory or unreadable.
- **Path safety (A)**: a **symlink** sidecar is not followed, and a directory /
  device / FIFO / unreadable path produces byte-identical no-usage output — named
  tests for symlink-not-followed and non-regular/unreadable path.
- **Agent validation / spoofing (B)**: invalid agent id, non-roster agent, and an
  event `agent` ≠ `snapshot.agent` mismatch are each skipped — named tests.
- **Terminal/JSON safety (C)**: a `provenance` / `decision_window.kind` carrying
  ANSI escapes, control characters, or an over-long value is sanitized (no raw
  escape reaches the terminal); `--json` never emits `NaN`/`Infinity` (invalid
  `decision_ratio` → `null`) — named tests.
- **Tail partial line (D)**: a large sidecar whose tail window starts mid-line
  discards that partial first line and the last valid snapshot still wins — named
  test.
- **decision_window tie (E)**: two windows sharing the max → the companion records
  the deterministic first-max-in-ratio-order; a missing `decision_window` still
  renders percentage-only — named tests.
- **Bounded**: a multi-MB sidecar is read in bounded time (tail cap) and the
  file-order last snapshot still wins.
- **Read-only assertion**: rendering opens only the sidecar path and performs no
  write / network / subprocess / companion import.
- `watch-status.sh` shows the block with **no change to the script** (it forwards
  to core `watch`); `--changes-only` treats a usage-line delta as a change worth
  reprinting.

## Open questions for implementation review

- Show all roster agents or only those with a snapshot? (Proposed: only those with
  a usable snapshot — do not imply coverage that isn't configured.)
- Tail cap value (`USAGE_TAIL_BYTES`) and whether to also cap line count.
- Whether Part A (`decision_window`) ships in the same release as Part B or one
  release ahead (so every sidecar already carries the field before the core reads
  for it). Proposed: same release; the core treats a missing `decision_window` as
  "no window attribution" (percentage still shows), so ordering is not load-bearing.
