# RFC 069 — Top-owned incremental status fold

- **Status:** implemented (#79, 2026-07-15)
- **Scope:** the long-lived interactive `m8shift-top` status consumer.
- **Amends:** [RFC 061](061-rfc-bounded-adaptive-activity.md) consumer
  implementation only.
- **Preserves:** frozen `m8shift.status/1`, one-shot `status`, RFC 063 point
  reads, and [RFC 064](064-rfc-effective-time-accounting.md) accounting.

## Decision

The interactive top owns one in-memory incremental fold for its process
lifetime. On first refresh it fully parses the living `M8SHIFT.md`; later
refreshes read a bounded mutable prefix, verify append-only anchors, and parse
only the unmatched parser carry plus newly appended bytes. The one-shot
`status` CLI continues to perform a full parse. There is no disk cache,
sidecar, daemon, new command, or new source of relay authority.

This follows the measured #78 scaling result: full turn parsing cost about
13.7 ms on the then-current 1.1 MB journal, 87.9 ms at 5,000 turns, and 170.6
ms at 10,000 turns, while an incremental append cost 0.1–0.3 ms. A persistent
two-second dashboard benefits; a one-shot CLI does not amortize a cache.

## Shared builder and frozen contract

Core exposes an internal read-only builder that receives an already parsed
LOCK, retained complete turns, the total valid-turn count, one caller-owned
observation time, and RFC 061's requested activity limit. Both the ordinary
full status command and the incremental top call that builder. The full path
is the behavioral oracle.

The builder re-observes every non-journal input on every refresh: session/time
ledger, usage, heartbeat, task and decision counts, doctor findings, gate state,
and listeners. Project-name lookup accepts the already parsed LOCK so it cannot
silently reread the full journal. RFC 064 remains a flat status sibling and is
not moved into snapshot v1. RFC 061's `0..200` clamp, oldest-first activity,
exact `activity_truncated`, and 200-record bound are unchanged.

## Cache evidence and algorithm

The top retains:

- an EOF watermark measured in bytes relative to the first TURN marker, so a
  shorter or longer LOCK prefix does not invalidate a true append;
- bounded first-turn bytes and SHA-256 of the 256 bytes ending at the
  watermark;
- total valid-turn count and only the newest 200 complete parsed turns; and
- a bounded unmatched suffix after the last complete TURN END.

Each refresh opens the journal once, reads at most 64 KiB to recover the LOCK
and relocate the first TURN, verifies the head and prior-tail anchors, seeks to
the relative watermark, and reads the delta. It parses only `carry + delta`,
folds complete turns, and retains the new unmatched suffix. It compares the
open descriptor with the pathname after the read; a concurrent atomic
replacement cannot publish a mixed snapshot. Engine source is stat-checked on
every tick and dynamically loaded only when its version matches the companion.
Older, newer, or non-importable engines use the existing full subprocess path.

## Fail-closed invalidation matrix

The reader discards the candidate and rebuilds from the full oracle on first
use, shrink, archive rotation/head change, tail mismatch, invalid UTF-8,
oversized carry, engine replacement/version skew, or pathname replacement
during validation. A full snapshot with an oversized incomplete suffix is
valid, but it does not seed a cache; full parsing continues until the record is
complete. Normal core atomic replacement *between* refreshes is supported when
the relative anchors prove the same append-only turn stream. Inode identity is
therefore not used as a cross-refresh invariant.

Arbitrary manual rewriting is outside the fast-path trust boundary. Detected
violations degrade to a full parse, never to a guessed or partially validated
snapshot.

## Compatibility and proof gate

Canonical UTF-8 JSON (`ensure_ascii=False`, `sort_keys=True`) from the
incremental result must be byte-identical to the full builder with the same
clock and sidecars. The executable matrix covers initial load, stable refresh,
one and many appends, shorter/longer LOCK headers, rotation plus append,
truncation plus completion, deterministic atomic replacement during
validation, shrink, tail mismatch, engine/version replacement, limits 0, 8,
20, and 200, and RFC 064 sibling equality. Every invalidation asserts full
mode. Instrumented tests separately prove stable/one-append refreshes read only
bounded prefix + anchors + delta and invoke TURN parsing only for carry + delta.

Importing the engine is also tested for zero CLI output or other command-side
effects. Python 3.8, non-TTY fallback, lockstep checks, checksums, and the full
suite remain release gates.
