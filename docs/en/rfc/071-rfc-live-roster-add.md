# RFC 071 — Pen-guarded live roster addition

- **Status:** implemented (#89, 2026-07-15)
- **Scope:** one additive core command, `roster add <agent> --by <holder>`.
- **Builds on:** [RFC 001](001-rfc-roster.md),
  [RFC 002](002-rfc-n-agents.md), and the actor-binding rules in
  [RFC 038](038-rfc-multi-session.md).

## Problem

`init --agents` declares a roster when a relay is created, but changing it later
requires `init --force`. That operation resets the session and is therefore the
wrong authority for enrolling one additional identity in an active relay.

## Command and authority

```text
./m8shift.py roster add <agent> --by <holder>
```

The command is a relay mutation attributed to `--by`. The central RFC 038
binding gate resolves that actor before any lock is created. Under the relay's
internal file lock, the actor must still be an existing roster member and must
hold a non-expired `WORKING_<HOLDER>` pen. `IDLE`, `AWAITING_*`, `PAUSED`,
`DONE`, another holder, an expired lease, an invalid roster, or a corrupt LOCK
all refuse without mutation.

The new identity uses the existing normalized agent grammar. An exact duplicate
is a successful byte-for-byte no-op. Similar names remain distinct: `codex` and
`codex-2` are separate routing identities.

## State-preserving write contract

The operation changes only the value of the single `agents:` line inside the
LOCK block. It does not use the general LOCK renderer. Consequently it preserves
the current session, turn, holder, state, timestamps, expiry, note, models, free
text, and every closed TURN byte-for-byte. It emits no TURN, session event, state
transition, archive entry, task entry, or companion ledger record.

All input, current LOCK, live-pen, and prospective full-relay validation happens
before one atomic replacement of `M8SHIFT.md`. The internal lock serializes
concurrent additions, so each writer rereads the latest roster and no membership
update is lost. A missing or duplicate `agents:` field is refused; the command
does not guess how to migrate a legacy or ambiguous layout.

## Bootstrap boundary

Live membership and instruction bootstrap are deliberately separate. The
command never creates or edits `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, or another
anchor. It prints a manual-bootstrap warning directing the operator to the
protocol and a distinct launch-time identity.

This is particularly important for duplicate CLI instances such as `codex` and
`codex-2`: two identities must not silently share one generated identity stanza.
First-class per-instance anchor/provider templating is deferred. Once bootstrapped,
the new exact name participates in ordinary `--to`, `claim`, status, and routing
without a reset.

## Acceptance criteria

1. Adding `gemini` changes one LOCK line; after normalizing only `agents:`, the
   full relay is byte-identical, and the TURN suffix plus session/auxiliary
   ledger hashes are unchanged.
2. The current work window is unchanged and the holder can immediately hand off
   to the new name, which can claim normally.
3. `codex-2` routes as an exact distinct name, emits the bootstrap warning, and
   never overwrites `AGENTS.md`.
4. Duplicate addition is an idempotent no-op.
5. Non-holder, idle, expired, malformed-name, malformed-LOCK, and ambiguous
   `agents:` cases fail closed with `M8SHIFT.md` unchanged.
6. Concurrent additions serialize without a lost roster member or any change to
   non-roster state.

