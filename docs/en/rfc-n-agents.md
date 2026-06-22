# RFC — M8Shift Stage 2: N-agent relay (single pen)

- **Status:** Proposed
- **Supersedes scope of:** [RFC — configurable agent pair](rfc-roster.md) (Stage 1, shipped)
- **Prior art:** the `m8shift-vscode-multiagent-kit` (RFC-MA-001/002/003) — this RFC
  *reconciles* that design with M8Shift's single-file / passive / stdlib / degree-1 identity.

## 1. Summary

Stage 2 lets **N agents** cooperate through M8Shift instead of a fixed pair, **without
giving up the single pen**. "N agents" here means two things, both degree-1-preserving:

1. **N-agent relay** — one pen, but the baton is routed to *any* active agent
   (`append --to X`), not just alternated between two.
2. **Isolated-worktree concurrency (optional)** — real parallel work happens only in
   **separate git worktrees**; integration back to the shared tree is serialized by one
   `integration` pen. There is **no** degree-N lock on the shared tree.

Everything structured (roles, relations, permissions, validation, tasks) is **advisory
data written into the turn header**, never YAML the engine must parse, and never read
back into coordination logic. M8Shift keeps doing **one** thing: *who writes, when*.

## 2. Goals / Non-goals

**Goals**
- Generalize the active pair to **N active agents** (states already parameterized by agent).
- Carry **advisory** handoff context (role / relation / validator / branch / tests / next…)
  in the turn, write-only.
- Provide **read commands** (`recap`, `peek`, `log`, `status --json`, `agents`, `tasks`).
- Offer an **opt-in** isolated-worktree concurrency model with serialized integration.

**Non-goals (would break a core quality)**
- A **degree-N lock** / path-scoped leases on the shared tree (parallelism is worktrees only).
- **YAML / jsonschema / any third-party dep** in the engine (stdlib only, single file).
- **Hard enforcement** of permissions/roles/validation in the first increments (advisory first).
- M8Shift **running models**, **auto-merging**, **auto-selecting agents**, or any background
  daemon/watcher. Worktree git commands run **only** behind an explicit opt-in.

## 3. The governing decision: turn-header markdown, not YAML

All Stage-2 structured data lives in the **LOCK block** and **turn headers** as flat
`- key: value` lines (lists are comma-separated), the exact format M8Shift already writes
and parses. The engine **writes these fields verbatim and never re-reads them** to decide
anything — only `to` and `state` drive the mutex. Consequences: stdlib-only, single file,
one source of truth, and the contract stays a **consultative passthrough** the receiving
agent interprets with its own auth. Codex's YAML specs + JSON schema remain useful as
**human-facing examples**, validated by the kit's optional `validate_specs.py` — not as
engine input. (Trade-off accepted: nested structures/lists become flat CSV text.)

## 4. State machine (N agents, one pen)

`LOCK` fields (additions in **bold**):

```
holder:   <active agent | none>
state:    IDLE | WORKING_<X> | AWAITING_<X> | DONE      (X = any active agent, uppercased)
agents:   claude,codex,gemini,...                       (CSV — now N active, was 2)
roles:    claude=coordinator,codex=implementer,...       (optional, advisory)   ← new
turn:     <n>
since: / expires: / note: / lang:
```

- `claim <me>` succeeds from `IDLE` (any active agent; one O_EXCL winner) or
  `AWAITING_<me>`. `WORKING_<other>` / `AWAITING_<other>` refuse.
- `append <me> --to <X>` closes the turn and routes the baton to **any other active** `X`
  (`X` ≠ `me`, `X` ∈ active). Strict-alternation-to-2 is dropped; exclusivity of the work
  window is unchanged (you still only write while holding the pen).
- `release` → `IDLE`. `done` → `DONE`. `--force` recovery unchanged.

Guarantees carried over verbatim: N simultaneous claims → one winner; inactive/absent
target refused; immediate self-target refused; closed turns immutable; writes serialized
by `.m8shift.lock` + atomic replace.

## 5. Turn schema (advisory fields)

Existing required fields stay: `from`, `to`, `ask`, `done`, `files`, `handoff`.
New **optional, write-only** advisory fields (any subset; default `-`):

| field | meaning | engine behavior |
|---|---|---|
| `role` / `target-role` | poster's / receiver's active role | passthrough |
| `relation` | delegate / implement / review / revise / integrate / continue / `x-*` | passthrough |
| `allow` / `deny` | capability hints (CSV) | passthrough |
| `enforce` | `advisory` (the only honest value today) | passthrough |
| `expect` | required outputs (CSV) | passthrough |
| `validator` / `status` | who reviews / validation status | passthrough |
| `branch` / `commit` / `tests` | VCS + test context | passthrough |
| `blocked_on` / `next` | wait reason / suggested next command | passthrough |
| `observers` | informational agents, **no work right** | passthrough |
| `task` | task id (see §7) | passthrough |

The engine validates **only** `to ∈ active` and `to ≠ self`. Every other field is recorded
and never interpreted. `clean_field` injection-safety applies to all of them.

## 6. Roles / relations / capabilities = optional convention

Codex's vocabulary (12 roles, 11 relations, 11 capabilities) ships as a **documented
convention**, not an engine-enforced schema. `x-` prefix escapes for custom values. The
engine does **not** check role membership (preserves MINIMAL). A later opt-in
`--strict-roles` could soft-validate against a project-declared list, but it is not in the
first increments.

## 7. Tasks board (optional, append-only)

A sibling `M8SHIFT.tasks.md`, one task per line, serialized by the **same** O_EXCL lock:

```
id | owner | state | deps | files | note
```

`tasks add/claim/done` mutate one line under `file_lock`; `tasks list` and a read-only
`READY` view (deps satisfied) compute from the file. **No** auto-routing, **no** background
watcher, **no** auto-READY side effects — agents read it and pick work on their own turn.

## 8. Concurrency: isolated worktrees (opt-in) — the one open decision

Real parallel work uses **separate git worktrees** (one branch + workspace + workspace lock
per task), consolidated by a single `integration` pen, then an independent reviewer:

```
content -> feat/content -> .m8shift/worktrees/content
assets  -> feat/assets  -> .m8shift/worktrees/assets
                              \-> integration branch (integration pen) -> reviewer
```

This is where M8Shift would **run git** — the largest stretch of "passive". Two shapes:

- **(a) Core subcommand** `m8shift.py worktree …` — git runs only behind this explicit
  opt-in command; the rest of M8Shift stays passive.
- **(b) Separate companion** `m8shift-worktree.py` — keeps the core engine 100 % git-free
  ("runs nothing"); the companion drives git and uses M8Shift files for coordination.

**Recommendation: (b).** Keep the core a passive coordination primitive; ship worktree
orchestration as an opt-in companion. **This is the decision to confirm before building §8.**
Non-goals (from RFC-MA-003): no path-leases, no auto-merge, no auto-deletion of worktrees,
no auto agent selection, no model execution.

## 9. Validation = advisory first

`validator` / `status` (pending / approved / changes_requested / rejected / waived) are
recorded in turns. The engine does **not** refuse a close for a missing/independent
validation in the first increments — independence is a documented expectation. A later
opt-in `--require-validation` could harden it into a passive refusal (still "who writes,
when", just a stricter gate), but it is explicitly deferred.

## 10. Read commands (do these first)

`recap` (LOCK + last N turns + memory headlines), `peek` (last handoff to me, parse-free),
`log` (relay timeline), `status --json`, `agents` (list + active roles), `tasks` (board).
All read-only, passive, stdlib. These are the low-risk **on-ramp** and a prerequisite for
VS Code surfaces.

## 11. Backward compatibility

- The shipped **pair is just N = 2** — no behavior change for existing two-agent projects.
- Turns **without** advisory fields are valid free relays (`relation: continue` implied).
- Phase-2 **dual-read** still applies: legacy `COWORK.*` / `COWORK:*` projects keep working;
  the new fields are optional and additive. No breaking change.

## 12. Sequencing (increments)

1. **Read commands** (`recap`/`peek`/`log`/`status --json`) — prerequisite, lowest risk.
2. **N-agent roster + relay** (pair → N, `append --to <any active>`, `roles` field).
3. **Advisory contract fields** in turns (§5) + injection-safety coverage.
4. **Tasks board** `M8SHIFT.tasks.md` (§7).
5. **(after decision §8)** worktree companion + `integration` pen.
6. **Optional hardening** — `--strict-roles`, `--require-validation`.

## 13. Tests (extends the Phase-2 matrix)

3–16 agents; N concurrent claims → one winner; inactive/self target refused; every advisory
field round-trips and **never** changes the mutex; `tasks` deps → deterministic `READY`;
worktree isolation + exclusive integration; injection neutralized for **both** brands;
**no network call added**; pair-mode (N = 2) byte-unchanged.

## 14. Open decisions

1. **§8 worktrees:** core subcommand vs separate companion (recommend **companion**).
2. **§9 validation:** ship advisory-only, or add opt-in `--require-validation` now?
3. **§6 roles:** convention-only vs soft `--strict-roles`.
4. **Config ceiling:** confirm turn-header markdown over YAML for *all* structured data (§3).

---

*This RFC keeps M8Shift a single passive file that answers one question — who writes, when —
and adds N-agent reach, advisory context, and opt-in isolated concurrency without a daemon,
a dependency, a degree-N lock, or a second source of truth.*
