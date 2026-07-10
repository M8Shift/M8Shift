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

## 9. Session binding (amendment — RFC 052 PR4; design rev 3 Codex-approved, IMPLEMENTED)

Operator requirement (RFC 052): *a shift is a work session bound to ONE project; if the
target is ambiguous, the tooling asks the operator instead of guessing; identifiers never
cross shifts.* PR1 shipped the behavioral rule (agent-pack text). This amendment adds the
**mechanics**, without implementing the full named-namespace resolver above (which stays
future work). Everything below is **opt-in / triggered state**: with no binding and no
ambiguity, behavior stays byte-identical.

### 9.1 Candidates and physical identity (Codex #4)

- The **two possible relay authorities** are exactly: the relay designated by
  `M8SHIFT_ROOT` (RFC 035) and the **script-local** relay (`HERE`, the running script's
  directory — today's local authority). **No cwd parent-walk, no sibling or recursive
  discovery** (RFC 052 C3: cross-project discovery would violate the rule it enforces).
- **Ambiguity** exists when BOTH designate an EXISTING relay and they are **physically
  different**: equality is `os.path.samefile` when both exist (symlinks and
  case-insensitive filesystems resolve correctly), with a platform-aware fallback
  (`os.path.normcase` comparison on Windows; exact canonical comparison elsewhere).
  **Never unconditionally case-fold** — distinct `/Foo` and `/foo` relays are legitimate
  on case-sensitive filesystems. A symlinked checkout resolving to the same physical
  root is NOT ambiguous.
- Binding files store the **canonical realpath** for diagnostics; equality checks use the
  samefile rule above, never string comparison alone.

### 9.2 A1 — centralized pre-write ambiguity/binding policy (Codex #1)

One **single pre-write gate**, not a per-command check, with TWO distinct layers
(Codex rev-2 #1 — several mutators deliberately carry NO agent identity; never invent
or infer one):

- **A1 ambiguity layer — every mutator, agentless included**: `claim` (incl.
  `--refresh`), `append`, `next` (treated as mutating BEFORE it polls/claims),
  `request-turn`, `yield-turn`, `decline-turn`, `steer-turn`, `pause`, `cooldown`,
  `resume`, `release`, `done`, `remember`, `task add/done/drop`, `archive`,
  `decisions target --set`, `decisions scaffold`, and `session report --write`.
  An **agentless mutator under unresolved ambiguity always refuses** — no agent
  binding may silently resolve the target for a write that names no actor; with a
  single candidate it preserves today's behavior.
- **A3 binding layer — actor-bearing mutators only**: the per-agent binding
  verification applies exactly where the command has a validated actor argument
  (`claim`, `append`, `next` via its agent, `request-turn`/`yield-turn`/
  `decline-turn`/`steer-turn`, `pause`/`resume`/`release`/`done`, `remember`,
  task mutations). `may-i-write` reports binding validity read-only. Acceptance
  tests must pin BOTH branches (an agentless write refused under ambiguity even
  when a binding exists; an actor-bearing write resolved by its own binding).
Read-only commands are explicitly excluded: `status`, `doctor`, `log`, `peek`,
`history`, `recap`, `watch`, `wait`, `claim --check`, `task list/show`,
`contract validate`, `decisions target` (without `--set`),
`session list/show/decisions/report` (without `--write`), `update --dry-run`,
`bind --show` / `bind --list`. They keep working under ambiguity and surface both
candidates (disclosure per §9.5).

- **Ordering**: the ambiguity refusal happens **before `file_lock` can create any lock
  file** (a refusal must not leave a lock behind). The **binding verification is
  re-checked under the selected relay's file lock immediately before the mutation** — an
  outer preflight alone is TOCTOU-prone.
- **Special cases**:
  - `update` carries an **explicit `--target` authority** with command-scoped rebase:
    ambient `M8SHIFT_ROOT`/local ambiguity must **not** refuse or override that explicit
    target (its own safety checks still apply).
  - `init` is bootstrap, not a bound write: no-env bootstrap and same-physical-root
    env stay allowed. `init` **refuses whenever a non-empty M8SHIFT_ROOT resolves to
    a physical/canonical root different from HERE — whether or not the env target or
    its relay exists yet** (Codex rev-2 #2: import-time root configuration plus
    `file_lock` can CREATE a previously missing external directory while `init`
    writes script-local anchors/companions — exactly the hybrid this rule prevents).
    The refusal precedes `file_lock` and any directory creation; a binding never
    silently chooses where `init` writes.

### 9.3 A2 — explicit binding with a deterministic target (Codex #2, #3)

`m8shift.py bind <agent>` records the agent's durable choice in the TARGET relay:
`.m8shift/bindings/<agent>.json` (canonical realpath identity, project name, `bound_at`,
reserved `relay_session` field — RFC 038 §3 names stay future work). Penless by design
(you bind BEFORE claiming — `task add`/`remember` class), **but**:

- **Deterministic target selection**: zero or one existing candidate → deterministic.
  With TWO distinct candidates, `bind` **refuses** unless (a) exactly one existing,
  self-consistent binding already resolves the choice, or (b) the operator passes the
  **closed selector `--candidate env|script`** (env = the M8SHIFT_ROOT relay, script =
  the script-local relay). The refusal message gives the non-leaking symbolic hints
  (`--candidate env` / `--candidate script`) — the operator is never asked to
  reconstruct a redacted absolute path (§9.5 displays basename+hash only). `bind`
  **never silently inherits env-wins**.
- **Live-pen guard (charter condition for penless writes)**: any binding **mutation**
  (`bind`, `bind --clear`) takes the target relay's file lock and **refuses while the
  named agent holds a live `WORKING_<agent>` lock in ANY candidate** — rebinding must
  not strand a pen or make a pending `append` resolve elsewhere. Recover the stale
  lock explicitly first (`append`/`release`/`pause`/recovery); rebind never bypasses it.
  `bind --show` (and `bind --list`, §9.4) stay read-only and lock-free.
- **Scope honesty**: a binding stored inside a relay is a **local root pin** for this
  project — it is NOT a claim that the agent holds no binding in some undiscovered
  sibling project. No sibling scan, no global exclusivity.

### 9.4 A3/A4 — verification and inventory (Codex #1, #6)

- The centralized gate (§9.2) verifies an EXISTING binding for the acting agent:
  mismatch (per §9.1 identity) → **refuse** with the disclosure rule of §9.5 and the
  recovery instruction (`bind <agent> --clear` on the bound relay, then rebind). A
  binding that MATCHES one of two ambiguous candidates resolves A1 to the bound relay.
  `may-i-write` stays read-only but **reports binding validity** in its output.
- **`sessions list` is DEFERRED** out of PR4 (Codex #6: the core already has the
  singular `session list` for HISTORICAL sessions — a plural near-homonym addressing
  normally-absent namespaces is a two-model trap and a half-RFC-038 API). The useful
  current capability ships as **`bind --list`**: read-only inventory of the bindings
  recorded in THIS relay (agent, identity per §9.5, bound_at, relay_session field).
  The full namespace inventory returns with the RFC 038 resolver itself.

### 9.5 Disclosure rule (Codex #5)

ONE rule for every surface (ambiguity refusals, mismatch refusals, read-only warnings,
JSON payloads): a candidate/bound root **outside the current project** is shown as
**basename + stable short hash** (`…/<basename> [root:<sha256-10>]`), never the full
foreign path — terminal and JSON output is routinely pasted into handoffs (RFC 052).
The full canonical path lives only in the gitignored binding file; local forensics can
read it there directly.

### 9.6 Charter fit

Local, stdlib-only, no network, no daemon. Fail-closed refusals trigger only on
operator/agent-created state (a binding) or true ambiguity (two physically-distinct
candidate relays); the zero-config path is untouched. Penless binding is admissible
ONLY with the §9.3 serialization + live-pen guard. The named-namespace resolver (§3)
remains unimplemented; `relay_session` is recorded but only the default session is
addressable until RFC 038 lands fully.

### 9.7 Acceptance criteria (implementation)

- No binding, no ambiguity → byte-identical behavior (full suite unaffected).
- Two physically-distinct candidates → EVERY mutator in the §9.2 matrix refuses BEFORE
  any write or lock-file creation, naming both candidates per §9.5; every listed
  read-only command still works; `update --target` and `init` follow their §9.2
  special-case rules.
- Binding verification re-checked under the relay file lock (TOCTOU pin); mismatch →
  refusal with §9.5 disclosure; `bind --clear` + rebind recovers.
- Binding match resolves the A1 ambiguity to the bound relay.
- `bind` with two candidates refuses without the closed `--candidate env|script`
  selector (or a pre-existing resolving binding); it never env-wins silently.
- Split-layer pins: an AGENTLESS mutator (e.g. `archive`, `decisions target --set`)
  refuses under unresolved ambiguity even when an agent binding exists; an
  actor-bearing mutator is resolved by its own agent's matching binding.
- `init` refuses whenever non-empty `M8SHIFT_ROOT` resolves to a different physical
  root than HERE — even if that target does not exist yet — before any lock/dir
  creation; no-env and same-physical-root init are unaffected.
- `bind`/`bind --clear` refuse while the named agent holds a live WORKING lock in any
  candidate; a stale lock requires explicit recovery first.
- Symlinked same-physical-root checkouts are NOT ambiguous (samefile); `/Foo` vs `/foo`
  on a case-sensitive filesystem ARE distinct.
- `bind --show`/`--list` are read-only, lock-free, and disclose per §9.5.
- Hygiene: binding files carry the operator's own paths only, gitignored with the rest
  of `.m8shift/` state; no foreign full path ever reaches terminal/JSON output.

## 10. Recommendation

Adopt the named relay-session model with the default session preserving today's behavior. Use the
distinct `--relay-session` / `M8SHIFT_RELAY_SESSION` selector (§5.1). Pair parallel sessions with
worktrees for file isolation. Keep it charter-pure: **N independent degree-1 relays**, never
degree > 1.
