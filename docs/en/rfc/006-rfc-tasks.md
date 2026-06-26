# RFC — Tasks board (`M8SHIFT.tasks.md` + `task`)

**Status:** SHIPPED — **ship-reduced** (v3.4.0) · roadmap item "🗂️ Tasks board / block-on" ·
design validated by an adversarial panel (Q0 + 3 angles → skeptical synthesis, all unanimous)

## Q0 — does this belong in the core at all? → **SHIP-REDUCED**

The memory precedent (`remember`) proves a dumb, append-only, pen-free, file-ordered sibling
ledger lives in the core *without* becoming a second authority: it takes `file_lock`, never
`set_lock`. A task ledger is the same artifact class and ships **iff** built as the strict twin of
memory. It is *reduced* (not full ship) because three features from the original sketch cross the
charter and are **cut to the companion permanently**: (a) a mutate-in-place HTML-comment TASK
block (a second mutable authoritative artifact) → replaced by an append-only event transcript;
(b) a `deps (all|any):id` grammar + READY evaluator (cross-record dependency-solving); (c)
reopen/transition/ownership validation + an id-referencing `blocked_on` (a state machine + the
seed of READY). What ships is last-event-wins status, opaque verbs, free-text `blocked_on`.

## Goal (if Q0 = yes)

A durable, append-only to-do ledger the agents curate by hand: what's planned / in progress /
done, and naming an **external** dependency as an advisory `blocked_on` wait reason. The turn
journal records *what happened*; tasks record *what is intended to happen*.

## Non-goals (carried from the README / memory charter)

No gating: a task NEVER blocks a `claim`/`append`; `blocked_on` is advisory text, not enforced.
No second authority: task state NEVER feeds the mutex/routing. No derived intelligence
(auto-assign, priority ranking, dependency-cycle solving, auto-close). The core stays a **dumb,
human-curated record**; current status is the only "derivation" and it is a transparent
last-event-wins replay (like memory's most-recent-wins), nothing more.

## Sketch (if Q0 = yes)

- `task add "<desc>" [--for <agent>] [--blocked-on <ref>]` — append a task. *(write)*
- `task done <id>` / `task drop <id>` — append a status event referencing the id. *(write)*
- `task list [--all]` — read-only; open tasks by default. *(read)*
- `recap` may show a short "open tasks" headline tail (like memory headlines).
- File `M8SHIFT.tasks.md`: a sibling artifact (like memory/archive), **gitignored**, lazily
  created, append-only. Each line is a flat event: `- #<id> <iso> <verb> <author>: <text>`.
- Pen-free (curation, like `remember`): `file_lock` only, never the pen. `clean_field` on text;
  `need_agent` on author/`--for`; `parse_tasks` read-only, current status by last event per id.

## Resolved by the panel

1. **Status → append-only event log + read-time last-event-wins fold** (`fold_tasks`). One line per
   event `- #<id> <isoZ> <verb> <author>: <text>`; current status = the latest event's verb; a
   task's identity (description, author) stays its `add` event. No engine-validated verb
   vocabulary, no transition checks (that is a state machine = second authority). The fold has
   ZERO cross-task logic — the same "most-recent-wins replay" memory already ships.
2. **IDs → sequential `1+max(existing)`**, derived *inside* `file_lock` after the read (race-free,
   like `remember`'s locked read-derive-write). The only value derived from prior content — an
   opaque label, never a routing key. Timestamp ids rejected (1 s resolution collides).
3. **`blocked_on` → free text, advisory, zero enforcement / zero resolution.** Never a task-id
   reference, never parsed back — so dependency-solving is structurally impossible in the core.
4. **Pen → pen-free** (`file_lock` only, never `set_lock`), identical to `remember`. The pen gates
   `M8SHIFT.md`; a different file needs only its O_EXCL lock. `load_or_die` runs only to populate
   ROSTER/LANG; the LOCK state is ignored (`cmd_task` never branches on holder/state).
5. **recap + list/show → both.** `task list` (open by default; `--all` adds done/drop) + `task
   show <id>` (event history) earn their place — a fold-to-status can't be replicated with `cat`.
   `recap` gains an open-tasks tail (`--tasks N`, default 5, `<=0`=all) guarded by file existence
   (absent ⇒ byte-unchanged). No `--owner/--state/--tag` filters, no sort (a query layer).
6. **`--for` → optional, advisory attribution only**, `need_agent`-validated if given (catches
   typos), recorded verbatim, NEVER routing/ownership. Backlog items are legitimately unassigned.

**No-authority guarantee:** `cmd_task` never names `set_lock`; `claim/append/wait/load_or_die`
never call `parse_tasks`/`fold_tasks`. A blocked/open task never blocks a claim, and a task still
closes instantly. (Source-pinned by `test_cmd_task_has_no_set_lock` + `test_routing_never_reads_tasks`.)

**Companion-only, permanently (rfc-n-agents §7/§8):** dependency grammar + READY evaluation,
transition/ownership gating, auto-close, `--for` routing. `blocked_on` stays free text forever.
