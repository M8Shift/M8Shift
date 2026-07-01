# RFC 038 — Parallel multi-session M8Shift on one project

- **Status:** draft
- **Builds on:** [002-rfc-n-agents.md](002-rfc-n-agents.md) (one shared pen), [008-rfc-worktree-companion.md](008-rfc-worktree-companion.md) (worktrees), [015-rfc-shared-tree-degree-gt1.md](015-rfc-shared-tree-degree-gt1.md) (degree > 1 rejected), [035-rfc-interactive-listener-gap.md](035-rfc-interactive-listener-gap.md) (`M8SHIFT_ROOT`)
- **Core invariant:** each session stays a **degree-1, one-pen** relay. This RFC replicates that relay under a namespace; it does **not** introduce degree > 1 concurrent writes to one tree.

## 1. Problem

The relay state — `M8SHIFT.md`, `.m8shift.lock`, and the memory / tasks / sessions sidecars — is
a **singleton per directory**. A project directory hosts exactly **one** relay session. So you
cannot run two independent M8Shift sessions on the same project in parallel — for example one pair
of agents on feature A and another pair on feature B. It is effectively one session per project
checkout (and, in a shared checkout, one per machine).

## 2. Decision

Allow multiple **named sessions** per project. Each session owns a namespaced set of relay files
and is selected by name. The **default (unnamed) session preserves today's behavior byte-for-byte**
— zero migration for existing users.

## 3. Namespacing

- A named session's files live under a per-session namespace, e.g.
  `.m8shift/sessions/<name>/` holding that session's `M8SHIFT.md`, lock, memory, tasks, and
  sessions ledger.
- The default session keeps the current top-level files (`M8SHIFT.md`, `.m8shift.lock`).
- `M8SHIFT_ROOT` selects the project root (RFC 035); `M8SHIFT_SESSION` (or a `--session <name>`
  flag) selects the session within it.

## 4. Isolation — what the relay does and does not give you

- **Coordination is isolated.** Each session's `LOCK` / turns / memory are independent: the pen in
  session A never blocks session B. Two sessions run truly in parallel at the coordination layer.
- **File isolation is out of the relay's scope.** Two sessions on the *same working tree* still
  share the project files; their agents can still clobber each other's edits. The relay coordinates
  *within* a session, not *across* sessions. So parallel sessions on one checkout require either
  **non-overlapping file scopes** or — more robustly — **one git worktree per session**
  ([008-rfc-worktree-companion.md](008-rfc-worktree-companion.md)). The relay namespaces
  coordination; worktrees namespace files. The two together are what make real parallelism safe.

## 5. Command surface (sketch)

- `m8shift.py --session <name> <cmd>` — every command takes an optional session; no name = the
  default session.
- `m8shift.py sessions list` — enumerate the named sessions present in the project.
- The companions (`m8shift-runtime.py`, `m8shift-context.py`) resolve the **same** session
  namespace so presence, packs, and reports stay per-session.

## 6. Charter

1. **Passive core, per session.** Each session is the same passive one-pen mutex; nothing here
   weakens the mutex — it replicates it under a namespace.
2. **Backward compatible.** No session name = today's behavior, byte-identical; the default path
   and file names are unchanged.
3. **Not degree > 1.** This is N *independent* degree-1 relays, not concurrent writers on one
   relay. RFC 015's rejection stands.

## 7. Open questions

1. Namespace layout: `.m8shift/sessions/<name>/` (clean) vs a suffix on the top-level files
   (closer to today)?
2. First-class in the core, or a thin companion/wrapper that sets the resolution (keeps the core
   minimal)?
3. Cross-session visibility: should `sessions list` / a dashboard show every session's state, or
   stay strictly per-session?
4. Should "one session ↔ one worktree" be the recommended (or automated) default for true
   parallelism, wired through [008-rfc-worktree-companion.md](008-rfc-worktree-companion.md)?

## 8. Recommendation

Adopt the named-session model with the default session preserving today's behavior. Pair parallel
sessions with worktrees for file isolation. Keep it charter-pure: **N independent degree-1
relays**, never degree > 1.
