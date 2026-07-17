# v3.62.0 release notes

## Version

**v3.62.0 (Révision).** Backwards-compatible feature release: liveness
evidence across the status snapshot, the `m8shift-top` dashboard, the runtime
listener, and the notification path. No relay-format or CLI break; snapshot
fields are additive.

## Highlights

### Usage freshness that cannot lie (#193)

The status snapshot now carries `captured_at`, `age_seconds`, `freshness`, and
`stale` for every agent-usage row, and `m8shift-top` renders a mandatory
`STALE` marker *before* any stale ratio — truncation-immune by construction:
no visible percentage can outlive its marker, at any width, colour tier, or
`NO_COLOR`. Machine readers get the same fields through `status --json`.

### Producers you can pronounce dead (#193)

`usage watch` records a per-agent lifecycle sidecar (pid, apply/advisory mode,
heartbeat, phase). Stale data and a dead producer are now separate doctor
findings: the dashboard can say *the number is old* and *nobody is refreshing
it* independently.

### Stranded turns get noticed (#192)

For every `AWAITING_<X>` the core derives an advisory attention verdict —
`covered`, `human_resume_needed`, or `stranded` — from listener, presence, and
usage-watch evidence. Damaged or undecodable evidence classifies as `unknown`,
never as covered. Past the strict 300 s boundary the runtime emits a
deduplicated, local-tier-only RFC 027 `stranded` notification. A new
`listener start --notify-only` gives interactive agents durable human wake-up
without provider invocation; it is never counted as covered.

### A listening contract with teeth (#192)

RFC 062, the protocol mirror, the agent pack, and the compact floor stanza are
sharpened: an expiring bounded wait counts as listening only while the agent
stays blocked on it; long off-relay work needs a supervised persistent
watcher, and every halt re-arms when no supervisor exists.

### Hardening from the review chain

The core sidecar reader survives invalid UTF-8 and adversarially deep JSON
(diagnostics, never a status/watch crash); notification I/O failures degrade
without ending a listener loop; damaged evidence can never upgrade a
notify-only listener to covered; stdout-only tiers deduplicate. Two of these
were empirically-reproduced blockers found in adversarial review before merge.

## Deferred

- Accepted supervisor-hardening follow-ups (atomic supervisor singleton lock,
  unreadable-start-identity restart on Windows, post-detach child-survival
  confirmation, a `needs_reconciliation` resolver command) — next batch.
- RFC 073 slices 3–4 (live Gemini + probed native resume; the #59
  routing-matrix extension) remain accepted, not shipped.

## Upgrade and verification

Update in place with `python3 m8shift.py update` (or the operator wrapper
`scripts/m8shift-self-update.py`, dry-run by default, snapshot + rollback on
failure). Relay state is never touched. Verify: `./m8shift.py --version`
prints 3.62.0; `status` on an awaited agent shows an attention line;
`m8shift-top` marks any stale usage row `STALE`; `python3 -m unittest
discover -s tests` is green (1103 tests, 3 skips at time of release).
