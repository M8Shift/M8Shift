# Stage 2 — Design rationale & rejected alternatives

Companion to [002-rfc-n-agents.md](rfc/002-rfc-n-agents.md). This records the *design discussion* behind the
Stage-2 RFC: the architectural choices, **why** each was made, and **what was rejected and why**.
The RFC is the spec; this is the reasoning and the discarded paths, so a future contributor does
not re-open settled questions or re-introduce a rejected idea.

## The yardstick

Every decision is measured against M8Shift's identity invariants. A choice is only acceptable if
it keeps **all** of them:

- **Single file**, Python 3.8+, **stdlib only** (no PyYAML, no jsonschema, no deps).
- **Passive**: no daemon, no autonomous watcher, no network; agents drive it via shell.
- **Degree-1**: exactly one writer at a time on the shared tree; the pen is the only authority.
- **MINIMAL**: the engine decides **one** thing — *who writes, when* — and reads back **only** the
  LOCK fields `agents` / `holder` / `state`. Everything else it records but never interprets.
- **Honest**: never claim enforcement, autonomy, or a guarantee it does not actually provide.

When a desirable feature could not keep all of these, it was **moved out of the core** (into the
opt-in companion tier) or **rejected**, rather than allowed to erode the identity.

---

## Decisions

### D1 — "N agents" means an N-agent *relay* (one pen), not degree-N concurrent writers

- **Context.** "Multi-agent" naively suggests several agents writing at once.
- **Decision.** Stage 2 generalizes the active *pair* to N agents sharing **one pen**; the baton is
  routed to any active agent (`append --to X`). Real parallelism comes only from isolated git
  worktrees with serialized integration (D7).
- **Why.** Keeps degree-1 and the single passive file — the whole value of the tool. This is also
  exactly what Codex's RFC-MA-001 proposed ("N agents, one pen"); two independent designs converged.
- **Rejected:** a **degree-N lock / path-scoped leases** on the shared tree. That puts ≥2 agents in
  a working state at once — it is the deferred degree-2 model, not degree-1; `--to`/strict turn-taking
  lose meaning, and it adds a second orthogonal dimension (*where* each may write). Wrong for the core.

### D2 — Two tiers: a passive core and an opt-in companion

- **Context.** Roles, contracts, validation, tasks, and worktrees are all useful, but several of them
  *interpret content* or *run loops* — which the core must never do.
- **Decision.** Split Stage 2 into a **passive core** (`m8shift.py`, the single-pen mutex) and an
  **opt-in companion tier** (`m8shift-worktree.py` + a liveness supervisor) that `import m8shift`,
  reuse its lock/parse helpers, and add only the orchestration/git surface.
- **Why.** It gives a clean home for everything that would breach MINIMAL/passive without contaminating
  the core. Anything that reads recorded payload back to gate work — or runs an autonomous watcher —
  lives in the companion. A foreground read-only `watch` view is acceptable because it only repeats
  `status` and never acts on the result. The core's promise ("who writes, when") stays literally true.
- **Rejected:** folding tasks-gating / worktree git / an autonomous watcher into `m8shift.py` itself. It would make
  the core an orchestrator and break passive + MINIMAL.

### D3 — Structured data lives in turn-header markdown, not YAML

- **Context.** Codex's kit expresses contracts/roster as YAML files + a JSON schema.
- **Decision.** All Stage-2 structured data lives in the LOCK block, turn headers, and task blocks as
  flat `key: value` lines (lists are CSV). **Keys are snake_case** (`target_role`, not `target-role`).
- **Why.** Python stdlib has **no YAML parser**; using YAML would force PyYAML and break single-file +
  stdlib, and create a second source of truth the engine must load and validate. Markdown key:value is
  the format M8Shift already uses; the contract becomes a **consultative passthrough** the receiving
  agent reads with its own auth. Codex's YAML + schema survive as human-facing examples (validated by
  the kit's optional `validate_specs.py`), not engine input.
- **Why snake_case specifically.** `get_lock`'s key regex is `[a-z_]+` (m8shift.py:1165) — a hyphenated
  key like `target-role` would be **silently dropped**. Snake_case avoids a silent-correctness hole.
- **Rejected:** YAML config; a hand-rolled restricted-YAML parser (still a parser to maintain, still a
  second source of truth); JSON config (no stdlib pretty round-trip into the markdown format, and
  `tomllib` is 3.11+, too new for the 3.8 floor).
- **Cost accepted:** nested structures/lists flatten to CSV text. Fine — M8Shift has always been flat,
  grep-able `key: value`.

### D4 — Roles: three independent levels, stateless, never enforced by the core

- **Context.** Agents need roles (writer, reviewer, …), and an agent may play different roles over time.
- **Decision.** Roles exist at three levels: the **menu** (what an agent *may* be, declared in the LOCK
  `roles:` at `init`, mutable via `agents set_role`); the **task role** (set at `tasks add`); the
  **turn role** (declared per `append`). There is **no persistent "current role"** and no role state
  machine. An agent "changes role" simply by declaring a different one next turn/task.
- **Why.** Statelessness preserves MINIMAL — no role state to track, synchronize, or validate. The role
  is an attribute of the *turn/task*, not of the agent. The receiver learns its expected role from the
  handoff's `target_role` (via `peek`) or the task's `role:`.
- **The one rule** is a **convention**, not enforcement: a validator should not validate its own
  production (independence) — agents pick `--to` accordingly; the core does not check it.
- **Rejected:** tracking `active_role` as a persistent LOCK field (Codex's model). It re-introduces
  state to maintain and a transition to manage, for no engine benefit. Roles stay per-turn/per-task.

### D5 — Contracts are advisory; the core never reads payload back to gate a write

- **Context.** A rich handoff contract (role, permissions, expected outputs, validator) is valuable.
- **Decision.** The core records all contract fields (D3) and **never reads them back** to permit or
  deny a write. It validates only `to ∈ active`, `to ≠ self`, and that the writer holds the pen
  (`state == WORKING_<self>`). `enforce:` is dropped — with only one honest value ("advisory") it
  carries no information and only signals future enforcement intent.
- **Why.** Reading `role`/`validator`/`status` back to gate a write is the engine *interpreting the
  contract* — that is an orchestrator with a workflow policy, not a degree-1 mutex. This is the exact
  identity line. Permissions are honestly **advisory** because the core has no auth into the agents and
  cannot enforce them anyway.
- **Rejected:** `enforce: enforced`, capability checks, mandatory output checks — all in the core.

### D6 — Tasks board: a pure journal in the core; the gating lives in the companion

- **Context.** A task graph (ids, deps, states, READY) is the natural way to partition parallel work.
- **Decision.** The core's `tasks` is a **pure journal**: `add`/`set`/`show`/`list` write/print verbatim;
  `set` stamps a **caller-supplied** state/owner with **no** transition or ownership validation; `READY`
  (deps satisfied) is computed **only** for human-facing `list`/`show` output, and **no core command
  gates on it**. The ownership/transition/READY-gating semantics live in the **companion**.
- **Why.** Gating `claim` on READY/owner or `integrate` on deps means the engine reads its own recorded
  task state back to allow/deny work — the precise MINIMAL breach D5 forbids. "Deterministic" /
  "read-only computation" does not make it passthrough. So the journal stays in the core; the
  orchestration moves to the honest companion tier.
- **This was the review panel's identified top risk**: once the engine computes over payload to gate
  work, every later "just one more check" feels natural and tips M8Shift into the orchestrator it
  exists *not* to be.
- **Rejected:** a core task state machine with ownership/transition guards and a READY/deps gate.

### D7 — Worktree concurrency: companion; canonical-root paths; integration pen = a shared-LOCK transition

- **Context.** Real parallel work (writer + image-gen at once) cannot share one tree.
- **Decision.** Each concurrent task runs in its **own git worktree** (branch + workspace); integration
  is serialized by **one `integration` pen**, modeled as a normal LOCK transition in the **shared**
  `M8SHIFT.md`. All coordination paths resolve to a **canonical repo root** (`git rev-parse
  --git-common-dir` parent, or `$M8SHIFT_ROOT`), never the worktree's copy. A **total lock order**
  (global lock → flip → release → then git) prevents inversion; per-worktree single-writer is the task
  block's `state=WORKING` + `owner` (advisory), **not** a new long-lived lock primitive. A merge conflict
  ⇒ `git merge --abort` + task `BLOCKED`, no partial state.
- **Why.** This gives real concurrency without a degree-N lock on the shared tree (D1). The canonical-root
  pinning fixes a **blocker** the panel found: `HERE = dirname(__file__)` means a worktree's own
  `m8shift.py` computes a *different* `.m8shift.lock`, so two integrators could merge into `main`
  simultaneously. Anchoring the pen to the shared file restores single-integration.
- **Rejected:** the integration pen as a per-worktree artifact (the blocker above); a second long-lived
  workspace lock primitive (use the task block's advisory state instead); assuming `main` as the merge
  target; auto-merge / auto worktree deletion (Codex's non-goals, kept).

### D8 — Liveness supervisor: a companion headless loop, never a core daemon

- **Context.** If a holder stalls (takes the pen, never appends) or dies, who recovers the pen?
- **Decision.** The **core** makes it *recoverable* (TTL `expires` + `claim --force`; `.m8shift.lock`
  stale-takeover after `LOCK_STALE_S`) but never *acts*. Triggering recovery is a human **or** an
  optional **companion** headless loop: poll `status --json`, detect `now > expires` with no progress,
  and `claim --force` + reassign — recording the reason in a turn.
- **Why.** A background watcher in the core would break **passive**. The supervisor adds **no** core
  surface — it is a pure consumer of the read commands + `claim --force` + `tasks set`, in the same
  family as `examples/headless_runner.py`. Keeping it in the companion is what preserves the core's
  "no background loop" guarantee.
- **Rejected:** a TTL-watcher / auto-reclaim loop inside `m8shift.py`.

### D9 — Capability mismatch is handled by graceful degradation, not enforcement

- **Context.** What if a role is assigned to an agent that cannot actually do it?
- **Decision.** Nothing prevents it up front. The agent **bounces it back** through the relay (closes
  its turn with `relation: revise` + `blocked_on`, declaring it cannot), and the coordinator reassigns
  (`tasks set owner=…`). A bad *result* is caught downstream by the review loop (`changes_requested` →
  `revise`).
- **Why.** M8Shift **does not run the models** and has **no knowledge of real capabilities**, so it
  cannot honestly verify them. Even `--strict_roles` would only check the *declared menu* (itself a
  human claim), giving **false confidence**. Routing + recording + a visible bounce is more honest and
  more robust than a refusal that pretends to guarantee an ability it cannot check.
- **Rejected:** `--strict_roles` / capability enforcement in the core (also D5/rejected list).

### D10 — Honesty boundary: a cooperative, advisory mutex — recoverable, not capable/honest/Byzantine-tolerant

- **Context.** What if the agent neither does the work **nor** signals?
- **Decision.** State the boundary plainly. M8Shift guarantees *who writes, when* and that a
  **stalled/dead holder is recoverable** (TTL + `claim --force` + stale-takeover). It does **not**
  guarantee an agent is capable, honest, or productive, and it is **not** Byzantine-fault-tolerant. The
  last line of defense is always a **human or a supervising loop** (D8).
- **Why.** This matches the rest of the project's honesty (e.g. "`wait` does not wake an agent's UI; a
  human/headless runner does"). Overpromising enforcement or autonomy would be the dishonest path the
  brief forbids.
- **Rejected:** framing M8Shift as a system that prevents bad/idle agents. It makes the situation
  **visible** (`status`/`log`) and **recoverable**, not prevented.

---

## Rejected alternatives (consolidated)

| Rejected | Why it breaks an invariant |
|---|---|
| Degree-N lock / path-scoped leases on the shared tree | Not degree-1; two writers at once; wrong tier (this is stage-2-degree-2, not the pen) |
| YAML config (engine input) | No stdlib parser → breaks single-file/stdlib; second source of truth |
| jsonschema / any third-party dependency | Breaks single-file/stdlib |
| `--strict_roles` / `--require_validation` **in the core** | Reads advisory data back to refuse a write → orchestrator, not mutex (D5) |
| Persistent `active_role` LOCK state | Adds state to track/sync for no engine benefit; roles stay per-turn (D4) |
| `enforce:` field | Only one honest value ("advisory"); carries no info; signals future enforcement |
| Core task state machine / READY-gating | Engine interprets payload to gate work (D6) — the top risk |
| Integration pen as a per-worktree artifact | Different `HERE` per worktree → two concurrent merges (the blocker, D7) |
| A second long-lived workspace lock | Use the task block's advisory `state`+`owner`; avoids lock inversion (D7) |
| Auto-merge / auto agent-selection / auto worktree deletion | Breaks passive / "M8Shift never decides for you" (Codex non-goals, kept) |
| Background daemon/autonomous watcher in the core | Breaks passive; supervision is a companion loop (D8). A foreground read-only `watch` view is not a supervisor. |
| Codex's 12 roles / 11 relations / 11 caps as **engine-enforced schema** | Bloats the engine; kept as documentation convention with `x-` escape |
| "N-activation needs no engine change" (an early RFC claim) | False — `active_pair` truncates to 2; see RFC §4a |
| "The core runs no git" (an early RFC claim) | False — `init`/`migrate-brand` already shell `git ls-files`/`git mv` |

---

## How these were validated — adversarial design panels

Two multi-agent review panels (independent reviewers + skeptical synthesis) were run, each reading the
actual `m8shift.py`:

- **Phase-2 design panel** (the rename + back-compat architecture) — chose the load-time dual-read
  resolver, the detect-and-write-brand discipline, and the `migrate-brand` design.
- **Stage-2 RFC review panel** — found, and this design now reflects: the **N-activation blocker**
  (degree-2 hardcoded), the **integration-pen lock-substrate blocker**, the **tasks-board identity
  breach** (top risk → D6), the **"core runs no git" honesty defect**, the dropped **append holder
  guard**, the **hyphen-key silent-drop**, missing **`RESERVED += TASK`**, the `roles:` parser trap, and
  the `agents`-mutation guard gaps. Verdict: **revise-then-ship** — increments 1-3 shippable; gate 4 on
  the journal model; gate 5 on the canonical-root/lock fixes; reject increment 6 from the core.

The lesson encoded here: **the core stays a single passive file that answers one question — who writes,
when — and every payload-interpreting or loop-running behavior is pushed into an honest, opt-in
companion tier outside the pen.**
