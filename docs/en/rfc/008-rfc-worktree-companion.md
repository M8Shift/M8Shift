# RFC — Worktree companion (§8): degree-2 concurrency, opt-in

**Status:** implemented v1 · **Surface:** `m8shift-worktree.py` opt-in companion · **Builds on:**
[002-rfc-n-agents.md](002-rfc-n-agents.md) §8/§8c (the settled model) · **Co-designed:** Claude ⇄ Codex via the relay

## Goal

True **degree-2** concurrency *without breaking the degree-1 core*: several agents work in **isolated
git worktrees** in parallel, and a single **integration pen** merges them into the target branch
one-by-one. The passive, single-pen `m8shift.py` core is unchanged in spirit; the concurrency lives
in an **opt-in companion** (`m8shift-worktree.py`) that **imports `m8shift`** and reuses its lock /
LOCK / tasks helpers — never a second source of truth.

## Settled by rfc-n-agents §8 (the constraints we keep)

1. **Canonical-root pinning (REQUIRED).** Coordination paths (`.m8shift.lock`, `M8SHIFT.md`, tasks)
   must resolve to the **canonical repo root** (parent of `git rev-parse --git-common-dir`, or
   `$M8SHIFT_ROOT`), **never** the worktree's own `m8shift.py` copy — else two integrators compute
   different lockfiles and double-merge.
2. **Lock order (REQUIRED, no inversion).** Acquire the global canonical-root `.m8shift.lock` →
   atomic flip → **release it** → *then* run git/worktree work. **Never hold two of {global lock,
   integration pen, workspace} at once.** Per-worktree single-writer is an **advisory** task
   `state=WORKING`/`owner`, not a second long-lived lock.
3. **Merge contract (REQUIRED).** On a non-clean merge: `git merge --abort`, leave the worktree
   untouched, set the integrate task `BLOCKED` (`blocked_on=conflict:<id>`), exit non-zero — no
   partial state. Target via `git symbolic-ref --short HEAD` or `--into`; never assume `main`.
4. **Integration pen = a normal LOCK transition** in the shared `M8SHIFT.md` (the existing `claim`
   path), not a new primitive.
5. **Honesty.** Worktrees share one git repo (refs/objects/index); isolation is **advisory
   discipline**, integration is serialized because **one agent honors the integration pen**.
6. **§8c liveness supervisor** (optional, companion-only): a headless loop over `status --json` that
   detects `now > expires` with no progress and re-routes (`claim --force` + reassign) — never in the core.

### Companion command surface (original §8 sketch — SUPERSEDED)

> ⚠️ This is the original rfc-n-agents §8 sketch, kept for context. The **authoritative v1
> surface is the [`## v1 contract (CONVERGED)`](#v1-contract-converged--codex-co-design--adversarial-pressure-test)
> section below**: v1 has **no `review`, no deps/READY gating, no optional `--into`** — `integrate`
> requires `<id> <agent> --into <branch> --to <next-agent>`. Implement the converged surface, not this.

```
m8shift-worktree claim     <id> <agent>   # git worktree add + task→WORKING (gates on READY)
m8shift-worktree done      <id>           # task→COMPLETED
m8shift-worktree integrate [--into B]     # integration pen (shared LOCK); refuse if deps unmet; merge 1-by-1
m8shift-worktree review    <id> <reviewer> --status approved|changes_requested
m8shift-worktree drop      <id>           # remove worktree (confirmation required, never auto)
```

## Open questions (the co-design agenda — Codex, weigh in)

1. **Canonical-root in the CORE.** Pinning needs `m8shift.py` itself to resolve `LOCKFILE`/living
   file/tasks to the canonical root (currently `HERE = dirname(__file__)`). How do we do this so the
   **single-tree degree-1 relay stays byte-identical** (no worktree ⇒ today's behavior)? `$M8SHIFT_ROOT`
   override + a `git rev-parse --git-common-dir` discovery with a safe fallback to `HERE`? Is this a
   core change or can the companion inject the root when it imports `m8shift`?
2. **Deps / READY without polluting the dumb core.** The core tasks board kept `blocked_on` as **free
   text** (no task-id refs, no dependency-solving — deliberately). The companion needs **structured
   deps** to gate `integrate` on "deps COMPLETED". Where do structured deps live — a companion-only
   sidecar, or a blessed `x_deps:` advisory turn/task field the companion (not the core) interprets?
3. **Minimal v1 scope.** §8 is large. What is the smallest *useful, correct* first companion —
   e.g. `claim`/`done`/`integrate` with **manual** dep ordering + the merge contract, deferring the
   READY evaluator, `review`, and §8c? What must v1 NOT cut (the lock-order + canonical-root + merge
   contract are non-negotiable)?
4. **Companion ↔ core dependency.** Confirm: `m8shift-worktree.py` imports `m8shift` and calls
   `file_lock()`/`get_lock`/`set_lock`/task helpers against the canonical-root lockfile (so a core
   `task …` and a companion `worktree claim` are mutually exclusive on the same lock). Any helper the
   core must **expose** (it currently doesn't export a clean tasks API)?
5. **Testing degree-2.** How do we test concurrent integration deterministically (no `Date.now`/race
   flakiness) — serialize via the global lock in-test, assert no double-merge, assert merge-abort
   leaves a clean tree?
6. **Charter check.** Does any of this re-introduce a daemon, a second authority, or derived state
   in the **core**? (The companion may gate/derive; the core must stay passive/dumb.)

## v1 contract (CONVERGED — Codex co-design + adversarial pressure-test)

Codex answered the open questions; an adversarial panel then pressure-tested the result and found
5 real holes (folded below). Ship v1 only when all of this holds.

### Scope
- **Commands**: `claim <id> <agent> --base <b> [--branch <b>]` · `done <id> <agent>` ·
  `integrate <id> <agent> --into <branch> --to <next-agent>` · `drop <id> <agent> --yes` ·
  `status [<id>]`. **Cut from v1**: deps/READY evaluator, `review`, §8c liveness supervisor,
  auto-pick, auto-delete, default target branch.
- **Deps**: v1 = **manual ordering**, `integrate` takes one explicit `<id>`. The core tasks board
  stays dumb (free-text `blocked_on`, no solver). Structured deps (if ever) = a companion-owned
  manifest under the canonical lock, never core routing.

### Core change (minimal, opt-in)
- Add `configure_root(root)` recomputing the living relay, archive, protocol, memory, task and
  lockfile paths; default stays
  `HERE` unless `$M8SHIFT_ROOT`. **Make `read(path=None)`/`write(text, path=None)` late-bind** (today's
  default args capture the old path — the footgun). Single-tree relay stays **byte-identical**.
- Companion discovers the canonical root (`$M8SHIFT_ROOT`, else parent of `git rev-parse
  --git-common-dir`; refuse bare/ambiguous) and injects it **before** any core read/write. It imports
  `m8shift` and calls low-level helpers (`file_lock`/`get_lock`/`set_lock`/`need_agent`/`active_agents`),
  **never** the `cmd_*` CLI functions (they `sys.exit`).

### Lock order & the no-double-merge guard (MUST)
- The global `.m8shift.lock` is held **only** around the LOCK state flip (load_or_die + set_lock +
  atomic write) — **fast local-disk only, < `LOCK_STALE_S` (60s)**; **never** around git. *(panel #2)*
- After the flip's write, the holder **re-verifies it still owns the `.m8shift.lock` token** before
  treating the transition as committed; if it changed (a stale takeover fired), abort + retry. *(panel #2)*
- The integration pen is a **normal core `claim`** transition — BUT its tenure during a merge is guarded
  by a **fact on disk, never the WORKING TTL clock**: before releasing the file lock, the companion
  writes an `integrating:<id>@<target-sha>` sentinel into the LOCK; it **REFUSES to TTL-reclaim
  (`claim --force`) any WORKING pen carrying an `integrating:` sentinel** (an in-flight merge is not a
  reclaimable stale lock — surface it for human/§8c); after the merge, **before** the handoff, it
  re-acquires the file lock and verifies `holder==self AND sentinel==the SHA it recorded`, else
  `git merge --abort` + exit non-zero (no stolen merge). Integrate TTL ≫ realistic merge time. *(panel #1)*

### Integrate target & merge contract (MUST)
- `integrate` merges in a **dedicated integration worktree** `.m8shift/worktrees/_integration` checked
  out on the target branch: `git -C <that-tree> merge <feature-ref>` — never the canonical root checkout,
  never a feature worktree. Target = `--into` else `git symbolic-ref --short HEAD` of that tree, else
  require `--into`. **Before the flip** (fail-before-claim): if the target branch is checked out in any
  *foreign* worktree (`git worktree list --porcelain`), refuse + exit non-zero **without flipping**. *(panel #3)*
- **Pre-flip precondition**: the integration tree is **clean** (`git -C <tree> status --porcelain` empty)
  and on the `--into` branch, else refuse **before claiming**. *(panel #4)*
- **On any post-flip failure** (conflict OR merge-start/checkout error): `git merge --abort` **only if
  `MERGE_HEAD` exists**; then — **unconditionally** — append a turn + **hand off via `--to`** (WORKING_integ
  → AWAITING_next) + exit non-zero, recording the distinguished reason (`blocked_on=conflict:<id>` vs
  `precondition-dirty:<id>`). The abort runs in the pen-pinned integration tree. *(panel #3/#4)*

### No-stuck-WORKING invariant (MUST)
- **No companion command exits while the LOCK is `WORKING_<agent>`** (except a documented hard crash).
- **Fail BEFORE claiming**: `integrate` first does a pure read and validates `--to` is a live roster
  agent (`need_agent`/`active_agents`), `to != integrator`, and `--into/--base` resolve — only then
  claims the pen. The handoff recipient is never validated for the first time post-claim. *(panel #5)*
- Post-clean-merge idempotence: before the handoff append, guard with `git merge-base --is-ancestor`
  so a forced retry can't double-apply; the integrator can resume/hand off its own pen without waiting
  out the TTL. *(panel #5)*

### Hygiene
- Worktrees under ignored `.m8shift/worktrees/<id>/`; ids **path-safe** (no `../`, slash, spaces);
  no network calls; the core never reads companion state to refuse a normal `claim`/`append`.

### Tests (deterministic, temp git repos — no timing races)
canonical-root pinning (no-env byte-identical / env-root / linked-worktree writes canonical) ·
no-double-integration (2nd refuses "already integrated") · concurrent integrate via a test barrier
(2nd refuses on LOCK state) · **TTL-expiry-mid-merge: sentinel present → 2nd refuses reclaim, 1st
verify-then-commit succeeds, exactly one merge effect** · conflict contract (abort → clean tree,
worktree branch untouched, blocked recorded, LOCK not stuck because `--to` handoff happened) ·
file-lock takeover-during-flip (paused flip-holder's write cannot win) · hygiene/path-safety ·
**committed-but-unhanded retry** (integrator resumes its own sentinel, no double-apply).

### Final amendments (Codex sign-off review of the converged contract)

These close real correctness holes in the merge/sentinel flow; they are part of the v1 acceptance criteria.

1. **Non-committing merge so `--abort` is a real rollback (HIGH).** A normal `git merge` may already
   commit / fast-forward, after which `merge --abort` is impossible. So: if the feature is already an
   ancestor of the target → skip to finalize; else run `git -C <_integration> merge --no-ff --no-commit
   <feature-ref>`; **then** re-acquire the canonical file lock and verify **all** of `holder==integrator`,
   `state==WORKING_<integrator>`, `integrating==<id>@<target-sha>`, and the integration worktree
   `HEAD==<target-sha>` (no out-of-band movement); **only then** `git commit` the merge; then append the
   turn + hand off via `--to` + **clear the sentinel**. (Abort is meaningful because the merge is still
   uncommitted at the reverify.)
2. **Sentinel is a first-class, force-guarded LOCK field (HIGH).** A named field `integrating: <id>@<sha>`
   (never hidden in `note`), format-validated, set only while `state==WORKING_<integrator>`, **cleared on
   every finalization path** (success / conflict / precondition-fail / recovery). `claim --force` **and**
   `release --force` **and** `done --force` MUST refuse a WORKING lock carrying it (else a human/runner
   clears the pen mid-merge → stolen merge). A break-glass override, if ever, is explicit and out of v1.
   This is a small **core** LOCK-safety field, scoped to protecting the integration pen — not a deps/review
   solver, so it does not break the dumb-core charter.
3. **`file_lock()` exposes token ownership (MED).** Provide a real API — `file_lock()` yields a guard with
   `still_owned()`, or a low-level token-verify helper — so the companion can confirm it still holds the
   token after the flip without scraping internals. Test takeover/lost-token → caller refuses to commit.
4. **Committed-merge-but-failed-handoff retry/finalize (MED).** After the merge commit but before the LOCK
   handoff, a crash leaves the repo integrated yet the LOCK `WORKING_<integrator>` + `integrating:` set.
   Retrying `integrate <id> <agent> --into B --to X` with the **same** integrator+sentinel MUST be
   idempotent: if the feature is already an ancestor and the sentinel matches → do NOT re-merge; finalize
   (record already-integrated, clear sentinel, append + hand off). The integrator resumes its own pen
   without waiting out the TTL.
5. **Exact target-HEAD check before commit (LOW).** Since the sentinel records `<target-sha>`, verify the
   integration worktree `HEAD` is still that SHA immediately before committing — catches out-of-band branch
   movement in the integration tree.

**v1 acceptance criteria (Codex):** core root override + late-bound read/write; first-class LOCK sentinel
field with force guards; non-committing merge + pre-commit sentinel/HEAD reverify; retry-finalize after an
already-applied merge; unconditional `--to` handoff on every non-crash post-claim path; deterministic tests
for sentinel-TTL, token-loss, double-integrate, conflict-abort, and committed-but-unhanded retry.

## v1 implementation notes & failure modes (`m8shift-worktree.py`)

RFC 008 v1 is implemented by `m8shift-worktree.py` and the minimal core support in `m8shift.py`.
The implemented surface is intentionally limited to `claim`, `done`, `integrate`, `drop`, and `status`.
The shipped acceptance boundary is:

- **Lock-order / no-double-merge guard:** the companion flips the canonical `LOCK` under the shared
  file lock, stamps a first-class `integrating: <id>@<sha>` sentinel, verifies the lock token is still
  owned, then releases the file lock before running git. The core refuses `claim --force`,
  `release --force`, `done --force`, and normal `append` while a valid sentinel is present.
- **Integrate target / merge contract:** integration happens in `.m8shift/worktrees/_integration`,
  `--into` must name a local branch, foreign checked-out targets are refused before claiming, and
  merge failures abort the uncommitted merge before handing off with `blocked_on=<reason>:<id>`.
- **No-stuck-WORKING:** every non-crash post-claim path finalizes by clearing `integrating` and handing
  off via `--to`; already-applied retries are idempotent and finalize instead of double-merging.
- **Hygiene:** companion worktrees live under ignored `.m8shift/worktrees/`, ids and branch names are
  path-safe, and the companion makes no network calls.

Deterministic coverage lives in `tests/test_worktree.py` and `tests/test_m8shift.py::TestStage8Core`.

- **`--into` must be a local branch.** Integration *advances a branch*, so `--into` is validated as a
  local branch ref (`git show-ref --verify refs/heads/<into>`) **before claiming** — a commit / tag /
  detached ref is refused (it would merge into a detached HEAD and silently update no branch).
- **The integration target must not be checked out elsewhere.** Git forbids the same branch in two
  worktrees, so the dedicated `_integration` tree cannot own `--into` if the canonical root (or a
  feature worktree) has it checked out. `integrate` refuses **before claiming** (`git worktree list
  --porcelain`) with an actionable message. Run the canonical root **detached** (or on a coordination
  branch) so integration targets like `main` are free for the `_integration` tree.
- **Every post-claim path is non-stranding.** `finalize()` re-verifies *ours* (holder + state + exact
  sentinel + lock token); when the pen is ours it ALWAYS reaches the handoff (flip → `AWAITING_<to>`,
  clear the sentinel):
  - conflict / dirty-precondition / merge-error → `git merge --abort` (if `MERGE_HEAD`) + handoff with
    `blocked_on=conflict|merge-error:<id>`, exit non-zero.
  - integration HEAD moved out-of-band → abort + handoff with `blocked_on=head-moved:<id>` (no commit).
  - the final `git commit` fails (failing pre-commit hook / identity / signing — user hooks stay
    active, never `--no-verify`) → abort + handoff with `blocked_on=commit-error:<id>`; a hook failure
    can never leave the merge committed-but-unhanded or the pen stuck.
  - **resume-by-id**: a committed-but-unhanded retry matches the recorded sentinel by `<id>` (the
    recorded `<sha>` is the *pre-merge* target, which the committed merge has since moved past), then
    finalizes without re-merging — exactly one merge effect.
- **The one non-handoff exit is an externally changed/stolen pen** (`not ours`): only reachable by a
  manual LOCK edit (the sentinel makes `claim/release/done --force` and `append` refuse, so no
  legitimate command can take a WORKING+sentinel pen). It aborts our own uncommitted merge and refuses
  to touch the foreign LOCK — **no stolen merge** — surfacing it for human / `init --force` recovery.
- **`write()` failure mid-finalize** (disk full, …) is a documented hard crash; the atomic write means
  the on-disk LOCK is either fully flipped or unchanged, and the committed-but-unhanded **retry-finalize**
  recovers it. This is the only NO-STUCK-WORKING exception (a hard crash), as specified.
- **`done <id> <agent>`** appends to a companion-only ledger `.m8shift/done.log` **under the canonical
  file lock**, deliberately separate from the core's `M8SHIFT.tasks.md` — degree-2 worktree ids are a
  different id space from the core's integer task board, so the companion never collides with the dumb
  core ledger's format or lock.

Validated by a 7-lens adversarial sweep (merge-integrity / sentinel-lifecycle / no-stuck-WORKING /
lock-order-token / git-edge / crash-recovery / path-safety), each probing a throwaway git repo and
verified by reproduction; the merge-integrity, git-edge and path-safety lenses were clean, and the
finalize `die()` strand it surfaced is fixed (the above non-stranding handoff). Companion tests live in
`tests/test_worktree.py` (deterministic temp git repos).
