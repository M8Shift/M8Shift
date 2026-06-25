# RFC — Session history

## Status

Accepted and implemented in v3.7.0.

## Problem

`log --all` gives a durable timeline of turns, but not a session-level view. After several
relay runs, a maintainer cannot quickly answer:

- how many relay sessions happened;
- which agents were configured;
- how many turns each session had;
- whether a session closed normally, is still open, or was reset;
- which `m8shift.py` version produced the coordination state.

The turn journal remains the canonical work dialogue, but it is the wrong shape for this
operational question.

## Decision

Add a passive session ledger:

```text
M8SHIFT.sessions.jsonl
```

The file is append-only and contains one JSON object per event:

- `start` when `init` creates or force-recreates `M8SHIFT.md`;
- `done` when `done <agent>` closes a non-closed session;
- `reset` when `init --force` replaces an open session.

Add an optional `session:` field to the `LOCK` block. New relay files carry it; legacy
files without it remain valid.

Add:

```bash
./m8shift.py history [--limit N] [--oneline] [--json]
```

`history` folds the JSONL events into one readable entry per session and enriches the
current session from the `LOCK` plus the turn journal.

`history --json` exposes the same folded summary as the human view. It deliberately
does not mirror raw JSONL `events` or internal fold fields such as `turn_start`.

## Kept

- Plain text / stdlib only.
- Append-only event storage.
- Read-only `history`; it never repairs, routes, claims, waits, or feeds the mutex.
- Backward compatibility: old `M8SHIFT.md` files without `session:` still load, and
  `history` can show a single legacy session derived from the existing turn journal.
- Human-sortable session ids: `YYYYMMDDTHHMMSSZ-xxxxxxxx`.
- Version visibility: each event records `m8shift_version`.

## Rejected

- A daemon or watcher that tracks sessions externally.
- Rewriting a single mutable session database row at close time.
- Inferring multiple historical sessions from pre-ledger turn logs. The boundary is not
  reliably present, so legacy files are shown as one legacy session.
- Making session history part of claimability or handoff routing. It is observability
  only.
- Storing full turn bodies again in the session ledger. The turn journal and archive
  already own that data.

## Data model

Example start event:

```json
{"event":"start","session_id":"20260624T120000Z-1a2b3c4d","started_at":"2026-06-24T12:00:00Z","project":"demo","agents":"claude,codex","lang":"en","turn_start":0,"m8shift_version":"3.7.0"}
```

Example done event:

```json
{"event":"done","session_id":"20260624T120000Z-1a2b3c4d","closed_at":"2026-06-24T12:42:00Z","closed_by":"codex","turn_end":4,"turns":4,"agents_used":"claude,codex","m8shift_version":"3.7.0"}
```

Example human output:

```text
m8shift.py v3.7.0
── session history ────────────────────
#1 20260624T120000Z-1a2b3c4d  2026-06-24T12:00:00Z -> 2026-06-24T12:42:00Z  DONE
  agents: claude,codex
  turns: 4
  used: claude,codex
  closed_by: codex
  version: 3.7.0
```

## Invariants

- `history` is read-only.
- `M8SHIFT.sessions.jsonl` is append-only by convention.
- The session ledger is never read by `claim`, `append`, `wait`, `release`, or `done`
  for routing decisions.
- `history --json` exposes a stable summary contract, not the raw event ledger.
- `init --force` records a `reset` event for an open current session before starting
  the replacement session.
- `done` records at most one `done` event per actual transition from non-`DONE` to
  `DONE`.
