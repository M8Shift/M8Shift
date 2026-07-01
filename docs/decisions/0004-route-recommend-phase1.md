# Route recommend Phase 1

- Status: accepted
- Traceability target: forge
- Source journal: M8SHIFT session `20260626T075208Z-3ee3f1b6`
- Source turns: #138

## Decision

Ship Phase 1 of tiered delegation as `m8shift-runtime.py route recommend`: a
read-only advisory recommendation over operator-owned manifests. Do not launch,
delegate, claim, score hidden providers, or mutate the core.

## Context

RFC 032 allows a pen-holder to use cheaper/capability-tiered sub-agents as tools,
but only if the degree-1 core remains unchanged and the pen-holder verifies before
integrating. RFC 039 resolves the routing layer: capability-first eligibility,
operator-owned model/task manifests, cost only as a tie-break among eligible
models, and explicit confirmation before any future launch.

## Options

- Option A: implement full `route delegate` immediately, including launch.
- Option B: ship only provider-neutral manifests and documentation.
- Option C: ship `route recommend` first as a read-only advisory layer; defer
  launch/delegate to a later confirmed phase.

## Positions

- claude: FOR `Option C` — it validates the routing contract and manifest model
  without introducing a new execution path.
- codex: FOR `Option C` — it preserves the charter boundaries: companion-only,
  advisory, no bundled prices/vendors, no hidden auto-scoring, no core mutation.
- maintainer: accepted `Option C`.

## Divergence

No substantive disagreement. The important boundary is that Phase 1 recommends
only; it never starts a sub-agent or integrates output.

## Resolution

Accepted. `route recommend` reads `.m8shift/routing/models.json` and
`.m8shift/routing/skills.json`, applies capability/context floors before cost,
prints an advisory recommendation, validates manifests in `doctor`, and fails
safe to self/manual when no reliable recommendation exists.

## Trace

- Session: `20260626T075208Z-3ee3f1b6`
- Turns: #138
- Commit / issue / PR / forge thread: #59
