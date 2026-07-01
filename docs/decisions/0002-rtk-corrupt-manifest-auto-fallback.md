# RTK corrupt-manifest fallback in automatic context packs

- Status: accepted
- Traceability target: forge
- Source journal: M8SHIFT session `20260626T075208Z-3ee3f1b6`
- Source turns: #134

## Decision

Automatic RTK adapter selection must degrade to the native stdlib context-pack
path when the on-disk RTK manifest is corrupt, unreadable, or not a JSON object.
Explicit `--adapter rtk-shell-output` remains fail-closed.

## Context

The v3.34.0 default-if-pinned behavior made the RTK adapter part of the default
`pack` path. A corrupt local manifest could therefore abort a default context
pack before the native fallback was reached, contradicting the fully-degrading
contract for automatic adapter use.

## Options

- Option A: keep using the strict adapter loader in automatic and explicit modes.
- Option B: make both automatic and explicit RTK selection degrade to native on
  corrupt manifests.
- Option C: make automatic selection degrade to native on corrupt manifests, but
  keep explicit RTK selection fail-closed.

## Positions

- claude: FOR `Option C` — automatic defaults must be fully degrading, while an
  explicit operator request should still fail clearly when the requested adapter
  cannot be trusted or parsed.
- codex: FOR `Option C` — the automatic path should use diagnostic loading and
  native fallback; the explicit path should keep the strict loader.
- maintainer: accepted `Option C`.

## Divergence

There was no substantive disagreement on the target behavior. The important
distinction is mode-dependent: automatic convenience is tolerant, explicit
operator selection is strict.

## Resolution

Accepted by agent agreement. `select_context_adapter()` now uses a non-throwing
manifest loader only in automatic mode. Broken JSON, unreadable files, and
non-object manifests produce adapter error findings and select native packing.
Explicit `--adapter rtk-shell-output` still uses the strict loader and aborts.

## Trace

- Session: `20260626T075208Z-3ee3f1b6`
- Turns: #134
- Commit / issue / PR / forge thread: #76
