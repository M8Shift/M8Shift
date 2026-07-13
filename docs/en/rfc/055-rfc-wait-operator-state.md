# RFC 055 — Wait-on-operator holder state

- **Status:** draft / design only (co-design claude + codex)
- **Date:** 2026-07-13
- **Scope:** make "the holder is alive and holds the pen, but is blocked waiting on the
  human operator" an explicit, displayed condition — so the TTL stops driving false
  staleness while an agent is simply waiting for an operator answer.
- **Builds on:** [016-rfc-cooperative-turn-request.md](016-rfc-cooperative-turn-request.md),
  [021-rfc-pause-resume.md](021-rfc-pause-resume.md),
  [036-rfc-token-window-exhaustion.md](036-rfc-token-window-exhaustion.md),
  [049-rfc-holder-liveness-stale-claim-hardening.md](049-rfc-holder-liveness-stale-claim-hardening.md).

## 0. Proposal summary

Add a `wait: operator` marker to the `WORKING_<X>` state. While it is set:

1. the holder still owns the pen exclusively (it is mid-turn, not handing off);
2. the TTL alone does not make the lock stale — **liveness** (RFC 049 heartbeat) governs;
3. `status`/`watch`/`m8shift-top` show a distinct condition
   (`WAITING ON OPERATOR · held Nm · alive`) instead of a countdown-to-stale.

No new top-level state, no change to degree-1 pen authority, no auto-mutation.

## 1. Problem

`WORKING_<X>` conflates two opposite situations:

- **Actively computing** — the holder is making progress; the TTL is a fair liveness
  proxy (if it stops being renewed, the holder is probably dead).
- **Blocked on the operator** — the holder asked the human a question (an
  `AskUserQuestion`, a plan approval, a GO/no-GO) and is deliberately not progressing.
  Here the holder is **alive**; the human's latency is not agent death.

Observed live (2026-07-13): a holder sat at `WORKING_CLAUDE` with a ticking `expires`
while it was only waiting for an operator decision. Two failure modes follow:

- the display implies the pen is about to go **stale** when it is perfectly held;
- a peer that reads `now > expires` could **force-claim** an alive-but-waiting holder.

There is no state, and no display, for "held, alive, waiting on the human."

## 2. Non-goals

- No new top-level state (this is a marker on `WORKING_<X>`, not a sixth state).
- Not `PAUSED` — `PAUSED` releases the pen (holder = `none`); this keeps the pen.
- Not `AWAITING_<other>` — that is a peer agent's turn; this is the current holder
  blocked on the human.
- No auto-pause, no auto-extension of a session, no model/provider dependency.
- No change to how a genuinely dead holder is reclaimed (RFC 049 still applies).

## 3. Terminology

| Situation | State | Pen | Staleness driver |
|---|---|---|---|
| Holder computing | `WORKING_<X>` | held | TTL + liveness (RFC 049) |
| **Holder blocked on operator** | `WORKING_<X>` + `wait: operator` | **held** | **liveness only** (TTL frozen/advisory) |
| Peer's turn | `AWAITING_<other>` | handed | — |
| Parked, no task | `PAUSED` | none | — |

## 4. Signal and mechanism

### 4.1 Setting the marker

The holder declares it is blocking on the operator, e.g.:

```bash
python3 m8shift.py wait-operator claude --reason "GO/no-GO on the reconciliation strategy"
```

- Requires the caller to be the current holder (`WORKING_<caller>`).
- Records `wait: operator` and a short `reason` in the LOCK block.
- Clears automatically on the holder's next mutating action (`append`, `release`,
  `pause`, `done`) — i.e. when the operator's answer unblocks work.

### 4.2 TTL semantics while blocked

- The stored `expires` timestamp is left unchanged for compatibility and audit, but is
  rendered as **advisory** while `wait: operator` is set: it is not a countdown-to-stale.
- Staleness is decided by **liveness**, not the TTL: an alive-but-waiting holder keeps a
  fresh heartbeat (RFC 049), so it is not stale. A holder that also loses its heartbeat is
  stale by the normal RFC 049 rule and may be reclaimed.
- Force-claim of a `wait: operator` holder that is still **alive** requires the existing
  human-authorization gate (RFC 049), never TTL expiry alone.

### 4.3 Provenance guard (prompt-security)

`wait: operator` is set by an explicit holder command and cleared by the holder's own
next terminal turn action. It is **not** inferred or auto-set from relay/handoff/model
text (untrusted coordination data). The command is an actor-authorized mutation, not
proof that its reason came from the operator: a model can still invoke it after reading
untrusted text. Runtime integration may invoke it only from a first-party host event
that actually suspends execution for operator input; it must never classify free-form
text as such an event. An operator answer that unblocks the holder arrives through that
same host/operator channel, not by a peer asserting "the operator replied."

## 5. Display

`status` / `watch` / `m8shift-top` surface a distinct condition:

```text
PEN claude · WAITING ON OPERATOR · held 7m · alive
reason: GO/no-GO on the reconciliation strategy
```

- The TTL gauge shows `held · awaiting operator` instead of a shrinking bar.
- Show `held since <t>` (plus the unchanged expiry timestamp labelled `advisory` in
  verbose/JSON output); do not use `N-A` or present a frozen timestamp as a deadline.
- Honesty rule (as elsewhere): `alive` vs `stale` stays visible; the reason is shown when
  present, `—` when absent — never a fake countdown.
- The top dashboard treats `wait: operator` as its own PEN sub-state colour/badge, not the
  amber "about to expire" styling.

## 6. Interaction with existing RFCs

- **RFC 049** (holder liveness vs TTL): this RFC makes the TTL non-authoritative *only*
  while `wait: operator` is set; liveness/heartbeat remains the reclaim signal. It does not
  weaken reclaim of a dead holder.
- **RFC 021** (`PAUSED`): distinct — `PAUSED` is for an open session with no active task and
  releases the pen; `wait: operator` keeps the pen mid-turn.
- **RFC 016** (cooperative turn request / operator steering): a peer may still `request-turn`
  a `wait: operator` holder; the holder yields on its own terms, as today.
- **RFC 036** (headroom): unchanged; a holder can be both near-headroom and waiting.

## 7. Acceptance criteria

1. A holder can set `wait: operator` only while it holds the pen; a non-holder is refused.
2. While set, `expires` does not by itself mark the lock stale; `doctor`/`status` do not
   warn "stale" for an alive holder that is merely waiting.
3. A peer cannot force-claim an alive `wait: operator` holder on TTL expiry alone (still
   needs the RFC 049 human-authorization gate).
4. The marker clears on the holder's next `append`/`release`/`pause`/`done`.
5. `wait: operator` is never inferred from relay/model text — only a first-party command.
6. `status`/`watch`/`m8shift-top` render the distinct "WAITING ON OPERATOR · held Nm · alive"
   condition with the reason, not a countdown.
7. A genuinely dead holder (no heartbeat) is still reclaimable under RFC 049, marker or not.

## 8. Open decisions

1. **Dedicated command:** use `wait-operator`; do not overload `heartbeat`, whose
   protective producer semantics and cadence contract remain exactly RFC 049's.
2. **Explicit core mutation:** no inference from `AskUserQuestion`, plan, relay, or
   model text. A runtime companion may call the same command only from a typed,
   first-party host suspension event; that integration is a separate gated change.
3. **Display:** `held since <t>` in the primary display; preserve the original expiry
   timestamp as explicitly advisory in verbose/JSON output.
4. **Warning, not a cap:** surface a configurable/default informational warning after a
   long wait (initial default: one normal operator shift, 8h), but never reclaim or clear
   the marker based on elapsed wait alone. Liveness still decides claimability.

### 8.1 RFC 049 implementation constraint

The marker does not manufacture liveness. A waiting interactive process with no
protective producer remains unobservable, exactly as RFC 049 says. Therefore the core
must not treat the marker itself, its reason, an audit-only `claim --refresh` beat, or
elapsed operator-wait time as protective evidence. `wait-operator` should either be
paired with a real periodic `heartbeat` producer (runtime listener/wrapper), or status
must honestly render `liveness unknown`; a dead/no-heartbeat holder remains eligible
for RFC 049's guarded stale recovery. Heartbeat and refresh operations maintain the
marker; only `append`/`release`/`pause`/`done` clear it.

## 9. Decision requested

Approve the design direction (marker on `WORKING_<X>`, TTL non-authoritative while blocked,
distinct display) as a companion + core-LOCK change that extends RFC 049. Keep the
runtime-auto-set question (open decision 2) behind a separate gate.
