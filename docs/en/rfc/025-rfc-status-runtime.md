# RFC — Runtime status composition

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Design `status-runtime`: a composed view that combines core relay status with runtime companion
presence, progress, inbox, and run lifecycle data.

The core `status` remains authoritative for `LOCK` state, holder, turn, TTL, and routing hints.
Runtime status may explain whether a UI/process appears alive, which run id is active, and what
progress has been reported.

## Open design question

Should runtime status be a separate `m8shift-runtime.py status-runtime` command, a wrapper around
`m8shift.py status --json`, or both?

Subquestions:

- Which fields are stable enough for JSON consumers?
- Should stale presence alter exit codes, or only render warnings?
- How should status behave when runtime sidecars are missing, corrupt, or intentionally deleted?
- Should `status-runtime --brief` mirror the core brief-output contract?

## Non-goal

Runtime status must not change `claim`, `append`, `next`, or any legal `LOCK` transition.
