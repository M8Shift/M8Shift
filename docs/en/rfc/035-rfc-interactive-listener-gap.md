# RFC 035 — Interactive listener gap: wait readiness versus UI resumption

- **Status:** proposed
- **Date:** 2026-06-30
- **Scope:** make interactive-agent waiting observable and recoverable when a terminal
  `wait` process detects readiness but the agent UI is not automatically resumed.
- **Builds on:** [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md),
  [016-rfc-cooperative-turn-request.md](016-rfc-cooperative-turn-request.md),
  [021-rfc-pause-resume.md](021-rfc-pause-resume.md),
  [025-rfc-status-runtime.md](025-rfc-status-runtime.md),
  [027-rfc-notifications.md](027-rfc-notifications.md).

## 1. Problem

`m8shift.py wait <agent>` correctly watches the relay. When the relay reaches
`AWAITING_<agent>`, the process exits with a "your turn" message.

That is not enough for interactive agent UIs.

In VS Code, desktop apps, or web chat surfaces, a terminal process finishing does
not automatically wake the model session. The result looks like an abandoned shift:

1. agent A runs `wait codex --interval 30`;
2. agent B hands off to Codex;
3. `wait` exits successfully;
4. Codex's UI is not re-entered automatically;
5. the relay is `AWAITING_CODEX`, but nobody claims.

This is not a mutex failure. It is a missing bridge between **readiness detection**
and **interactive UI resumption**.

### Motivating incident — the PAUSED wait gap (2026-06-30)

A concrete instance recorded from a live relay session. The session was paused (`PAUSED`,
turn 84); the waiting agent **stopped its `wait`** because in `PAUSED` the command loops printing
*"paused: do not claim until resume"*, which looks useless. The operator then resumed the session
and posted a new turn (a fresh user scope). Because the agent had stopped listening, **it did not
catch the new turn** — picking it up required a manual `next`.

Two faults compound:

1. **Discipline.** `PAUSED` is **not** `DONE`. The keep-listening rule is "stay armed until
   `DONE`", not "until `PAUSED`": the session is still open and a new scope can arrive. An agent
   must not stop its listener on `PAUSED`.
2. **Command behaviour.** The core `wait` *induced* the mistake by spamming a no-claim line in
   `PAUSED`. In `PAUSED`, `wait` must stay **alive but quiet** — longer interval, suppressed
   no-claim noise, still never claims — and **auto-wake on resume → the agent's turn**.

**Invariant:** a new scope arriving after a pause must reach a still-listening agent
**automatically**, with no manual `next`.

## 2. Core invariant

The passive core must stay passive.

`m8shift.py` should continue to own:

- `LOCK`;
- claimability;
- turn order;
- `wait` readiness semantics;
- cooperative turn requests;
- `pause` / `resume`.

It should not become a daemon, process supervisor, notification service, or UI
automation layer.

## 3. Decision

Add a runtime-companion listener concept that records and surfaces three separate
states:

| State | Meaning |
|---|---|
| `waiting` | a listener process is alive and polling for this agent |
| `ready` | the listener detected `AWAITING_<agent>` and exited or notified |
| `resumed` | the agent actually claimed / peeked / yielded / declined after readiness |

This should be implemented outside the core, likely in `m8shift-runtime.py`.

## 4. Proposed command surface

```bash
python3 m8shift-runtime.py listen codex \
  --interval 30 \
  --notify stdout,file,bell \
  --ready-timeout 300
```

Minimum behaviour:

1. poll the core using `status --json` / `wait --once`;
2. write presence under `.m8shift/runtime/presence.json`;
3. append listener events under `.m8shift/runtime/listeners.jsonl`;
4. when readiness is detected, emit a `ready` event and notify the operator;
5. if no follow-up action occurs after `--ready-timeout`, surface a diagnostic.

The listener must not claim automatically unless a future explicit headless mode
authorizes that. Interactive mode only reports readiness.

## 5. Listener event schema

```json
{
  "schema": "m8shift.runtime.listener.v1",
  "ts": "2026-06-30T17:25:49Z",
  "agent": "codex",
  "session_id": "codex-ui-123",
  "state": "ready",
  "relay": {
    "holder": "codex",
    "state": "AWAITING_CODEX",
    "turn": "78"
  },
  "action_hint": "Resume Codex UI and run: python3 m8shift.py next codex"
}
```

State values:

- `waiting`;
- `ready`;
- `resumed`;
- `stale`;
- `stopped`;
- `error`.

## 6. Status/runtime composition

`status --for <agent>` remains core-owned, but `status-runtime` should compose
listener state:

```text
codex is awaited.
listener: ready 4m ago, no resumed action observed.
next: resume the Codex UI and run `python3 m8shift.py next codex`.
```

If the listener is alive:

```text
codex is not awaited.
listener: waiting, pid 12345, last_seen 20s ago.
```

If no listener is registered:

```text
codex is awaited, but no live codex listener is registered.
```

## 7. Doctor checks

Runtime doctor should warn when:

- `AWAITING_<agent>` is older than a threshold and no live listener exists;
- a listener emitted `ready` but no `claim`, `yield-turn`, `decline-turn`, or
  `pause` followed;
- a cooperative turn request is open but not answered for a threshold;
- an agent claims to be "waiting" but there is no fresh presence row;
- repeated ready events happen without progress.

These checks are diagnostics only. They never force a holder and never mutate the
core relay.

## 8. Notifications

Phase 1 should support local, no-network notification modes:

- stdout line;
- append-only file event;
- terminal bell;
- optional OS notification when available and explicitly enabled.

Network notifications, webhooks, hosted dashboards, or provider APIs are deferred
and require explicit operator configuration.

## 9. Process rule for agents

Agents must stop saying "I am waiting" when only a terminal process is waiting.
The accurate statement is:

> A listener is armed. If it detects my turn, the interactive UI may still need to
> be resumed manually.

Once readiness is detected, the agent or operator must perform one of:

- `next <agent>`;
- `yield-turn` / `decline-turn` for an open cooperative request;
- `pause` when there is no active work;
- explicit handoff after reviewing the turn.

## 10. Acceptance criteria

This RFC is implemented when:

- `m8shift-runtime.py listen <agent>` records waiting / ready / resumed events;
- runtime status can distinguish awaited-with-listener, awaited-without-listener,
  and ready-but-not-resumed;
- runtime doctor reports stale ready events and missing listeners;
- no `m8shift.py` semantics change is required;
- interactive mode never auto-claims;
- tests cover listener lifecycle, missing listener diagnostics, ready timeout, and
  cooperative request visibility;
- documentation clearly states that `wait` does not wake an interactive UI.

## 11. Non-goals

- No core daemon.
- No background service installed by default.
- No automatic UI automation.
- No automatic claim in interactive mode.
- No network notification in Phase 1.
- No change to `LOCK` legality.
