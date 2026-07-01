# RFC — Companion workboard

**Status:** design finalized (this RFC) · **implementation deferred pending operator greenlight** (#48) · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Evaluate whether a richer `m8shift-board.py` companion is worth adding beside the existing dumb core
`task` board.

The core task board is intentionally append-only and advisory. A companion board could model owner
tokens, heartbeats, proof/artifacts, blocked reasons, readiness, and review state for teams that need
more structure.

## Design (finalized)

A richer board adds value **only as a read-only, composed VIEW** — the way `status-runtime` composes
core status over sidecars — and **never as a second state store, dispatcher, or dependency solver**.
The core `task` board and `append --to` handoffs stay the only source of truth and the only routing;
the board just presents what already exists, in one consolidated glance.

`m8shift-board.py show [--json] [--agent X]` renders per-agent columns — **awaiting / working /
blocked / done** — composed from:

- the relay `LOCK` (who holds the pen, current state);
- the core `task` ledger (advisory to-dos);
- the runtime sidecars (runs, progress, operator inbox, presence — RFC 009);
- the worktree companion's integration state (RFC 008), read-only;
- optionally a link-out to the forge issues the operator already tracks (never a mirror).

It writes **no authoritative state**. The only thing it may persist is a small host-local, gitignored
presentational config (`.m8shift/runtime/board.config.json` — column order / filters), which never
feeds routing.

## Resolved subquestions

1. **Which fields are advisory, and how is that enforced?** *All* of them — every field is **derived
   read-only** from existing sources. Enforcement is structural: the board is a companion with **no
   write path** to the `LOCK`, `M8SHIFT.md`, or the task ledger (the same boundary as `doctor` /
   `status-runtime`).
2. **State in JSONL / Markdown / manifest?** **Nothing new or authoritative** — the board *composes*
   from the existing task JSONL + runtime sidecars + relay state and *renders* a view (stdout /
   `--json` / Markdown). Only a tiny presentational config is host-local + gitignored.
3. **Integrate with the worktree, or stay separate?** **Read** the worktree/integration state to
   *show* degree-2 lanes, but stay a **separate, read-only** companion — it never drives the worktree.
4. **Minimal useful v1?** `m8shift-board.py show` — a consolidated **read-only** board composed from
   the sources above. It does **not** duplicate an issue tracker (it is a live relay/runtime view, not
   a project backlog) and does **not** compete with `append --to` (it routes nothing).

## Non-goals

- **No automatic task promotion, dependency solver, or autonomous dispatch** — in the core *or* the
  companion. Routing is `append --to` plus explicit human/operator decisions, only.
- **No second source of truth.** The board derives; it never authors task or relay state.
- **No issue-tracker replacement.** The forge issues remain the durable backlog; the board is a live
  glance, not a project-management tool.
