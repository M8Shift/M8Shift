# RFC — Companion workboard

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Evaluate whether a richer `m8shift-board.py` companion is worth adding beside the existing dumb core
`task` board.

The core task board is intentionally append-only and advisory. A companion board could model owner
tokens, heartbeats, proof/artifacts, blocked reasons, readiness, and review state for teams that need
more structure.

## Open design question

Can a richer board add value without creating a second dispatcher or dependency solver that competes
with explicit `append --to` handoffs?

Subquestions:

- Which board fields are advisory only, and how is that enforced?
- Should board state live in JSONL, Markdown, or a dedicated companion manifest?
- Should it integrate with `m8shift-worktree.py`, or stay separate?
- What is the minimal useful v1 that does not duplicate issue trackers?

## Non-goal

No automatic task promotion, dependency solver, or autonomous dispatch in the core.
