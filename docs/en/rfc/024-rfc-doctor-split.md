# RFC — Doctor split between core and runtime companion

**Status:** baseline implemented · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define which diagnostics belong in `m8shift.py doctor` and which belong in `m8shift-runtime.py doctor`.

The core already owns read-only checks for the relay file, lock schema, anchors, stale locks,
contract metadata, and other facts directly derived from M8Shift coordination files. The runtime
companion owns presence, progress, inbox, provider, workflow, role, and run-state diagnostics.

## Baseline implementation

The baseline boundary is:

- `m8shift.py doctor` remains the CI-safe core diagnostic surface. It validates the
  relay file, `LOCK` schema, anchors/stanzas, protocol/reference drift, stale
  `WORKING_*` locks, session/request ledger shape and request/answer sequence, contract metadata
  when explicitly requested, and security-oriented local coordination risks.
- When `.m8shift/runtime/` exists, core doctor performs only removable sidecar hygiene:
  it warns if the runtime directory is not gitignored and if JSON/JSONL files are
  syntactically invalid. These warnings do not make runtime sidecars routing authority.
- `m8shift-runtime.py doctor` is the runtime companion diagnostic surface. It verifies
  `core.status`, runtime gitignore state, runtime JSONL event schemas, stale presence,
  no-progress findings, inbox ledgers, and provider registry checks.
- Shared finding concepts may exist, but ids stay scoped by surface: core uses
  `runtime.*_invalid` for minimal hygiene; the companion uses `runtime.jsonl`,
  `runtime.presence_stale`, `runtime.no_progress`, and provider-specific ids.
- Runtime doctor hints stay neutral. They may tell an operator to inspect status or
  progress, but they must not recommend automatic `claim --force` against a fresh holder.

## Remaining design questions

- Should core runtime-hygiene warnings be suppressible when a project intentionally
  ignores the companion?
- Should runtime doctor optionally embed full core `doctor --json`, or is the current
  `core.status` check enough for companion workflows?

## Non-goal

No automatic repair or force recovery. This RFC is about diagnostic ownership only.
