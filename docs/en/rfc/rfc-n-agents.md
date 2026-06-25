# RFC — M8Shift Stage 2: N-agent relay (single pen)

- **Status:** Historical / implemented, now superseded by the current
  [specification](../specification.md) and [architecture](../architecture.md)
- **Supersedes scope of:** [RFC — configurable agent pair](rfc-roster.md) (Stage 1, shipped)
- **Prior art:** the `m8shift-vscode-multiagent-kit` (RFC-MA-001/002/003) — this RFC
  *reconciles* that design with M8Shift's single-file / passive / stdlib / degree-1 identity.
- **Rationale & rejected alternatives:** [stage2-rationale.md](../stage2-rationale.md) — why each
  choice was made and what was discarded.

> ℹ️ **Status update.** The **degree-1 N-agent relay** designed here is shipped:
> active roster, advisory turn fields, `recap`/`peek`/`log`/`status --json`,
> `claim --check`, tasks, memory, session history, doctor, and local-time human
> output are now part of the current v3.x surface. The **tier-2 / §8**
> isolated-worktree companion for true degree-2 concurrency is also shipped as
> `m8shift-worktree.py`. Treat the body below as design history; the current
> normative source is the specification.

## 0. Two tiers (the framing that resolves the identity tension)

Stage 2 is split into two clearly separated tiers:

- **The passive core** (`m8shift.py`): the single-pen mutex. It decides **one** thing —
  *who writes, when* — by reading back **only** the LOCK fields `agents`, `holder`, `state`.
  Every other field it writes is **advisory passthrough**: recorded verbatim, never read back
  to permit or deny a write. The core gains N-agent reach and advisory turn fields.
- **The opt-in companion tier**: explicitly orchestration-shaped tools (NOT passive, NOT
  MINIMAL, documented as such) that `import m8shift` and reuse the core's lock/parse helpers
  (one source of truth), adding only consumer surface over the core's passive primitives. It
  hosts (a) **worktree orchestration** (`m8shift-worktree.py`) — runs git, interprets task
  READY/deps + integration gating (§8); and (b) a **liveness supervisor** — a headless loop
  that re-routes a stalled/dead holder without a human (§8c).

This split is load-bearing: anything that reads recorded payload back to gate work — or runs a
loop/watcher — lives in the companion, **not** the core.

## 1. Summary

"N agents" means two degree-1-preserving things:

1. **N-agent relay** (core) — one pen, baton routed to *any* active agent (`append --to X`),
   not just alternated between two.
2. **Isolated-worktree concurrency** (companion, opt-in) — real parallel work happens only in
   **separate git worktrees**; integration back to the shared tree is serialized by one
   `integration` pen, which is a normal LOCK transition in the **shared** `M8SHIFT.md`. There is
   **no** degree-N lock on the shared tree.

## 2. Goals / Non-goals

**Goals**
- Generalize the active pair to **N active agents** (requires real engine edits — see §4a).
- Carry **advisory** handoff context in the turn, write-only, never read back by the core.
- Runtime roster/role mutation (`agents …`) without resetting the relay.
- Read commands (`recap`, `peek`, `log`, `status --json`, `agents`, `tasks`).
- An **opt-in companion** for isolated-worktree concurrency with serialized integration (§8).
- An **opt-in companion** liveness supervisor that re-routes a stalled/dead holder (§8c).

**Non-goals (would break a core quality)**
- A **degree-N lock** / path-scoped leases on the shared tree (parallelism is worktrees only).
- **YAML / jsonschema / any third-party dep** anywhere (stdlib only).
- The **core** reading any advisory field (`enforce`/`status`/`validator`/task state/deps) back
  to permit or deny a write. Such gating, if ever built, lives **only** in the companion tier.
- Auto-merge, auto agent-selection, auto worktree deletion, any background daemon/watcher.

**Honesty note on git:** the core is *not* git-free today — `init` may shell out to
`git ls-files` / `git mv` for anchor case-renames, with an `os.replace` fallback when
untracked. The companion's distinction is **no git in the
coordination / merge path of the mutex**, not "runs nothing."

## 3. The governing decision: turn-header markdown, not YAML

All Stage-2 structured data lives in the LOCK block, turn headers, and task blocks as flat
`key: value` lines (lists are comma-separated). **Key grammar: `[a-z_]+`** in the LOCK block
(snake_case; exactly what `get_lock`'s parser accepts — hyphens and digits are **not** matched
there and would be silently dropped). So all field keys are snake_case (`target_role`, not
`target-role`); relations, ids and role names are **values**, never keys.

> Note (shipped §5): the **turn-journal** parser (`parse_turns`, used by peek/recap/log) widens
> turn-field keys to `[a-z][a-z0-9_]*` so the open `x_*` advisory namespace may carry digits
> (e.g. `x_pr2`). The LOCK-block grammar is unchanged.

Turns and task blocks are **not parsed back today** (only the LOCK block is). `peek`/`recap`/
`tasks` therefore introduce **one new shared `key: value` block parser** (with a test that an
unknown key is preserved verbatim, never silently dropped) — this RFC does not claim the format
is "already parsed", only that it reuses the same grammar.

The engine **writes advisory fields verbatim and never re-reads them** to decide anything.
Codex's YAML specs + JSON schema remain **human-facing examples** validated by the kit's
optional `validate_specs.py`, not engine input.

## 4. State machine (N agents, one pen)

`LOCK` fields (additions in **bold**):

```
holder:   <active agent | none>
state:    IDLE | WORKING_<X> | AWAITING_<X> | PAUSED | DONE   (X = any active agent, uppercased)
agents:   claude,codex,gemini,...                    (CSV — now N active, was 2)
roles:    claude=coordinator,codex=writer+implementer,...   ← new, optional, advisory
turn:     <n>
since: / expires: / note: / lang:
```

- `claim <me>` succeeds from `IDLE` (any active agent; one O_EXCL winner) or `AWAITING_<me>`.
- `append <me> --to <X>` closes the turn and routes the baton to any other active `X`.
- `release` → `IDLE`. `done` → `DONE`. `--force` recovery unchanged.

### 4a. Validator changes (implemented)

Historical context: before the N-agent work, the engine only used the first two
agents of the roster and would reject a baton that reached a third agent. The
current implementation uses the full active roster. The required changes were:

1. Add `active_agents(lk)` = full active roster (drop the `[:2]` truncation) and feed it to
   `valid_states()` (already set-based — generalizes for free) and to `load_or_die`'s `state`/
   `holder`/`agents` checks.
2. Replace `other(me)` usage: it is a 2-agent function and cannot name a 3rd agent. The baton
   target comes from the **turn's `to`** / explicit `--to`, not `other()`; `wait`/stale logic
   becomes a holder-string test; `stanza_for` stops baking in a single "other".
3. Update `cmd_status` to print the full active set, not a pair.

`append` legality is unchanged and is the single-writer guarantee (see §5).

## 5. Turn schema (advisory fields)

**Normative append legality (unchanged, all N):** `append <me>` REQUIRES `state == WORKING_<me>`
(you hold the pen). `to ∈ active` and `to ≠ self` are **additional** checks. Holding the pen is
the only state from which a write/handoff is legal — this is the exclusive-work-window guarantee.

Existing required fields stay: `from`, `to`, `ask`, `done`, `files`, `handoff`. The engine knows a
**small fixed set** of advisory keys and writes them verbatim; **any other** `key: value` (e.g.
`x_*`) is carried in an open namespace, preserved verbatim, never enumerated or interpreted:

| field | meaning | engine behavior |
|---|---|---|
| `role` / `target_role` | poster's / receiver's active role | passthrough |
| `relation` | delegate / implement / review / revise / integrate / continue / `x-*` (value) | passthrough |
| `allow` / `deny` | capability hints (CSV) | passthrough |
| `expect` | required outputs (CSV) | passthrough |
| `validator` / `status` | who reviews / validation status | passthrough |
| `branch` / `commit` / `tests` | VCS + test context | passthrough |
| `blocked_on` / `next` | wait reason / suggested next command | passthrough |
| `observers` | informational agents, **no work right** | passthrough |
| `task` | task id (see §7) | passthrough |

`clean_field` injection-safety applies to all of them. (`enforce:` is dropped — with only one
honest value, "advisory", it carries no information and only signals future enforcement intent.)

## 6. Roles — three levels, stateless, never enforced by the core

No role state machine, no persistent "current role". Three independent levels:

| level | what | where | changed how |
|---|---|---|---|
| **Menu** | role-set an agent *may* play | LOCK `roles:` | `init` declares · **`agents set_role`** mutates · `init --force` resets |
| **Task role** | role a task asks of its owner | `M8SHIFT:TASK` block `role:` | set at `tasks add`, reassignable until close |
| **Turn role** | active role for one turn | turn `role:` | declared at each `append` (stateless) |

An agent "changes role" by declaring a different one next turn/task. A receiver learns its
expected role from the handoff's `target_role` (via `peek`) or the task's `role`. There is **one
convention** (not an engine rule): a validator should not validate its **own** production —
agents choose `--to` accordingly; the core does not enforce it.

**`roles:` sub-grammar:** `agent=role(+role)*` comma-separated. It MUST be parsed by a dedicated
parser, **never** routed through `roster_tokens` (which fullmatches `AGENT_RE` per token and would
reject every legal `roles:` value). Schema rules: every left-hand name ∈
`agents:`; role tokens match `[a-z][a-z0-9_]*`; an unparseable `roles:` is a clean refusal, never a
traceback. `load_or_die` must NOT pass `roles:` through agent-name validation.

**Runtime roster/role mutation** — computes the **full new `(agents, roles, state, holder)` tuple**,
validates it in-memory against the `load_or_die` schema, then writes once via `set_lock` under
`file_lock` (atomic):

```bash
m8shift.py agents list
m8shift.py agents set_role gemini image_generator+reviewer
m8shift.py agents add    mistral:tester [--reassign <agent>]
m8shift.py agents remove mistral        [--reassign <agent>]
```

Guards — refuse if the op would: remove the current `holder` or an `AWAITING_<X>` target; drop
below 2 active; remove an agent that **owns a non-terminal task** (CLAIMED/WORKING/NEEDS_REVIEW)
or holds a live worktree (unless `--reassign`); leave a dangling `roles:` entry (remove strips it).
`add` re-injects the agent's anchor via `ensure_canonical_anchor`/`inject_anchor` — which itself
runs `git mv` and can exit on `anchor_ambiguous`/collision (codex/lechat/mistral all map to
AGENTS.md); that must run and **abort the whole op before the LOCK write**.

`--strict_roles` (checking a declared role ∈ menu) is **out of scope for the core** — it requires
reading advisory data back to refuse a write. If wanted, it lives in a separate policy tier.

## 7. Tasks board (core = pure journal; gating lives in the companion)

`M8SHIFT.tasks.md`: one HTML-comment block per task, same grammar as the LOCK, mutated in place
under the **same** canonical-root `.m8shift.lock`.

```markdown
# M8SHIFT · tasks

<!-- M8SHIFT:TASK content BEGIN -->
- owner:    codex
- role:     writer
- state:    READY
- deps:     -
- files:    content/hero.md
- branch:   feat/content
<!-- M8SHIFT:TASK content END -->
```

**The core treats tasks as a strict journal — it never reads task state back to permit/deny work:**

- `tasks add` / `tasks set <id> key=val …` / `tasks show` / `tasks list` write/print **verbatim**.
  `tasks set` stamps a **caller-supplied** state/owner with **no** transition or ownership
  validation by the core (the receiving agent decides, with its own auth, per §0).
- `READY` (deps all `COMPLETED`/`APPROVED`) is computed **only** for human-facing `list`/`show`
  output. **No core command gates on it.** `deps` grammar: `-` | `(all|any):id(,id)*`, ids may
  contain hyphens (they live in the BEGIN/END marker, not as parsed keys).
- The **ownership/transition/READY-gating** semantics (claim refuses if owned; integrate refuses if
  deps unmet) are **coordination authority** and live in the **companion** (§8), never the core.

Injection-safety: add the `M8SHIFT:TASK` marker to the `RESERVED` tuple so `clean_field`
rejects a forged TASK boundary inside a `note`/`files` value (verified gap:
`clean_field` scans only `RESERVED`; `clean_body`'s zero-width neutralization does not cover field
values). `roles:`/`deps:` values must pass `clean_field` (allowing `=`,`+`,`:` while still rejecting
RESERVED markers and newlines), with byte-identical `set_lock`/`get_lock` round-trip tests.

## 8. Concurrency: isolated worktrees (companion, opt-in)

```
codex  → feat/content  → .m8shift/worktrees/content   (parallel, isolated)
gemini → feat/hero-img → .m8shift/worktrees/assets
                              └─► integrate (deps satisfied) → integration pen → merge 1-by-1 → reviewer → main
```

**Canonical-root pinning (REQUIRED, fixes the integration-pen blocker).** Historically,
`HERE = dirname(__file__)` and the module-level coordination paths for the living relay file, tasks
and lockfile derived from that script location, so an integrator launched from a worktree
(which contains its own `m8shift.py`) could compute a **different** lockfile and living file
than one in the main tree → two concurrent merges into `main`. Fix: resolve all coordination
paths to a **discovered canonical repo root** — the parent of
`git rev-parse --git-common-dir`, or `$M8SHIFT_ROOT` — never the worktree copy. The **integration
pen is a normal LOCK transition in the shared `M8SHIFT.md`**, acquired via the existing `claim` path
— not a per-worktree artifact.

**Lock order (REQUIRED, no inversion).** For any task/LOCK mutation: acquire the global
canonical-root `.m8shift.lock` first, do the atomic flip, **release it**, *then* run git/worktree
work. **Never hold two of {global lock, integration pen, workspace} at once.** Per-worktree
single-writer is modeled as the task block's `state=WORKING` + `owner` (set under the global lock at
flip time) — **advisory** (the OS does not stop the agent writing), **not** a second long-lived lock
primitive. If a real second lock is ever needed, it must carry `file_lock`'s token + `LOCK_STALE_S`
takeover contract and a stated TTL.

**Merge contract (REQUIRED).** On a non-clean `git merge`: the companion runs `git merge --abort`,
leaves the worktree untouched, sets the integrate task to `BLOCKED` (`blocked_on=conflict:<id>`),
exits non-zero — no partial state. Default integration target is detected via
`git symbolic-ref --short HEAD` or required via `--into`; never assume `main`.

**Companion commands & dependency direction.** The companion **imports `m8shift`** and calls
`m8shift.file_lock()`/`get_lock`/`set_lock` + task helpers against the canonical-root lockfile (one
source of truth; it never re-implements lock/parse logic). So a core `tasks set` and a companion
`worktree claim` are mutually exclusive on the same lock.

```bash
m8shift-worktree claim     <id> <agent>   # git worktree add + task→WORKING (gates on READY here, not in core)
m8shift-worktree done      <id>           # task→COMPLETED
m8shift-worktree integrate [--into B]     # integration pen (shared LOCK) ; refuse if deps unmet ; merge 1-by-1
m8shift-worktree review    <id> <reviewer> --status approved|changes_requested
m8shift-worktree drop      <id>           # remove worktree (confirmation required, never auto)
```

**Honesty:** worktrees share the same git repo (refs / object store / index); per-worktree
isolation is **advisory** discipline, not OS-enforced. Integration is serialized because **one
agent honors the integration pen**, not because the OS forbids the others.

### 8c. Liveness supervisor (companion, optional — never the core)

The core makes a stalled/dead holder **recoverable** but does not act on it: a holder that takes
the pen and never appends goes stale at `expires` (TTL) and can be reclaimed by `claim --force`;
an abandoned `.m8shift.lock` is taken over after `LOCK_STALE_S`. *Who* triggers that recovery is
**not** the core — by design (no daemon, no watcher in the passive core). It is a human, or this
optional companion: a **headless loop** that polls `status --json`, detects `now > expires` on a
`WORKING_<X>` with no turn progress, and re-routes — `claim --force` then reassign the task/baton
to another active agent (or back to the coordinator), recording the reason in a turn.

It is honest about its limits: it detects **liveness** (no progress past TTL), **not** capability
or output quality (those are the bounce-back + review loop, §9). It adds **no** core surface — it
is a pure consumer of the core's read commands + `claim --force` + `tasks set`, in the same family
as [`examples/headless_runner.py`](../../../examples/headless_runner.py). Keeping it in the companion
is what preserves the core's "no background loop" guarantee.

## 9. Validation = advisory, in the core; enforcement only in a separate tier

`validator` / `status` (pending / approved / changes_requested / rejected / waived) are recorded
in turns and **never read back by the core**. `--require_validation` (refusing a close without an
independent validator) is **out of scope for the passive core** — it reads advisory data back to
refuse a write. If desired it ships in the companion/policy tier, documented as a different product.

## 10. Read commands (do first — increment 1)

Read-only, passive, stdlib, no identity exposure:
- `recap` — current LOCK + last N turn summaries. *("memory headlines" is dropped from increment 1;
  it depends on the unbuilt shared-memory roadmap item — add it only once that exists.)*
- `peek <me>` — reuse the `cmd_archive` TURN `finditer`, parse each block's `to:` line, print the
  body of the last block where `to == me`; rc 3 if not your turn (reuses `wait --once`'s state check).
- `log` — relay timeline; `status --json`; `agents` (list + menus); `tasks list`.

## 11. Backward compatibility

- Pair = N = 2 — no behavior change for existing two-agent projects **after the §4a edits** (which
  must keep `valid_states`/`load_or_die` byte-identical for the 2-agent case).
- Turns without advisory fields are valid free relays (`relation: continue` implied).
- Historical migration paths are out of scope for this RFC; Stage 3+ documents only the M8Shift
  surface. `roles:`, the tasks file and worktrees are optional/additive.
- **Migration:** a project with a stored 3+ roster (extra names declared but inactive in Stage 1)
  must **opt in** to activate them (`agents add` / `init --force`) — increment 2 must NOT silently
  promote stored-inactive names to active. `test_status_shows_active_pair` is rewritten to N-active
  semantics, plus a stored-extra-name migration test.

## 12. Sequencing (increments) — with review gates

1. **Read commands** — ✅ **SHIPPED** (`recap`, `peek`, `log`, `status --json`; shared
   `parse_turns` block parser keeps unknown keys verbatim and preserves reserved relay markers).
2. **N-agent roster + relay** — ✅ **SHIPPED** (§4a de-pairing: `active_agents()`, `load_or_die`/
   `valid_states`/holder on the full roster, `cmd_init` anchors+ROSTER+BRIDGE on N, `cmd_wait`
   self-excluding stale check naming the real holder, `cmd_status`/`recap`/migrate on N; `stanza_for`
   renders byte-identically for a pair and a generic peer for N>2). `agents …` mutation + `roles:`
   parser deferred to a follow-up. 104 tests; pair mode (N=2) byte-unchanged.
3. **Advisory turn fields** (§5) — GO after 2, with snake_case keys + the open `x_*` namespace.
4. **Tasks board** — split: **4a** = the *journal* (create/locate/brand-derived, `add`/`set`/`list`/
   `show` pure passthrough, `RESERVED += TASK`, READY **not** gating); **4b** = READY evaluator
   (display-only; missing-dep/cycle = clean refusal). GO on 4a once §7's journal model is accepted;
   4b only if it never gates a core command.
5. **Worktree companion** (§8) — GO only after canonical-root pinning + integration-pen-as-shared-LOCK
   + lock order + merge contract + companion import/shared-lock + the honesty rewording. Do last.
6. **`--strict_roles` / `--require_validation`** — **rejected from the core, permanently** (both read
   advisory data back to refuse a write). Only ever as a separate policy/companion tier.

## 13. Tests (extends the Phase-2 matrix)

`load_or_die` accepts `WORKING_<3rd-agent>` once active; N concurrent claims → one winner;
`append` from a non-holder refused (all N); inactive/self target refused; every advisory field
round-trips and never changes the mutex; hyphenated/unknown key preserved-or-loudly-rejected (never
silently dropped); `roles:`/`deps:` byte-identical round-trip + dedicated-parser validity;
`agents add/remove/set_role` full-tuple validation + holder/awaited/<2/roles-orphan/task-owner/anchor-
collision guards; forged `M8SHIFT:TASK` boundary in a task field rejected; tasks brand-derived +
migrate-brand renames it; two `worktree integrate` from different worktrees → exactly one acquires;
core `tasks set` ⨉ companion `worktree claim` cannot interleave; clean-merge and conflicting-merge
(abort + BLOCKED, no working-tree mutation); pair-mode (N = 2) byte-unchanged; no network call added.

## 14. Open decisions

1. **§8 worktrees:** confirmed **separate companion** (imports core, shares canonical-root lock).
2. **§7 tasks identity:** resolved — core = pure journal; gating lives in the companion.
3. **§9/§6 enforcement:** resolved — `--require_validation` / `--strict_roles` rejected from the core.
4. **Config ceiling:** confirmed turn-header markdown (snake_case keys) over YAML for all data.

*Remaining for the user:* sign-off on the two-tier split (§0) and on starting increment 1.

## Appendix A — sequential N-agent relay (one pen)

```
init --agents "claude:coordinator,codex:writer+implementer,gemini:image_generator+reviewer"
T1  claude --to codex   role=coordinator target_role=writer relation=delegate validator=gemini
T2  codex  --to gemini  role=writer relation=generate_asset branch=feat/hero tests=pass
T3  gemini --to claude  role=reviewer relation=review status=approved
T4  claude --to codex   relation=integrate ; done
```

## Appendix B — parallel work (companion)

```
tasks add content   --owner codex  --role writer          --files content/hero.md
tasks add hero-img  --owner gemini --role image_generator --files assets/hero.png
tasks add integrate --owner claude --role integrator --deps all:content,hero-img
worktree claim content  codex ; worktree claim hero-img gemini   # concurrent, isolated
worktree done content ; worktree done hero-img
worktree integrate --into main    # integration pen (shared LOCK) ; merge feat/content then feat/hero-img ; review
```

---

*This RFC keeps the M8Shift **core** a single passive file that answers one question — who writes,
when — and pushes every payload-interpreting behavior (task gating, READY/deps, git, integration)
into an honest, opt-in companion tier outside the pen.*
