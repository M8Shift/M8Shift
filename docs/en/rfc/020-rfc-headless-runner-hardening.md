# RFC — Headless runner hardening

- **Status:** implemented v1 in v3.16.0
- **Scope:** `examples/headless_runner.py`
- **Core invariant:** the runner is a host-side companion. It never edits
  `M8SHIFT.md` directly and never force-steals another agent's pen.

## Problem

The reference headless runner already handles the main pitfalls of unattended
operation: read LOCK state directly, avoid relaunching at `DONE`, refresh its own TTL,
verify progress after the child exits, and write `.m8shift/runtime/runs.jsonl`.

For real use it still needed stronger operational guardrails:

- reject invalid agent names and bad timing parameters early;
- show the effective argv without launching the provider;
- bound one stuck provider process with a timeout;
- terminate then kill a timed-out child deterministically;
- audit timeout events in the same runtime run ledger.

## Decision

Keep the runner as a stdlib-only reference companion and add hardening without turning
it into a provider framework.

## Shipped surface

```bash
python3 examples/headless_runner.py <agent> \
  --cmd <argv...> \
  [--dry-run] \
  [--turn-timeout SECONDS] \
  [--kill-grace SECONDS]
```

Existing lifecycle behavior remains:

- one process per headless agent;
- `--start-on-idle` must be designated on at most one runner;
- manual heartbeat refreshes only the holder's own `WORKING_<agent>` lock;
- post-run validation still decides whether the run progressed.

## Semantics

- `--dry-run` validates configuration and prints the effective argv as JSON, then exits.
- `--turn-timeout 0` disables timeout; any positive value bounds one child turn.
- on timeout, the runner calls `terminate()`, waits `--kill-grace`, then calls `kill()`;
- timeout appends `run.timeout` and `run.ended status=timeout`;
- retry caps still apply and leave recovery to the operator.

## Non-goals

- no provider SDK;
- no shell interpolation;
- no automatic stale-lock force recovery;
- no hidden approval of destructive actions;
- no replacement for `m8shift-runtime.py providers`.

## Acceptance criteria

- invalid agent names are rejected before launch;
- invalid timing parameters are rejected before launch;
- dry-run launches no child process and emits JSON;
- timeout stops a hanging child and records `run.timeout`;
- the runner still passes `M8SHIFT_RUN_ID`, `M8SHIFT_AGENT`, and `M8SHIFT_TURN`;
- the runner still never edits `M8SHIFT.md` directly.
