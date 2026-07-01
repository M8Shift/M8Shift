# Decision 0005 — RTK visibility remains local and self-declared

- **Status:** accepted
- **Date:** 2026-07-01
- **Issue:** #79
- **M8Shift version:** v3.36.0
- **Agents provenance:** Claude requested and reviews; Codex implements and rechecks.

## Context

RTK telemetry is disabled by design, so `rtk session` is not an authoritative
source for M8Shift. Operators still need to see whether an agent claims to use
RTK and whether the M8Shift context adapter is active for context packs.

## Decision

M8Shift exposes two separate signals:

1. **Agent lane signal:** `M8SHIFT_RTK=on|off`, recorded in runtime presence as
   a self-declaration only. Absent or invalid values fail safe to `off`.
2. **Context-adapter signal:** local RTK manifest identity pinning under
   `.m8shift/context/adapters/rtk-shell-output.json`, surfaced as
   `RTK: ON (pinned, compressing packs)` or `RTK: OFF (native)`.

`m8shift-runtime.py status-runtime`, `m8shift-context.py status`, and
`m8shift-context.py doctor` show the adapter state and the latest context-pack
compression ratio when metrics are available.

Actual RTK command usage by an agent is audited through `rtk discover`, not
through M8Shift telemetry.

## Rejected alternatives

- Re-enable RTK telemetry: rejected; it violates the local/no-telemetry charter.
- Auto-probe agent shells: rejected; it would make visibility invasive and
  brittle.
- Treat self-declaration as evidence: rejected; it is only an advisory lane
  signal.

## Consequences

- Operators get useful local visibility without adding a network primitive.
- The context adapter state is independently visible even when agents do not
  self-declare.
- Read-only status paths treat non-regular trusted executable paths as RTK OFF
  and report corrupt context-sidecar JSON as findings instead of hanging or
  aborting.
- For forensic audit, operators must use RTK's own local `rtk discover`.
