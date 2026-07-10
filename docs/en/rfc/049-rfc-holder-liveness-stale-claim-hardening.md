# RFC 049 — Holder liveness and stale-claim hardening

Status: design rev 4 APPROVED / PR A + PR B implemented (2026-07-10 — protective-vs-audit heartbeat model exact [CLI --source/--cadence-seconds, claim-refresh audit-only], deterministic one-attempt phase-2 with three pinned refusal branches, pinned force+release-back audit sequence, editorial fixes)
Target: next minor after RFC 052
Related issues: #6, #104 (incident analysis + recurrences)
Owner: core relay + runtime/worktree companions

## Summary

M8Shift currently treats an expired `WORKING_<agent>` TTL as the only machine
signal that a holder may be gone. That is too coarse: a live headless runner can
miss the pen TTL while still executing, and a peer can then force-claim into the
same workstream.

This RFC adds a **holder heartbeat** as a second signal for managed/headless
lanes, and makes stale recovery honest:

- **managed lane with fresh heartbeat**: expired pen is not force-claimable by
  default;
- **unmanaged interactive lane with no fresh heartbeat**: the core cannot prove
  the holder is alive, so recovery remains a human/cooperative judgment, guarded
  by status/log checks and explicit override text.

The RFC does **not** claim to solve unobservable interactive long work by magic.
If an interactive holder runs one long synchronous command and emits no relay or
runtime signal, M8Shift has no reliable local liveness source. That incident is
handled by clearer stale guidance and the already-shipped pre-append/status
guards, not by pretending a heartbeat exists.

## Problem

Long operations such as full test suites, release builds, or cross-platform
installer checks can exceed the 30-minute pen TTL. If the holder misses
`claim --refresh`, peers see a stale lock and the current protocol core says
recovery is possible through `claim --force`.

There are two distinct cases:

| Case | Observable signal | Desired behavior |
|------|-------------------|------------------|
| Managed/headless holder still running | fresh holder heartbeat from listener/wrapper | refuse ordinary force-claim |
| Interactive holder in silent synchronous work | no fresh signal | do not invent liveness; require explicit caution/human judgment |

The first case can be improved mechanically. The second cannot be proven without
a producer; it must be documented as an operator/agent discipline boundary.

## Live incident evidence and amendments (forge #104, 2026-07-10)

Three same-session incidents turned this draft's problem statement into
recorded fact, and the recovery behavior the reviewer improvised is codified
here as the REQUIRED recovery contract.

**What happened (three times in one shift):** the holder's pen expired mid-work
during long implementation phases (multi-minute test suites; every wake-up
consumed by fix work), despite an adopted refresh-on-wakeup discipline. The
peer's listener flagged the stale lock; the operator had to relay the warning
by hand. The peer then performed two textbook recoveries (relay turns 425/426):
checked whether any commit had been pushed, found none, recovered the stale
lock, and RENEWED THE SAME ASSIGNMENT unchanged as a time-boxed checkpoint
handoff — the same scope stayed recoverable and was eventually resumed (no
checkpoint existed to lose or save). A session-side 15-minute refresh loop then stopped
the recurrence: that loop INSPIRED the productized liveness mechanism — but
only the `heartbeat` verb creates PROTECTIVE evidence; a refresh loop
prevents expiry without ever proving liveness after it.

**Amendments (each becomes normative below):**

- **A1 — refresh early, never at the deadline.** The refresh/heartbeat cadence
  targets ~TTL/2 (minute 15 of a 30-minute pen), not the expiry edge. Listener
  cadence stays `min(wait_interval, 60s)`; an interactive holder's guidance is
  "refresh on every wake-up". **A one-time refresh immediately before a long
  synchronous operation does NOT protect it**: an operation expected to exceed
  one TTL requires a CONCURRENT managed producer (listener heartbeat or an
  explicit refresh loop) — a pre-operation refresh alone still expires
  mid-command.
- **A2 — two-phase grace recovery (never hold the lock through the grace).**
  A naive lock-sleep-recheck would BLOCK the holder's own `claim --refresh`
  and guarantee the theft it exists to prevent. The shared `claim --force` /
  `next --force` flow is:
  1. **Phase 1**: acquire `file_lock()`, observe the stale candidate, capture
     the identity tuple `(session, turn, holder, state, expires)`, then
     **release the lock**;
  2. sleep the exact grace duration — direct `claim --force` uses a fixed
     **5s** constant; `next --force` uses its own interval clamped to
     **[5s, 60s]**;
  3. **Phase 2**: reacquire `file_lock()`, reload LOCK + heartbeat, require
     the identity tuple (EXACT comparison) to still identify the SAME work
     window AND the TTL to still be expired AND no fresh protective heartbeat;
  4. only then perform the force transition under that second lock.
  **Deterministic outcome — one attempt, never a silent loop**: both direct
  `claim --force` and `next --force` perform exactly ONE two-phase attempt; on
  a changed identity, a refreshed expiry, or a newly appeared protective
  heartbeat they refuse with a nonzero not-claimable rc and a next-action hint
  (three branches pinned separately by tests). `next` WITHOUT `--force` may
  resume its ordinary waiting behavior (documented); `next --once` never
  sleeps or retries beyond its single attempt. The grace sleep happens only
  AFTER phase 1 has released the lock.
  Concurrent reclaimers serialize on phase 2: after the first transition every
  other claimant sees a changed identity/non-stale state and refuses. This
  exact contention path is pinned by tests.
- **A3 — assignment-preserving recovery (minimal honest core).** The passive
  core knows nothing of branches, remotes, or assignment identity, and never
  inspects Git or the network. The mechanical contract is therefore:
  **recovery preserves the journal and the pending handoff byte-for-byte by
  construction**, via ONE pinned sequence:
  1. `claim <recoverer> --force --reason "stale recovery; renew same
     assignment"` — the stale recovery records a force session event carrying
     the prior holder, the captured identity tuple, and the reason;
  2. `release <recoverer> --to <prior-holder> --force --reason "resume pending
     turn; checkpoint before TTL"` — allowed even when the recoverer itself
     has an older pending incoming turn; an explicit `--force` release ALWAYS
     records a recovery-release session event;
  3. no append, no turn increment: journal and last-handoff bytes unchanged,
     LOCK becomes `AWAITING_<prior-holder>`. Reason text is sanitized before
     any LOCK-marker write (no unsanitized free text in markers). The
  behavioral half — "check for pushed/checkpointed progress before renewing;
  reference progress you find" — is agent/operator GUIDANCE delivered in the
  agent-pack, not core policy. Tests assert the journal/pending body is
  unchanged across repeated force/release cycles.
- **A4 — checkpoint discipline (guidance, not enforcement).** Long work
  commits/pushes or records an explicit progress note before the TTL, or
  refreshes around minute 15. Delivered as agent-pack/stanza text within the
  existing byte budget.
- **A5 — observable liveness state (no UI resumption implied).** RFC 035
  already establishes that a terminal wait cannot wake an interactive UI, and
  nothing here auto-resumes one. Instead the READ-ONLY surfaces expose one
  liveness sub-state — `fresh`, `alive-expired`, `ordinary-stale`, or
  `orphaned/invalid` — in human and JSON `status`, plus heartbeat age, source,
  and declared cadence (bounded, redacted per RFC 052 §9.5). `wait`/listener
  report ready/stale accurately from that same state. The test asserts
  relay/listener/status STATE, never foregrounding.
- **A6 — no automatic double-holder.** No recovery path may ever produce two
  `WORKING_*` holders: the A2 grace recheck plus under-lock validation keep the
  single-pen invariant, and the race is pinned by tests.

## Goals

- Preserve the exclusive one-pen model.
- Keep stale recovery available when the holder is actually gone.
- Add an observable liveness signal for managed/headless work.
- Make `wait`, `next`, and `claim --force` distinguish “expired but heartbeat
  fresh” from ordinary stale recovery.
- Keep the core local and stdlib-only.
- Avoid one-condition-two-ID diagnostics.
- Make worktree ownership advisory and honest: companion verbs can guard
  themselves, but direct shell/editor writes are outside M8Shift's control.

## Non-goals

- No network daemon, service, or hosted control plane.
- No OS-level process identity proof.
- No filesystem-wide write lock or shell sandbox.
- No claim that M8Shift can detect an interactive agent that emits no heartbeat
  while running a long command.
- No autonomous peer interruption.

## Liveness model

### Terms

- **Pen TTL**: `expires` in `WORKING_<agent>`.
- **Stale pen**: `now > expires`.
- **Holder heartbeat**: local sidecar written by the holder lane while work is
  ongoing.
- **Fresh heartbeat**: heartbeat matching the current `agent`, `session`, `turn`,
  and `state`, with `written_at` within the configured freshness window.
- **Alive-expired**: stale pen plus fresh matching heartbeat.
- **Ordinary stale**: stale pen with no fresh matching heartbeat.

### Producer honesty

Heartbeat freshness is meaningful only when a producer is actually running after
the pen was acquired:

- runtime listener / headless wrapper: valid producer;
- an explicit `heartbeat <agent>` called by a wrapper: valid producer;
- `claim --refresh`: useful for audit and for refreshed TTL windows, but a beat
  written only at claim/refresh time is **not** enough by itself to prove
  liveness after that refreshed TTL later expires;
- no producer: no liveness proof.

This is the load-bearing correction: RFC 049 is a managed-lane liveness hardening
RFC, not a proof that silent interactive work is alive.

## Core sidecar

Add:

```text
.m8shift/holder-heartbeats/<agent>.json
```

Schema:

```json
{
  "schema": "m8shift.holder_heartbeat.v1",
  "agent": "claude",
  "session": "20260705T093732Z-...",
  "turn": 323,
  "state": "WORKING_CLAUDE",
  "written_at": "2026-07-05T10:00:00Z",
  "source": "runtime-listener",
  "protective": true,
  "cadence_seconds": 60
}
```

Audit beats (`source=claim-refresh`) carry `"protective": false` and
`"cadence_seconds": null`.

Rules:

- heartbeat writes are atomic replace;
- reads and writes that influence claimability happen under the existing
  `file_lock()` discipline;
- a heartbeat is considered only when it matches the current lock's agent,
  session, turn, and state;
- malformed or non-matching heartbeats are ignored for force-claim protection and
  reported by doctor;
- heartbeat files are coordination data, not a security boundary.

## Commands

### `heartbeat <agent>` (the ONLY protective producer surface)

```bash
python3 m8shift.py heartbeat codex --source runtime-listener --cadence-seconds 60
```

Semantics:

- allowed only while the relay lock is `WORKING_<agent>`;
- an actor-bearing mutator: passes the RFC 052 binding gate and revalidates the
  lock under `file_lock()`;
- `--source` is a closed enum (`runtime-listener` | `wrapper`) and
  `--cadence-seconds N` is REQUIRED, validated to `1..TTL_SECONDS`
  (`TTL_SECONDS = TTL_MIN * 60`) BEFORE any write;
- writes the holder heartbeat with `protective=true` and the declared cadence;
- does not extend `expires`; does not claim, append, release, or repair;
- runtime/headless producers call THIS VERB — they never write the sidecar
  directly (RFC 052 binding + file_lock semantics preserved).

**Protective vs audit beats (exact model):**

- protective window = `max(120, min(2 * cadence_seconds, TTL_SECONDS))`,
  evaluated against the beat's age;
- `claim --refresh` writes an AUDIT record only: `source=claim-refresh`,
  `protective=false`, `cadence_seconds=null` — it is NEVER considered by force
  protection after expiry;
- a periodic **heartbeat-verb loop** is protective (each beat declares its
  cadence); a periodic **refresh loop** prevents expiry by extending the TTL
  but its audit rows never become protective proof;
- only protective beats require a cadence; audit beats carry `null`.

This command is primarily for wrappers/listeners, not a new manual burden for
interactive agents.

### `claim <agent> --refresh`

Existing TTL-refresh behavior remains. New behavior:

- after successful refresh, write an AUDIT heartbeat (`source=claim-refresh`,
  `protective=false`, `cadence_seconds=null`) — never force protection;
- if the heartbeat sidecar write fails, keep the TTL refresh but print/report a
  warning; the sidecar is not the source of pen authority.

`claim --refresh` is still the preferred TTL-extension for long interactive
turns when the agent can call it before expiry — but its beat is audit-only:
protective evidence comes exclusively from the `heartbeat` verb. It does not
solve the “forgot to call anything” case.

### `claim <agent> --force`

Force flow:

1. acquire `file_lock()`;
2. validate the relay lock;
3. refuse if peer `WORKING_*` TTL is still valid, as today;
4. if stale, read the matching heartbeat under the same lock;
5. if heartbeat is fresh, refuse ordinary force-claim;
6. if heartbeat is absent, stale, invalid, or non-matching, follow the existing
   stale recovery path.

Optional live-holder override:

```bash
python3 m8shift.py claim codex --force --live-override --reason "human approved recovery"
```

Rules:

- accepted only with `--force` and `--reason`;
- records that a fresh heartbeat was overridden;
- should be used only with explicit human authorization.

The CLI cannot cryptographically prove that a human wrote the reason. This is an
audited cooperative control, not a security boundary.

## `wait` / `next` behavior

When peer `WORKING_*` TTL expires:

- alive-expired: keep waiting and print that the holder appears alive;
- ordinary stale: keep the existing stale-recovery path, but wording should be
  cautious: stale TTL is not proof of death; inspect status/logs or obtain human
  authorization before force-claiming shared work.

`next` inherits the same claimability rules.

## Protocol core budget

Implementation must update the compact protocol core. The current stale-lock
stanza that says “if `WORKING_<other>` and expired, take it with
`claim --force`” becomes conditionally false once this RFC ships.

Budget requirement:

- add one compact line to the core: “expired peer locks may be protected by a
  fresh holder heartbeat; `claim --force` may refuse; stale TTL is not proof the
  peer is gone”;
- trim equivalent detail from the stale-lock paragraph and move detail to the
  protocol reference;
- preserve the existing 2000 proxy-token ceiling and safety-invariant tests.

No implementation should merge without an updated core-budget test.

## Runtime companion integration

`m8shift-runtime.py listener` should emit heartbeats while a child runner is
alive. Recommended cadence:

- heartbeat every `min(wait_interval, 60s)` during a running child turn;
- `claim --refresh` before TTL expiry when the listener owns the holder turn and
  policy allows extension.

Runtime still delegates all pen authority to `m8shift.py`.

## Worktree ownership sidecar

Ownership metadata must live **outside** the peer worktree checkout:

```text
.m8shift/worktree-owners/<id>.json
```

Example:

```json
{
  "schema": "m8shift.worktree_owner.v1",
  "id": "fix-foo",
  "agent": "codex",
  "created_at": "2026-07-05T10:00:00Z",
  "path": ".m8shift/worktrees/fix-foo",
  "branch": "m8shift/fix-foo-codex"
}
```

`m8shift-worktree.py` can refuse its own mutating verbs when another owner is
recorded, unless `--takeover --reason` is explicit. This is an **advisory
companion guardrail**: direct `git`, editor, or filesystem writes do not pass
through the companion and cannot be refused by M8Shift.

## RFC 052 integration (session binding — shipped)

`heartbeat <agent>` and every heartbeat/owner-sidecar mutation are M8Shift-owned
mutators and MUST pass the shipped RFC 038 §9.2 gate:

- `heartbeat` is an **actor-bearing mutator**: dispatch-level A1/A3 binding gate
  plus the under-lock recheck, exactly like `claim`/`append`;
- runtime/worktree heartbeat producers write through the **preflight-resolved
  bound root** or fail closed under two-candidate ambiguity — a leftover
  `M8SHIFT_ROOT` must never place a heartbeat in one project to protect another
  project's pen (two-relay tests required);
- every liveness/status/doctor surface follows the RFC 052 §9.5 disclosure rule
  (no raw candidate path; bounded redacted labels).

## Doctor findings

Reuse the existing `lock.stale_working` condition rather than minting a parallel
dead-stale ID.

| Check | Severity | Meaning |
|-------|----------|---------|
| `lock.stale_working` | warning | THE canonical expired-lock finding, carrying a structured `liveness` sub-state (`alive-expired` / `ordinary-stale`) — one condition, one ID, never two warnings for one expired lock |
| `holder.heartbeat_malformed` | warning | heartbeat sidecar exists but is unreadable/invalid/out-of-range (sidecar-specific condition) |
| `holder.heartbeat_orphaned` | info | heartbeat exists for no current matching `WORKING_*` lock (sidecar-specific condition) |

Worktree companion doctor findings:

| Check | Severity | Meaning |
|-------|----------|---------|
| `worktree.owner_missing` | warning | managed worktree lacks sidecar ownership metadata |
| `worktree.owner_mismatch` | warning | sidecar metadata conflicts with known path/branch/owner |

## Backward compatibility

- Existing relays without heartbeat sidecars behave as they do today.
- A stale TTL with no fresh heartbeat remains recoverable.
- Pre-RFC-049 peers ignore heartbeat files and may force-claim through them; this
  must be called out in generated/reference docs during mixed-version operation.
- Cleanup of heartbeat sidecars is ATTEMPTED on `release`/`done` (best-effort,
  errors suppressed — the sidecar is never authority); a failed cleanup leaves
  an orphan that doctor reports as info.

## Security and prompt boundaries

- Heartbeats are local cooperative signals, not authenticated process identity.
- Any local process with filesystem access can try to write sidecars; matching
  session/turn/state checks reduce accidents but do not create a security
  boundary.
- Heartbeats cannot authorize destructive git operations.
- Malformed heartbeats do not protect stale locks; they generate diagnostics.
- Live override is an exceptional operator recovery path.

## Acceptance criteria

- `heartbeat <agent>` writes a matching sidecar only for current
  `WORKING_<agent>`.
- `claim --refresh` writes AUDIT-ONLY beat metadata (protective=false, null cadence) after refreshing TTL and warns if
  the sidecar write fails.
- `claim --force` refuses stale peer locks with fresh matching heartbeat.
- `claim --force --live-override --reason ...` succeeds and audits the override.
- `wait` / `next` distinguish alive-expired from ordinary stale states.
- `doctor --json` extends `lock.stale_working` and emits the exact holder
  findings listed above.
- Protocol core budget remains under 2000 proxy tokens after the stale-lock
  wording update.
- `m8shift-worktree.py` stores owner metadata outside the checkout and frames
  cross-owner protection as advisory companion enforcement only.
- Tests cover malformed, stale, orphaned, fresh, wrong-session, wrong-turn, and
  mixed-version/no-heartbeat behavior.
- **Incident-derived test families (A1-A6)**:
  - refresh-vs-reclaim race: the TWO-PHASE flow (observe+capture identity ->
    release -> grace -> reacquire+revalidate) never steals a lock refreshed
    during the grace, and never blocks the holder's own refresh during it;
  - repeated stale windows: two consecutive force+`release --to <prior holder>`
    recovery cycles leave the journal and pending handoff body byte-for-byte
    unchanged AND the turn number unmodified, with TWO audit events per cycle
    (force reclaim + recovery release), a recoverer holding an older pending
    incoming turn still allowed to release-back, and no unsanitized free text
    reaching LOCK markers;
  - protective-vs-audit heartbeats: a periodic producer's beat (declared
    cadence) protects within `clamp(2*cadence, 120s, TTL)`; a one-shot
    `claim-refresh` beat does NOT protect after expiry; malformed cadence fails
    open and is diagnosed;
  - observable state: human/JSON `status` expose the single liveness sub-state
    and bounded redacted heartbeat metadata; the assertion targets state, not
    UI foregrounding;
  - no-double-holder: concurrent phase-2 recovery attempts under contention
    never yield two `WORKING_*` states (first transition wins, others refuse);
  - RFC 052 two-relay: `heartbeat` refuses under unresolved ambiguity; a bound
    producer writes only the bound root's sidecar.
- `heartbeat` is classified in the RFC 052 mutator matrix (actor-bearing) and
  covered by the matrix meta-test; the protocol core stays under its byte
  budget after the wording update; mixed-version behavior (peer without RFC
  049) is documented and tested; the agent-pack carries the A1/A4 guidance.
- **Delivery is staged in three reviewable PRs**: PR A core (heartbeat verb,
  two-phase force, wait/status/doctor, protocol wording — protective beats are
  testable in PR A through the manual heartbeat verb, before PR B ships the
  managed producer); PR B runtime/headless producer + early-refresh cadence;
  PR C worktree ownership sidecar/guard.

## Resolved questions (rev 4, informed by the live incidents)

- **Freshness window (cadence-declared)**: every heartbeat DECLARES its
  producer's real cadence in a bounded `cadence_seconds` field; protective
  freshness = `age <= clamp(2 * cadence_seconds, floor=120s, ceiling=TTL)`.
  A one-shot `claim --refresh` heartbeat is **audit-only and non-protective
  after TTL expiry** — protection comes ONLY from periodic HEARTBEAT-VERB
  producers (listener, wrapper), each beat declaring the loop cadence; a
  refresh loop merely prevents expiry by extending the TTL.
  Malformed or out-of-range cadence **fails open for claimability** and is
  diagnosed (`holder.heartbeat_malformed`). Fixed formula, no config knob.
- **`--live-override`**: `--force --live-override --reason` suffices — the
  override is audited in session events; a human marker file adds ceremony
  without proof (the CLI cannot authenticate a human either way).
- **Orphan heartbeat cleanup**: best-effort removal on `release`/`done`
  (suppressed errors — the sidecar is never authority), plus the existing
  doctor info finding; no separate prune command in this RFC.
