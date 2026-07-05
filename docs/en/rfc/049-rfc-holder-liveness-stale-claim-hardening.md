# RFC 049 — Holder liveness and stale-claim hardening

Status: draft  
Target: v3.53.0 candidate  
Related issue: #6  
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
  "source": "runtime-listener"
}
```

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

### `heartbeat <agent>`

```bash
python3 m8shift.py heartbeat codex
```

Semantics:

- allowed only while the relay lock is `WORKING_<agent>`;
- revalidates the lock under `file_lock()`;
- writes the holder heartbeat;
- does not extend `expires`;
- does not claim, append, release, or repair.

This command is primarily for wrappers/listeners, not a new manual burden for
interactive agents.

### `claim <agent> --refresh`

Existing TTL-refresh behavior remains. New behavior:

- after successful refresh, write a heartbeat with `source=claim-refresh`;
- if the heartbeat sidecar write fails, keep the TTL refresh but print/report a
  warning; the sidecar is not the source of pen authority.

`claim --refresh` is still the preferred heartbeat for long interactive turns
when the agent can call it before expiry. It does not solve the “forgot to call
anything” case.

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

## Doctor findings

Reuse the existing `lock.stale_working` condition rather than minting a parallel
dead-stale ID.

| Check | Severity | Meaning |
|-------|----------|---------|
| `lock.stale_working` | warning | existing stale lock finding; extended with liveness sub-state when available |
| `holder.heartbeat_malformed` | warning | heartbeat sidecar exists but is unreadable or invalid |
| `holder.ttl_expired_alive` | warning | pen TTL expired, but a matching heartbeat is fresh |
| `holder.heartbeat_orphaned` | info | heartbeat exists for no current matching `WORKING_*` lock |

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
- Heartbeat sidecars may remain after release/done; doctor reports orphaned
  records as info. A later cleanup command may prune them.

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
- `claim --refresh` writes heartbeat metadata after refreshing TTL and warns if
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

## Open questions for implementation review

- Freshness window: fixed 2 minutes, `2 * listener poll interval`, or explicit
  config?
- Should `--live-override` require a human-maintained marker file in addition to
  `--reason`?
- Should orphan heartbeat cleanup be automatic on `release`/`done`, or only a
  doctor/prune concern?
