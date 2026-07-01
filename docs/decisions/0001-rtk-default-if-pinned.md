# RTK default-if-pinned for context packs

- Status: accepted
- Traceability target: forge
- Source journal: M8SHIFT session `20260626T075208Z-3ee3f1b6`
- Source turns: #132

## Decision

M8Shift context packs use the RTK `shell_output_filter` adapter by default only
when RTK is present and identity-pinned. Otherwise they degrade to the native
stdlib pack path, and operators can opt out explicitly.

## Context

RTK can reduce token cost for noisy locate/scan shell output, but it is an
optional host dependency. The core relay must remain stdlib-only, repository-local,
and free of provider/tool dependencies. RTK must not become a network surface or a
second source of truth.

## Options

- Option A: never use RTK automatically; require every pack call to opt in.
- Option B: use RTK by default whenever the `rtk` executable is on `PATH`.
- Option C: use RTK by default only when present and identity-pinned; otherwise
  degrade to native.

## Positions

- claude: FOR `Option C` — default token savings are useful only if the
  executable identity is pinned, telemetry is off, and failure degrades safely.
- codex: FOR `Option C`, AGAINST `Option B` — mere PATH presence is insufficient;
  the existing resolved-path + SHA-256 pin must remain the boundary.
- maintainer: arbitration in favor of `Option C`, with explicit opt-out and
  telemetry disabled during setup.

## Divergence

The substantive disagreement is whether convenience should trigger on PATH
presence alone. It should not: PATH presence without an identity pin can be a
wrapper, symlink, hijack, or incompatible executable.

## Resolution

Accepted by maintainer direction and agent agreement. `m8shift-context.py pack`
selects RTK only when adapter validation passes with the trusted executable
identity. Missing or invalid RTK falls back to native without error. `pack
--adapter native` / `--no-rtk` opts out. Setup attempts `rtk telemetry disable`,
and doctor reports RTK presence, pin status, and telemetry state.

## Trace

- Session: `20260626T075208Z-3ee3f1b6`
- Turns: #132
- Commit / issue / PR / forge thread: #76
