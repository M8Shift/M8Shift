# RFC — Runtime status composition

**Status:** baseline implemented · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define `status-runtime`: a composed view that combines core relay status with runtime companion
presence, progress, inbox, and run lifecycle data.

The core `status` remains authoritative for `LOCK` state, holder, turn, TTL, and routing hints.
Runtime status may explain whether a UI/process appears alive, which run id is active, and what
progress has been reported.

## Baseline implementation

The baseline shipped as a separate companion command:

```bash
./m8shift-runtime.py status-runtime [agent] [--brief] [--json]
```

- It wraps `m8shift.py status --json` for authoritative relay state.
- It reads runtime sidecars (`presence.json`, `progress.jsonl`, `runs.jsonl`, and
  per-agent inbox ledgers) as advisory context.
- Without an explicit agent argument, it discovers runtime lanes from presence,
  progress, run events, and inbox filenames, so missing presence does not hide
  recent runtime activity.
- Missing or intentionally deleted sidecars are treated as empty runtime state.
- Malformed sidecars produce `runtime_findings` warnings but do not alter the core `LOCK`.
- Human output stays concise by default; `--brief` is a strict line subset of that human
  output and omits progress/run detail.
- `--json` is the stable machine contract and is unchanged by `--brief`.

## Remaining design questions

- Should stale presence ever alter exit codes, or only render warnings?
- Should future run lifecycle summaries include the active run id directly in the compact
  human view?
- Should a later `--brief` contract be shared across core and companion commands, or remain
  command-local?

## Non-goal

Runtime status must not change `claim`, `append`, `next`, or any legal `LOCK` transition.
