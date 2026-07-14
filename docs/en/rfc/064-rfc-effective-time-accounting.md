# RFC 064 — Effective-work and non-work time accounting

- **Status:** draft / design only (#68, #71)
- **Date:** 2026-07-14
- **Scope:** read-only session/work-item accounting in the core status surface and
  `m8shift-top`; append-only state-transition evidence in the session ledger.
- **Builds on:** [RFC 011](011-rfc-session-history.md),
  [RFC 021](021-rfc-pause-resume.md),
  [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md),
  [RFC 060](060-rfc-adaptive-terminal-geometry.md), and
  [RFC 061](061-rfc-bounded-adaptive-activity.md).

## 0. Proposal summary

Separate the current wall-clock session duration into four mutually exclusive state
buckets:

1. **effective work** — time in `WORKING_<agent>`;
2. **awaiting** — time in `AWAITING_<agent>`;
3. **paused** — time in `PAUSED`;
4. **idle** — time in `IDLE`.

`awaiting + paused + idle` is the global **non-work** total. `DONE` closes the
measurement interval and accrues no time. An unknown/future state, malformed evidence,
or a historical interval whose claim boundary was never recorded goes into a fifth,
visible **unclassified** bucket. The invariant is:

```text
wall = effective_work + awaiting + paused + idle + unclassified
wall = effective_work + non_work + unclassified
```

The first version deliberately uses `WORKING_*` as an operational proxy, not as a
productivity claim. It does not subtract time merely because heartbeats are absent or
present. Heartbeats prove holder liveness; they do not prove useful activity.

Going forward, every successful state change records a compact transition event in the
append-only session ledger. This makes the fold exact. Existing sessions are computed
retroactively only where their current evidence supports it; missing historical claim
boundaries remain `unclassified` rather than being guessed.

## 1. Metric contract

### 1.1 Measurement interval

For one session, measurement begins at the valid `start` event timestamp and ends at the
first valid `done` or `reset` timestamp. For an open session it ends at the command's
single captured `as_of` timestamp. All arithmetic uses UTC instants and whole seconds.
Negative intervals caused by clock regression are not clamped into another bucket: the
affected interval is unclassified and a diagnostic is returned.

The existing `session_duration_seconds` remains wall-clock duration. It is not renamed
or silently reinterpreted.

### 1.2 State classification

| State during `[t0, t1)` | Bucket | Attribution |
|---|---|---|
| `WORKING_<agent>` | `effective_work` | that agent; optional primary work item |
| `AWAITING_<agent>` | `awaiting` | global non-work; optionally report awaited agent |
| `PAUSED` | `paused` | global non-work |
| `IDLE` | `idle` | global non-work |
| `DONE` | none | terminal boundary only |
| missing, malformed, unsupported, or ambiguous | `unclassified` | none |

The interval is half-open so a transition instant is never double-counted. Per-agent
effective-work totals sum to the session effective-work total. Per-work-item totals plus
`unattributed_work_seconds` also sum to it; a second work item never duplicates seconds.

### 1.3 What “effective” does and does not mean

The public JSON key is `effective_work_seconds` because that is the operator-facing
question. Human displays add `*` and the explanation `WORKING-state proxy` whenever
space permits.

This metric means “the relay granted this agent the exclusive work window.” It does not
measure keystrokes, CPU use, model tokens, result quality, or human labour. In
particular, an agent that parks a `WORKING_*` pen inflates the proxy. RFC 021/049/062
already make that state misuse visible and recoverable; this RFC does not pretend to
correct it statistically.

Heartbeat cadence is rejected as a v1 refinement:

- a protective heartbeat establishes life, not progress;
- an interactive holder can work without a historical heartbeat stream;
- mutable sidecars and listener logs are not a complete, durable session journal;
- subtracting gaps would make two equivalent work turns depend on their host wrapper.

A future activity-sampling metric, if evidence supports one, must use a different name
and RFC. It must not retroactively change this state-duration contract.

## 2. Canonical transition evidence

### 2.1 Additive session-ledger event

Every successful operation that changes `LOCK.state` appends one event under the same
core file lock:

```json
{
  "event": "state",
  "session_id": "20260714T120000Z-1a2b3c4d",
  "at": "2026-07-14T12:04:05Z",
  "from_state": "AWAITING_CODEX",
  "to_state": "WORKING_CODEX",
  "actor": "codex",
  "turn": 12,
  "operation": "claim",
  "work_window_id": "8f6c2d11",
  "work_item": "task:68",
  "m8shift_version": "3.x.y"
}
```

Required fields are `event`, `session_id`, `at`, `from_state`, `to_state`, `actor`,
`turn`, and `operation`. `work_window_id` is required when entering or leaving a
`WORKING_*` interval. `work_item` is optional, bounded single-line metadata.

`work_window_id` is a deterministic opaque digest of session id, agent, entering turn,
and the claim timestamp already stored in `LOCK.since`. The leaving command can therefore
recompute the same id without adding a mutable field to `LOCK`; the digest is correlation
metadata, not authentication or authority.

The transition is observability only. It never drives claimability, routing, expiry, or
recovery; the live `LOCK` remains authoritative. Existing `start`, `pause`, `resume`,
`force`, `done`, and `reset` events remain valid and retain their present meanings.

Transitions are emitted for `claim` (except a same-state `--refresh`), `append`,
`pause`, `cooldown`, `resume`, `release`, force-claim/force-release/steer, `done`, and
any future command that changes the state. `init`'s existing `start` event is the initial
transition to `IDLE`; `done`/`reset` remain the terminal boundary. Repeated cooldown
updates that leave the state at `PAUSED` are audit events, not new duration intervals.

### 2.2 Ordering and failure rules

The fold uses append order and validates timestamps; it does not sort malformed or
contradictory rows into a plausible story. A valid transition must have
`from_state == previous.to_state`. Duplicate events with the same transition identity
are ignored once. A gap, contradiction, bad timestamp, clock regression, or mismatched
session makes the affected range unclassified and produces a stable diagnostic.

At read time the current `LOCK.state` and `LOCK.since` provide the open interval's final
anchor only when they connect to the last valid transition. They never repair a broken
historical chain silently.

The existing command mutation remains authoritative if appending observational evidence
fails. The command returns a prominent warning and `doctor` reports
`accounting.timeline_gap`; it must not roll back or corrupt a successful baton change.

### 2.3 Work-item attribution

The optional primary work item is an opaque, sanitized reference such as `task:68` or
`issue:150`; it is not looked up in the task board or a forge. This preserves RFC 006's
rule that the advisory task journal never gates `claim`.

Proposed inputs are:

```bash
./m8shift.py claim codex --work-item task:68
./m8shift.py next codex --work-item task:68
./m8shift.py work-tag codex task:68
```

`work-tag` is allowed only for the current `WORKING_<agent>` holder. It appends a
`work_tag` event referencing the current `work_window_id`; it does not mutate `LOCK` or
alter the recorded time boundaries or duration. The tag applies to that whole work window,
which lets `next` claim and
peek before choosing the tag. A second tag replaces the attribution for that one window
in the derived view without rewriting the ledger; the last valid tag wins and the audit
history remains visible.

Only one primary work item may own a work interval. Combined work stays under an
explicit umbrella reference or is reported as unattributed; it is never counted once
per label.

## 3. Retroactive computation and evidence quality

### 3.1 What the current journal can prove

Before RFC 064 telemetry, the durable data contains:

- session `start`, `pause`, `resume`, `force`, `done`, and `reset` events;
- completed-turn `at` timestamps (for newer turns), which prove the transition from
  `WORKING_<author>` to `AWAITING_<recipient>` at append time;
- only the **current** state's `LOCK.since` boundary.

It does **not** contain historical ordinary-claim timestamps. Therefore an interval
between one append and the next cannot be split exactly between `AWAITING_*` and
`WORKING_*`. Historical heartbeat sidecars cannot repair this: they are incomplete and
prove liveness only. Exact full retroactivity for a pre-RFC-064 shift is impossible from
the canonical records.

### 3.2 Required legacy behavior

The reader derives every interval that is directly supported by start/pause/resume/
force/done/reset events, completed-turn timestamps, and the current `LOCK.since`. Any
span that needs a missing claim boundary is `unclassified`.

The response reports:

- `quality: "exact"` when `unclassified_seconds == 0`;
- `quality: "partial"` otherwise;
- `coverage_ratio = (wall - unclassified) / wall` when wall is non-zero;
- `telemetry_started_at`, the first RFC-064 transition boundary, when present;
- stable diagnostics explaining each excluded span class.

Displayed effective-work and non-work totals in a partial record are lower bounds over
classified evidence, rendered with `≥` rather than as complete totals. No default
“assume immediate claim,” “assume claim at midpoint,” or heartbeat interpolation is
permitted. An opt-in estimate would be a different metric and must never populate these
keys.

Pre-telemetry work cannot be assigned honestly to a work item. It remains unclassified
or unattributed, even if turn prose mentions an issue number; free text is not parsed
into accounting authority.

## 4. Read surfaces and JSON contract

### 4.1 Dedicated read command

```bash
./m8shift.py time [current|SESSION_ID] [--json]
```

This command is read-only and may inspect the full live/archive journal for legacy
evidence. Its JSON response is `m8shift.time-accounting/1` and includes the full
per-agent and per-work-item breakdown.

Representative shape:

```json
{
  "schema": "m8shift.time-accounting/1",
  "session_id": "20260714T120000Z-1a2b3c4d",
  "as_of": "2026-07-14T14:00:00Z",
  "quality": "partial",
  "wall_seconds": 7200,
  "effective_work_seconds": 1800,
  "non_work_seconds": 2400,
  "awaiting_seconds": 1200,
  "paused_seconds": 900,
  "idle_seconds": 300,
  "unclassified_seconds": 3000,
  "coverage_ratio": 0.583333,
  "unattributed_work_seconds": 600,
  "agents": [{"id": "codex", "effective_work_seconds": 1800}],
  "work_items": [{"ref": "task:68", "effective_work_seconds": 1200}],
  "diagnostics": ["legacy_claim_boundaries_missing"]
}
```

Integer second fields obey the two sum invariants. Lists have deterministic ordering.
Malformed ledger lines are ignored by the existing tolerant parser but reflected in
quality/diagnostics when they intersect the selected session.

### 4.2 `status --json`

The current-session response gains one additive top-level sibling:

```json
"time_accounting": {
  "schema": "m8shift.time-accounting/1",
  "quality": "exact",
  "wall_seconds": 7200,
  "effective_work_seconds": 3000,
  "non_work_seconds": 4200,
  "awaiting_seconds": 2400,
  "paused_seconds": 1200,
  "idle_seconds": 600,
  "unclassified_seconds": 0,
  "coverage_ratio": 1.0
}
```

The frozen `snapshot.schema == "m8shift.status/1"` object and all legacy flat keys stay
unchanged. The status projection omits per-work-item lists and verbose diagnostics so
the two-second dashboard path stays bounded. `m8shift-top` composes the sibling into
its internal view; it does not widen snapshot v1.

For an established RFC-064 timeline, status folds only transition events for the
current session. Legacy archive enrichment belongs to the explicit `time` command, not
the automatic refresh path. Status still exposes pre-telemetry wall time as
`unclassified`, so it never silently reports a recent slice as the whole shift.

## 5. Human display

Verbose `status` adds a compact block after the LOCK and before usage:

```text
── TIME ───────────────────────────────
  effective*  ≥ 5h 18m  (claude 3h 02m · codex 2h 16m)
  non-work    ≥ 9h 41m  (await 2h 10m · pause 7h 20m · idle 11m)
  unclassified 3h 07m   coverage 82%
  * WORKING-state proxy; not productivity
```

The `≥` and unclassified line disappear when quality is exact.

`m8shift-top` adds one global session strip immediately above the keyboard-help footer,
never one value per activity row:

```text
TIME  effective* 5h18 · non-work 9h41 (await 2h10 · pause 7h20 · idle 0h11) · unknown 3h07
```

At narrow widths the required priority is `effective`, `non-work`, then `unknown`; the
three-category non-work detail may collapse behind `non-work` but remains available in
`status`/`time`. Unknown is never truncated while quality is partial. Adding the strip
reduces the adaptive ACTIVITY capacity by one physical row; RFC 060's exact frame height
and RFC 061's buffer-edge semantics remain intact.

Colours are non-judgmental and redundant: effective uses the normal accent, non-work is
dim/cyan, and unclassified is amber. Non-work is not an error condition.

## 6. Performance, compatibility, and safety

- The core remains stdlib-only and network-free.
- Accounting is derived observability and never participates in routing, claimability,
  TTL, liveness, task gating, or stale recovery.
- Relays without transition events continue to work and return partial accounting.
- Transition rows are compact and append-only. Implementation must benchmark a
  10,000-transition current session and keep `status --json` within the existing
  dashboard refresh budget; an index/cache, if needed, is disposable derived state and
  must rebuild from the journal without changing totals.
- One `as_of` instant is captured per response, so displayed components cannot drift
  across the fold.
- All labels are bounded and terminal-sanitized. No turn body, task description, or
  relay prose is interpreted as a state/task signal.
- A corrupted accounting trail degrades to partial/unclassified; it never bricks status
  or the relay.

## 7. Delivery plan

### Phase A — timeline and fold

- emit transition evidence for every state-changing command;
- add deterministic folding, quality, diagnostics, and invariant tests;
- add work-window ids and optional work-item tagging;
- dogfood the fold on the current long-lived session and record its honest partial
  coverage rather than a fabricated retroactive total.

### Phase B — read surfaces

- ship `time [session] [--json]`;
- add the bounded `time_accounting` sibling to `status --json`;
- add verbose status rendering and retain all frozen snapshot-v1/flat contracts.

### Phase C — dashboard

- add the global bottom strip to compact and wide renderers;
- re-budget activity capacity by one row;
- verify 80/120/160 columns, small heights, non-TTY fallback, and resize behavior.

## 8. Acceptance criteria

1. For an exact synthetic timeline, every second belongs to exactly one of effective,
   awaiting, paused, or idle, and both sum invariants hold.
2. Per-agent totals sum to effective work; per-work-item plus unattributed work also
   sums to effective work without double-counting.
3. A pre-RFC-064 inter-turn span with no claim timestamp is unclassified and renders as
   partial/`≥`; no heuristic estimate populates effective or non-work.
4. `WORKING_*` time is counted through its recorded transition even with missing or
   frequent heartbeats; heartbeat cadence does not change the result.
5. Clock regressions, broken state chains, duplicate events, unknown states, malformed
   rows, and a corrupt optional cache fail visibly to unclassified without affecting
   relay operation.
6. Every state-changing path emits one transition; `claim --refresh` and same-state
   cooldown refreshes do not create false duration boundaries.
7. Work-item tags are bounded, do not query/gate the task board, and never give one
   second to multiple primary items.
8. `status --json` preserves all legacy flat keys and the exact
   `m8shift.status/1` snapshot shape while adding the namespaced sibling.
9. `m8shift-top` shows one global bottom strip and preserves exact frame geometry,
   activity navigation, buffer edges, expanded reader behavior, and non-TTY fallback.
10. Python 3.8, checksums, RFC index integrity, the full suite, and the
    10,000-transition performance fixture remain green.

## 9. Operator decisions requested

1. **Approve `WORKING_*` as the v1 effective-work proxy**, with the visible
   “not productivity” qualification and no heartbeat subtraction.
2. **Approve honest partial retroactivity:** older missing claim boundaries become
   unclassified and totals render as lower bounds. Exact reconstruction of the current
   pre-telemetry shift cannot be promised from data that was never recorded.
3. **Approve one optional primary work-item reference per work window**, with no task
   board/forge lookup and no double-counted multi-tag allocation.
4. **Approve the permanent global TIME strip immediately above the dashboard key
   footer**, costing one activity row at all heights.

Implementation starts only after these four decisions and adversarial review of the
transition/failure contract.
