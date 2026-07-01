# RFC — Capability-tiered sub-agent delegation

**Status:** design finalized — the four open questions are resolved by the routing RFC [039-rfc-model-task-routing.md](039-rfc-model-task-routing.md); implementation tracked in #59 · **Builds on:** [002-rfc-n-agents.md](002-rfc-n-agents.md) (degree-1 core), [008-rfc-worktree-companion.md](008-rfc-worktree-companion.md) (degree-2 worktrees), [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md), [028-rfc-headless-command-templates.md](028-rfc-headless-command-templates.md), [039-rfc-model-task-routing.md](039-rfc-model-task-routing.md) (the routing layer that operationalises this) · **Source:** maintainer request — let a pen-holding agent delegate simpler sub-tasks to cheaper/weaker models, in parallel where safe, while keeping the degree-1 core.

## Question

M8Shift today coordinates **peer** agents (Claude ⇄ Codex) through one shared pen
(degree-1, strict alternation). Can a pen-holding agent additionally **delegate sub-tasks to
capability-tiered sub-agents** — e.g. a strong model routing simple, time-tolerant work
(proofreading, formatting, boilerplate) to a cheaper / slower model — **without breaking the
one-writer-at-a-time core**?

## The two axes (do not conflate them)

| Axis | What it is | Pen |
|------|-----------|-----|
| **Peer coordination** (existing, horizontal) | different agents of equal standing, strict alternation | the shared core pen, degree-1 |
| **Sub-agent delegation** (new, vertical) | one pen-holder orchestrates *its own* cheaper-tier sub-agents on bounded sub-tasks, verifies, integrates, then writes | sub-agents hold **no** core pen; only the orchestrator commits |

The core mutex is **unchanged**: sub-agents are the orchestrator's *tools*, not core peers.

## Why

- **Cost / capability routing:** use an expensive model only where its strength is needed;
  route elementary, time-tolerant work to a cheaper model — it takes longer but is well within
  reach.
- **Throughput:** independent sub-tasks run in parallel.
- It formalizes a pattern already in everyday use (a coding agent spawning sub-agents for
  bounded tasks).

## Design — delegation within a turn

1. The pen-holder decomposes its turn into sub-tasks and assigns each a **capability tier**
   (e.g. `tier: light` → cheaper model; `tier: heavy` → strong model).
2. It invokes each sub-agent as a **CLI call** (argv-only, per
   [028-rfc-headless-command-templates.md](028-rfc-headless-command-templates.md)), passing a
   bounded prompt + the sub-task context. No sub-agent touches `M8SHIFT.md` or the core `LOCK`.
3. **Parallel sub-tasks use the worktree companion**
   ([008-rfc-worktree-companion.md](008-rfc-worktree-companion.md), degree-2): each sub-agent
   works in an isolated worktree so concurrent sub-tasks cannot conflict; results are
   serialized-integrated through the canonical integration pen — never a second routing
   authority.
4. The orchestrator **verifies every sub-agent's output against ground truth** (tests, build,
   byte diffs — see the agents-guide *Verification honesty*) **before** integrating. A weaker
   model is *more* error-prone, so delegation pairs with mandatory verification, **never blind
   trust**.
5. The orchestrator writes the integrated, verified result through the core pen as **its own**
   turn.

## Provenance

Each delegated sub-task records the **sub-agent's model + version** (see the agent
model-identification work) in the run ledger, so the trail shows which tier did which piece —
`light: claude-haiku-4-5`, `heavy: claude-opus-4-8`.

## Charter constraints

1. **Core unchanged.** Only the pen-holder commits; the degree-1 mutex is preserved. Sub-agents
   are tools, not peers.
2. **Parallelism via worktrees only.** Concurrent sub-agent writes go through RFC 008 isolated
   worktrees + serialized integration; no second core routing authority is ever created.
3. **Verify, don't trust.** Cheaper-tier output is verified against ground truth before
   integration.
4. **Advisory / companion.** Delegation orchestration is a companion concern; the single-file
   core needs none of it.
5. **argv-only invocation** (RFC 028): no shell, no injection, no bundled model SDK in the core.

## Non-goals

- No degree > 1 writes to the shared tree from sub-agents — [015-rfc-shared-tree-degree-gt1.md](015-rfc-shared-tree-degree-gt1.md) rejected that for the core; worktrees are the only parallel-write path.
- No automatic capability routing decided by M8Shift — the orchestrator (or operator) chooses
  the tier; M8Shift provides the structure, the worktree isolation, and the provenance.
- No bundled provider client / API-key management in the core (network stays out).

## Acceptance criteria

- A pen-holder can run a `light`-tier sub-agent on a bounded sub-task, verify its output, and
  integrate it, with only the pen-holder's commit reaching `main`.
- Two parallel sub-agents run in separate worktrees and integrate serially with no conflict and
  no second LOCK authority.
- An unverified sub-agent output is never integrated; the run ledger shows the verification
  step.
- The run ledger records the model tier of each sub-task.
- Removing all delegation state loses only orchestration telemetry, never the relay log or
  mutex.

## Resolved questions (via RFC 039)

The routing RFC [039-rfc-model-task-routing.md](039-rfc-model-task-routing.md) operationalises this
delegation charter and resolves all four:

1. **Tier expression.** Per task-type in the `skills.json` manifest — `min_model` / `optimum_model` /
   `downgradable` (RFC 039 §7) — not the orchestrator's ad-hoc judgment.
2. **Command surface.** A runtime-companion `route recommend | delegate` verb (RFC 039 §9):
   `recommend` is read-only advisory; `delegate` spawns a routed sub-agent in a worktree behind an
   **explicit confirmation gate** (`--confirm-route` / `--yes` + an RFC 031 decision), reusing the RFC
   028/020 hardened launch machinery. It lives in the companion, never the core, with no hidden
   auto-scoring.
3. **Cost bounding.** Advisory warn by default, opt-in fail-closed per-turn/session budget, reusing the
   RFC 040 usage snapshots rather than a second cost meter (RFC 039 §14).
4. **Same-family vs cross-provider.** Provenance records the model + version + tier regardless; a
   *different-family* verifier is a policy knob recommended for high-stakes `downgradable:false` tasks
   (adversarial-verify / security / legal), otherwise human verification plus a recorded waiver
   (RFC 039 §14).

Implementation of the delegation runtime — the `route` verb, worktree-parallel sub-agents, and
verify-before-integrate — is tracked in **#59**, building on this charter and RFC 039's routing layer.
