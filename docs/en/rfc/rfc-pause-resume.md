# RFC — Pause / resume for open sessions with no active task

- **Status:** implemented v1 in v3.17.0
- **Scope:** M8Shift core state machine and operator-loop guardrails
- **Core invariant:** `PAUSED` is not a work state. It has no pen holder and never makes
  `claim` legal until an explicit resume assigns new user scope.

## Problem

An M8Shift session can be intentionally left open while no agent has active work. Before
this RFC, agents had only three honest exits:

- keep working;
- hand off to another agent;
- close the session with `done`.

When the user explicitly says "do not close the session" and both agents have no work,
the relay can fall into a livelock:

- one agent parks the pen in `WORKING_*` and stops listening;
- or agents bounce empty acknowledgements back and forth.

Both are wrong. `WORKING_*` means "I am working or about to hand off", not "waiting for
future user scope".

## Decision

Add a stable open/no-work state:

```text
state:  PAUSED
holder: none
```

`PAUSED` means:

- the session is open;
- no agent owns the pen;
- no agent may claim automatically;
- the relay waits for explicit user scope.

## Shipped commands

```bash
python3 m8shift.py pause <holder> --reason "no further assigned work; waiting for user scope"
python3 m8shift.py resume <agent> --reason "user assigned new scope"
python3 m8shift.py next <agent> --resume --reason "user assigned new scope"
```

Semantics:

- `pause` is allowed only for the current holder and records a `pause` session event.
- `resume` is allowed only from `PAUSED`; it sets `AWAITING_<agent>` and records a
  `resume` session event.
- `next --resume` performs `resume`, then the normal `claim + peek` path.
- `release` refuses `PAUSED`; use `resume` for explicit assignment.
- `wait` and `next` do not treat `PAUSED` as "your turn".

## Diagnostics

`doctor` warns when:

- a `WORKING_*` lock note appears to say "no further work" / "waiting for user";
- recent turns look like acknowledgement ping-pong without files touched.

These checks are advisory. They never close, resume, or steal the pen.

## Non-goals

- no automatic timeout from `PAUSED`;
- no inference that a user wants a particular agent;
- no hidden auto-resume from operator inbox messages;
- no change to `claim → work → append`.

## Acceptance criteria

- `PAUSED` is a valid LOCK state with `holder=none`.
- `claim <agent>` refuses while paused.
- `wait --once <agent>` returns rc 3 while paused.
- `next <agent>` refuses while paused unless `--resume --reason` is provided.
- `resume` assigns exactly one awaited agent.
- `pause` and `resume` are auditable in `M8SHIFT.sessions.jsonl`.
