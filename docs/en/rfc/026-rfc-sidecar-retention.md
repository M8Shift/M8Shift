# RFC — Runtime sidecar retention and archive policy

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define retention for `.m8shift/runtime/` sidecars: presence snapshots, progress JSONL, inbox JSONL,
run ledgers, idempotency ledgers, approvals, reports, and related companion files.

Sidecars provide observability but can grow forever in long-running projects. Retention needs to keep
recent troubleshooting data without making runtime files a hidden database.

## Open design question

Should retention be fixed-count, age-based, explicit archive-only, or a combination?

Subquestions:

- Which files are safe to prune automatically, and which require explicit operator action?
- Should pruning preserve a compact summary before deleting raw rows?
- How should retention interact with session reports and project memory?
- Should retention be disabled by default until the operator opts in?

## Non-goal

Never prune `M8SHIFT.md` through runtime retention. Core archive remains the only mechanism for the
relay journal.
