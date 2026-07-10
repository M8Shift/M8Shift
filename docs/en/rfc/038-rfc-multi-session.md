# RFC 038 — Parallel multi-session M8Shift on one project

- **Status:** draft (Codex-reviewed, stabilized)
- **Builds on:** [002-rfc-n-agents.md](002-rfc-n-agents.md) (one shared pen), [008-rfc-worktree-companion.md](008-rfc-worktree-companion.md) (worktrees), [015-rfc-shared-tree-degree-gt1.md](015-rfc-shared-tree-degree-gt1.md) (degree > 1 rejected), [035-rfc-interactive-listener-gap.md](035-rfc-interactive-listener-gap.md) (`M8SHIFT_ROOT`)
- **Core invariant:** each session stays a **degree-1, one-pen** relay. This RFC replicates that relay under a namespace; it does **not** introduce degree > 1 concurrent writes to one tree.

## 1. Problem

The relay state — `M8SHIFT.md`, `.m8shift.lock`, and the memory / tasks / sessions sidecars — is
a **singleton per directory**. A project directory hosts exactly **one** relay session. So you
cannot run two independent M8Shift sessions on the same project in parallel — for example one pair
of agents on feature A and another pair on feature B. It is effectively one session per project
checkout (and, in a shared checkout, one per machine).

## 2. Decision

Allow multiple **named relay sessions** per project. Each session owns a namespaced set of relay
files and is selected by name. The **default (unnamed) session preserves today's behavior
byte-for-byte** — zero migration for existing users.

## 3. Namespacing

- A named session's files live under a per-session namespace:
  `.m8shift/sessions/<name>/` holding that session's `M8SHIFT.md`, lock, memory, tasks, and
  sessions ledger (and protocol/archive files where applicable). This is chosen over top-level
  suffix files: it keeps the root clean and scales to every sidecar.
- The default session keeps the current top-level files (`M8SHIFT.md`, `.m8shift.lock`) unchanged.
- **Safe-name requirement.** A session `<name>` must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
  (no path separators, no leading dot, bounded length). Any command with an invalid name is
  **rejected before any write** — the resolver never constructs a path from an unvalidated name.
- `M8SHIFT_ROOT` selects the project root (RFC 035); `M8SHIFT_RELAY_SESSION` (or a
  `--relay-session <name>` flag) selects the relay session within it. No selector = the default
  session.

### 3.1 Exact file mapping

Each artifact keeps its basename; only the parent directory changes. Default (unnamed) session
uses today's top-level paths; a named `<name>` session moves them under
`.m8shift/sessions/<name>/`:

- **Bridge / turns** — `M8SHIFT.md` → `.m8shift/sessions/<name>/M8SHIFT.md`
- **Lock** — `.m8shift.lock` → `.m8shift/sessions/<name>/.m8shift.lock`
- **Memory ledger** — current top-level path → `.m8shift/sessions/<name>/<same basename>`
- **Tasks ledger** — current top-level path → `.m8shift/sessions/<name>/<same basename>`
- **Sessions history** — current top-level path → `.m8shift/sessions/<name>/<same basename>`

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

- `m8shift.py --relay-session <name> <cmd>` — every command takes an optional relay session; no
  name = the default session. Path resolution lives in the **core** (see §7 Q2), so companions and
  direct core commands see the same namespace.
- `m8shift.py sessions list` — enumerate the named relay sessions present in the project (read-only
  inventory; see §7 Q3).
- The companions (`m8shift-runtime.py`, `m8shift-context.py`, `m8shift-worktree.py`) resolve the
  **same** relay-session namespace so presence, packs, worktrees, and reports stay per-session.

### 5.1 Naming — relay session vs runtime lane (Codex Finding MED)

`m8shift-runtime.py watch --session` **already exists** ([m8shift-runtime.py](../../m8shift-runtime.py),
`--session` = *stable UI/session id for this agent lane*). That is a lane/UI identity, **not** a
relay namespace. To avoid a same-name/different-concept collision, this RFC uses a **distinct term**
for the relay namespace: `--relay-session` / `M8SHIFT_RELAY_SESSION`. The runtime `watch --session`
lane id is left untouched — no rename, no compatibility break. Operators keep two clearly separate
concepts: the **relay session** (which coordination namespace) and the **runtime lane** (which UI
identity within a session).

## 6. Charter

1. **Passive core, per session.** Each session is the same passive one-pen mutex; nothing here
   weakens the mutex — it replicates it under a namespace.
2. **Backward compatible.** No session name = today's behavior, byte-identical; the default path
   and file names are unchanged.
3. **Not degree > 1.** This is N *independent* degree-1 relays, not concurrent writers on one
   relay. RFC 015's rejection stands.

## 7. Resolved questions (Codex review)

1. **Namespace layout.** `.m8shift/sessions/<name>/`, not top-level suffix files — clean root,
   scales to all sidecars, explicit safe-name regex (§3), exact file mapping (§3.1). Default
   unnamed session stays top-level.
2. **Core vs companion.** The selector is **first-class in the core path resolver** — direct
   `m8shift.py claim/status/append` must see the same namespace as companions, and a wrapper-only
   layer is too easy to bypass. Kept minimal: **path resolution only**, no cross-session policy in
   the core.
3. **Cross-session visibility.** Read-only only: `sessions list` (and optionally
   `sessions status --all`). It is **operator inventory, never routing authority** — it must never
   affect claimability across sessions.
4. **One session ↔ one worktree.** Strong recommendation and the automated path in
   `m8shift-worktree.py` where possible, but **not mandatory in the core** (valid low-risk /
   doc-only / non-overlap cases exist). The RFC warns: same-checkout multi-session is
   **coordination-parallel, not filesystem-safe**.

## 8. Acceptance tests (required at implementation)

- No session selector → **byte-identical** top-level path behavior.
- A named session writes **only** under `.m8shift/sessions/<name>/`.
- Invalid session names are **rejected before any write**.
- Two named sessions independently reach `WORKING_*` **without sharing LOCK files**.
- The default session stays compatible with existing files.
- `m8shift-runtime.py` / `m8shift-context.py` / `m8shift-worktree.py` resolve the **same** relay
  namespace without confusing it with the runtime lane id (§5.1).

## 9. Session binding (amendment — RFC 052 PR4, design for review)

Operator requirement (RFC 052): *a shift is a work session bound to ONE project; if the
target is ambiguous, the tooling asks the operator instead of guessing; identifiers never
cross shifts.* PR1 shipped the behavioral rule (agent-pack text). This amendment adds the
**mechanics**, without implementing the full named-namespace resolver above (which stays
future work). Everything below is **opt-in / triggered state**: with no binding and no
ambiguity, behavior stays byte-identical.

### 9.1 The ambiguity this closes

`M8SHIFT_ROOT` (RFC 035) silently WINS over a cwd-local relay. A leftover
`M8SHIFT_ROOT` from a previous shift (shell profile, reused terminal) plus a cd into
another project that has its own `M8SHIFT.md` is exactly the recorded cross-shift leak
vector: the agent writes into the WRONG project's relay without any signal.

- **A1 — ambiguity refusal (write commands).** When the `M8SHIFT_ROOT`-designated relay
  AND a cwd-local relay BOTH exist and differ, write commands (`claim`, `append`, `next`,
  `request-turn`, `yield-turn`, `steer-turn`, `resume`, `pause`, `task add/done/drop`,
  `remember`, …) **refuse before any write**, naming both candidates and asking the
  operator to disambiguate (unset `M8SHIFT_ROOT`, or bind — A2). Read-only commands
  (`status`, `doctor`, `log`, `peek`, …) keep working and surface both candidates.
- **A2 — explicit binding.** `m8shift.py bind <agent>` records the agent's durable choice
  in the TARGET relay: `.m8shift/bindings/<agent>.json` holding the resolved root
  identity (realpath), the project name, `bound_at`, and a reserved `relay_session`
  field (RFC 038 §3 names, default session today). Penless by design — you bind BEFORE
  claiming (same class as `task add` / `remember`). `bind <agent> --show` and
  `bind <agent> --clear` round it out. Binding is per-agent, per-relay, operator-visible.
- **A3 — binding verification (fail-closed when present).** `may-i-write`, `claim` and
  `append` verify an existing binding: if the binding's root identity does not match the
  effective root, **refuse** with the bound-elsewhere path (redacted to basename +
  hash if outside this project — a foreign project path must not leak into this relay's
  terminal/logs, per RFC 052) and the rebind instruction. A binding that MATCHES one of
  two ambiguous candidates **resolves A1** to the bound relay. No binding = today's
  behavior.
- **A4 — `sessions list` (read-only inventory).** Ships RFC 038 §5's command surface
  early: enumerates the default relay plus any named session directories under
  `.m8shift/sessions/` (forward-compatible with §3; today that is normally just the
  default), each with its state and the agents bound to it. Operator inventory, never
  routing authority (§7 Q3) — single-project only, never scans sibling projects
  (RFC 052 C3: auto-discovery across projects would violate the rule it enforces).
- **A5 — delivery.** The agent-pack Compartmentalization section gains the mechanical
  line: *"at session start run `./m8shift.py bind <you>`; if a write is refused for
  ambiguity or a binding mismatch, STOP and ask the operator which project this shift
  binds to."* Floor-marker addition so stale anchors surface it.

### 9.2 Charter fit

Local, stdlib-only, no network, no daemon. Fail-closed refusals trigger only on
operator/agent-created state (a binding) or true ambiguity (two candidate relays); the
zero-config path is untouched. The named-namespace resolver (§3) remains unimplemented;
`relay_session` is recorded but only the default session is addressable until RFC 038
lands fully.

### 9.3 Acceptance criteria (implementation)

- No binding, no ambiguity → byte-identical behavior (full suite unaffected).
- `M8SHIFT_ROOT` + differing cwd-local relay → every write verb refuses BEFORE any write,
  naming both candidates; read-only verbs still work.
- Binding mismatch → `may-i-write`/`claim`/`append` refuse; foreign path redacted in the
  message; `bind --clear` + rebind recovers.
- Binding match resolves the A1 ambiguity to the bound relay.
- `bind` is penless, idempotent, safe-name/JSON-shape validated, and never creates a
  relay (binding to a missing relay is refused).
- `sessions list` is read-only, single-project, and lists bindings per session.
- Hygiene: binding files carry the OPERATOR'S OWN paths only (they never leave the
  machine — gitignored like the rest of `.m8shift/` state).

## 10. Recommendation

Adopt the named relay-session model with the default session preserving today's behavior. Use the
distinct `--relay-session` / `M8SHIFT_RELAY_SESSION` selector (§5.1). Pair parallel sessions with
worktrees for file isolation. Keep it charter-pure: **N independent degree-1 relays**, never
degree > 1.
