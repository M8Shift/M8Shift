# v3.63.0 release notes

## Version

**v3.63.0 (Révision).** Backwards-compatible feature release: a third live
vendor, honest quota display, instant dashboard navigation, and the arbitrated
inter-agent exchange standard. No relay-format or CLI break.

## Highlights

### Gemini becomes a live vendor (RFC 073 slice 3)

The registered Gemini adapter graduates from validated stub to live managed
launches: exact non-interactive argv, pinned model, API-key-only
authentication (`GEMINI_API_KEY` via `requires_env` and the child allowlist —
the upstream OAuth free tier no longer exists), bounded version health, and
fail-closed native resume. Proven end to end: a real Gemini process claimed a
pen, passed `may-i-write`, and appended a turn in an isolated relay. An
adopter default registry stays healthy without the key (inactive example rows
warn instead of erroring).

### Quota you can plan with (#203)

Every human usage surface now leads with the explicitly labelled **remaining**
quota — the actionable number, aligned with vendor account UIs — derived from
the vendor-cumulative figure of the full window (decision window first, 5h
second, honest `n/a` when unknown). The vendor figure is authoritative and
resyncs through resets, including out-of-band manual full resets, emitting an
observable `usage.reset_detected` event. Machine surfaces carry both
`used_ratio` and the derived `remaining_ratio`; guard thresholds are unchanged.

### Navigation without the lag (#203)

Dashboard navigation keys re-render from the cached snapshot: a keystroke
performs **zero** engine subprocess spawns (previously ~0.4 s of spawns per
autorepeat event), key bursts drain into a single frame, and reader turns are
cached. AWAITING states render a neutral no-TTL strip instead of a misleading
stale gauge.

### A fourth vendor enters the registry

A source-validated **Mistral Vibe** adapter stub registers alongside Gemini
(declarative argv, fail-closed live surfaces, conformance fixture), with the
core anchor mapping verified against the CLI's actual anchor file. Live
support follows the same path Gemini took.

### RFC 074 — standardized inter-agent exchange (arbitrated)

The exchange standard lands already **arbitrated**: 15 primary shift stages
carried in a structured turn field (never inferred from prose), a versioned
vendor-neutral turn schema succeeding the emergent Stage 4 fields, and a
read-only whole-shift export with mandatory digests, denylist redaction, and
an explicit operator gate. Ten operator decisions are recorded in the RFC;
implementation remains separately authorized.

### Also shipped

Advisory routing matrix phase 1 (`route recommend`, launch=false); visible
ellipsis on truncated model/effort identifiers across all surfaces; per-turn
effort declarations rendered with the may-be-stale footnote.

## Deferred

- Live Vibe launches, probed Gemini resume, and the #59 routing-matrix
  extension (RFC 073 slice 4) — accepted, not shipped.
- The bootstrap-experience batch (quickstart, runner provisioning + version
  handshake, sandbox fast-fail, usage bootstrap, top-at-init) — scoped from
  real adopter evidence, next.

## Upgrade and verification

Update in place with `python3 m8shift.py update` (or
`scripts/m8shift-self-update.py`, dry-run by default, snapshot + rollback).
Relay state is never touched. Verify: `./m8shift.py --version` prints 3.63.0;
usage cells show a labelled remaining figure; navigation is instant at any
journal size; `python3 -m unittest discover -s tests` and `python -m pytest -q`
are both green (the release gate runs both collectors on two interpreters and
a Linux container).
