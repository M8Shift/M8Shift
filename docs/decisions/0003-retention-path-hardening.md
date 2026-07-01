# Runtime retention path hardening

- Status: accepted
- Traceability target: forge
- Source journal: M8SHIFT session `20260626T075208Z-3ee3f1b6`
- Source turns: #136

## Decision

Runtime retention rejects policy ledger patterns containing parent segments after
normalizing backslashes to slashes, and runtime JSONL append writes refuse
symlink redirection for ledger/archive targets.

## Context

The runtime retention policy is already architecturally confined to a hardcoded
allowlist of runtime ledgers, so the identified gaps are not directly exploitable
through arbitrary paths. They still touch a delete/archive surface, so
defense-in-depth should make the path checks and append writes robust against
future refactors and local symlink planting inside `.m8shift/runtime/`.

## Options

- Option A: keep the existing policy checks because the allowlist already
  confines retention.
- Option B: normalize backslashes for parent-segment checks only.
- Option C: normalize backslashes and refuse symlinked JSONL append paths for
  runtime ledger/archive writes.

## Positions

- claude: FOR `Option C` — the current risk is low, but retention writes deserve
  layered protection because they prune and archive local ledgers.
- codex: FOR `Option C` — minimal stdlib-only hardening preserves normal
  behavior while making future changes safer.
- maintainer: accepted `Option C`.

## Divergence

No substantive disagreement. The trade-off was whether defense-in-depth is worth
the extra helper code when the current allowlist already prevents arbitrary path
selection.

## Resolution

Accepted. `retention_rules_for_existing_ledgers()` now checks parent segments
after `\` to `/` normalization. Runtime JSONL append writes reject symlinked
components under `.m8shift/runtime/` and use `O_NOFOLLOW` when available for the
final append target. Normal real-file retention writes remain unchanged.

## Trace

- Session: `20260626T075208Z-3ee3f1b6`
- Turns: #136
- Commit / issue / PR / forge thread: #73
