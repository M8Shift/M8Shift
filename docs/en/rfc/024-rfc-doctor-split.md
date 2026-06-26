# RFC — Doctor split between core and runtime companion

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define which diagnostics belong in `m8shift.py doctor` and which belong in `m8shift-runtime.py doctor`.

The core already owns read-only checks for the relay file, lock schema, anchors, stale locks,
contract metadata, and other facts directly derived from M8Shift coordination files. The runtime
companion owns presence, progress, inbox, provider, workflow, role, and run-state diagnostics.

## Open design question

What is the exact boundary that keeps the core useful in CI while preventing it from depending on
runtime sidecars?

Subquestions:

- Should core `doctor` warn when `.m8shift/runtime/` exists but is malformed, or should it ignore it?
- Should runtime `doctor` call core `doctor --json` and compose the result, or should operators run both?
- Which finding ids are shared, and which are runtime-only?
- Should any runtime doctor finding ever recommend a `claim --force` command, or only print neutral
  recovery hints?

## Non-goal

No automatic repair or force recovery. This RFC is about diagnostic ownership only.
