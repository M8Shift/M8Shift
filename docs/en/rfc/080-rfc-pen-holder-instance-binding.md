# RFC 080 — Binding the pen to a holder *instance*, not just a roster name

- **Status:** draft / design-only — no code until the open questions are settled
- **Date:** 2026-07-29
- **Issue:** #286
- **Scope:** core relay — `claim` / `append` / `release` / `done` and the LOCK
  schema — plus an advisory lint in `doctor`. Must stay minimal and
  backward-compatible.
- **Amends:** [RFC 010](010-rfc-runtime-patterns.md) §4 — see §3.1, which states
  what is amended and what stays binding
- **Siblings:** [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md) (holder
  liveness / stale-claim hardening — this RFC defers to it rather than defining a
  parallel takeover model),
  [RFC 054](054-rfc-pre-exhaustion-session-rotation.md) (pre-exhaustion session
  rotation), [RFC 079](079-rfc-out-of-roster-observer.md),
  [RFC 078](078-rfc-freshness-first-class.md) (unverifiable values must not be
  presented as verified)

## Summary

The mutex authenticates a pen holder **by roster name**. Two concurrent processes
acting as the same roster agent are indistinguishable to the lock: the second one
to call `claim <name>` simply takes or refreshes the pen the first believes it
holds, and nothing anywhere reports it.

This is not hypothetical. It was observed twice in one working day on a live
shift. In both cases an agent process reached its context limit, the operator
started a fresh process for the same roster name to keep working, and for a
while **both** drove the relay. Consequences seen:

- production commits landed in project repositories **outside the work window**
  of the process that believed it held the pen;
- the peer agent reviewed a repository state whose author it could not identify,
  and had to ask the question explicitly in a turn;
- the human saw two agents answering under one name, with no signal from the
  tool that this was happening.

The relay stayed *internally consistent* the whole time. That is the problem: a
silent double-drive is indistinguishable from an orderly one.

## Why the existing pieces do not cover it

**`work_window_id` is not an ownership credential.** A fresh id is minted at each
claim and recorded in the session ledger, which makes the history auditable
*after the fact*, but any process passing the same roster name obtains one. It
identifies a work window, not who opened it.

**Stale-claim handling solves a different problem.** RFC 049 hardening answers
*"the holder is gone, may I take over?"*. Here the holder is **not** gone — it is
alive, mid-task, and about to write. TTL expiry is the wrong signal.

**The `M8SHIFT_AGENT` / `M8SHIFT_ROOT` pen guard is the right shape but the wrong
granularity.** It already keys pen legitimacy on the environment, which is the
precedent this RFC extends; it just cannot separate two environments claiming the
same name.

## The constraint that shapes the design

**Every CLI command is a new operating-system process.** `claim`, `append` and
`release` do not share a process, so anything derived from pid, process start
time or in-memory state is unusable as an instance identity. Whatever identifies
an "instance" must live *outside* the process and be stable across the commands
of one agent session.

This rules out the obvious answers before they are proposed:

| Candidate | Why it fails |
|---|---|
| pid / process start time | new process per command |
| controlling terminal (tty) | absent in headless, CI and runner contexts |
| a daemon holding session state | against the passive-core doctrine |
| lock file descriptor held open | requires a long-lived process; same objection |

## Proposal

### 1. An opt-in instance token, and its lifecycle

`$M8SHIFT_INSTANCE` — an opaque, non-secret string identifying one agent session.

- **Set** → recorded in the LOCK at claim as `holder_instance:<token>`, and
  compared by every operation that requires the pen: claim refresh, `append`,
  `release`, `done`.
- **Unset** → behaviour byte-identical to today. This is what keeps the change
  backward-compatible and adoptable one agent at a time.

The token is **not** an authentication secret. Anyone able to write the LOCK can
write any token. It is a coordination aid, consistent with a core that detects
rather than enforces: it makes an accident visible, it does not stop an attacker.

#### Who mints it, and why the environment alone is not enough

An earlier draft said only "set once per agent session by whatever launches the
agent". That is not a lifecycle, and review established that it fails on the very
case this RFC exists for: **an exported variable is inherited, not minted.** Two
sessions started from the same wrapper, or a fresh session started in a shell that
already exports the value, share one token — which is precisely the silent
double-drive the design is meant to expose. Stating that case out of scope, as the
earlier draft did, would have left the motivating incident uncovered while the RFC
claimed to address it.

So the lifecycle has to be specified per mode, and the guarantee differs by mode:

| Stage | **Managed** (runner or launcher starts the agent) | **Manual** (operator or interactive session) |
| --- | --- | --- |
| Created | by the launcher, per invocation | by the operator, per session |
| Value | the run id the runtime already mints — not a parallel concept | any opaque string |
| Rotated | necessarily, since a new invocation is a new run | only if the operator rotates it |
| Cleared | when the invocation ends | never automatically |
| Freshness | **guaranteed** by the launcher | **not guaranteed** |

The managed row is what makes the motivating case work: a context rotation starts
a *new invocation*, so it necessarily receives a new id, without anyone having to
remember anything. The guarantee comes from the launcher minting per invocation,
never from the environment variable mechanism, which cannot provide it.

#### What honest degradation looks like

Where freshness cannot be guaranteed — manual mode, or an inherited value — the
core MUST NOT behave as though it could. Two instances sharing a token are
indistinguishable to the LOCK, and the design says so rather than half-covering
it:

- the comparison still catches every case where the tokens **differ**, which is
  the common accident;
- it catches nothing where they are **equal but the sessions are not**, and no
  amount of core logic recovers that — the information does not reach the LOCK;
- therefore `doctor --lint` reports a token that appears across sessions whose
  boundaries the runtime *can* see (§4), and the docs state the residual gap
  plainly instead of implying coverage.

This is the same discipline as [RFC 078](078-rfc-freshness-first-class.md): a
value that cannot be verified must not be presented as though it had been.

### 2. Refusal that names the situation

A pen operation whose `$M8SHIFT_INSTANCE` differs from `holder_instance` is
refused with a message that says *what* happened rather than a generic denial —
the reader must not confuse it with a stale-lock case:

> the pen is held by a **different instance of the same agent**; this is not a
> stale lock and force-taking it would strand the other instance mid-task

### 3. Recovery must stay possible, and the two recoveries are not the same

The legitimate recovery path — a process dies or exhausts its context, a fresh
one continues — is **exactly the same event** as an illegitimate concurrent
drive, seen from the lock. A design that refuses the second instance outright
would break the recovery it is meant to protect.

But "seen from the lock" is the whole qualifier, and review was right that the
earlier draft collapsed two situations the system can in fact tell apart:

**Managed recovery — the old instance's liveness is observable.** When the prior
holder ran behind a runtime lane, its liveness is already answerable by the
mechanism [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md) defines,
and the accounting fold already consumes: a protective heartbeat inside the
window. If that beat is **fresh**, the old instance is alive and this is not a
recovery at all — ordinary takeover is refused, exactly as RFC 049 refuses a
force-claim against a live holder. If it is **absent or expired**, the takeover is
routine and needs no ceremony beyond recording the instance change.

**Unmanaged recovery — nothing distinguishes the two.** An interactive session
behind no lane leaves no liveness signal, so the core genuinely cannot tell
recovery from concurrent drive. Here the answer is not a smarter rule but an
honest one: the operation is refused with the message in §2, and proceeding
requires the **explicit audited override RFC 049 already defines** rather than a
second, parallel takeover verb invented here.

Either way the transition stops being silent: an **instance-change event** is
recorded in the session ledger, so it appears in `history` and `recap` instead of
being inferred later from commit timestamps.

This is deliberately *not* a new takeover model. Where RFC 049 has an answer, this
RFC defers to it and adds only the field that says which instance held the pen.

### 3.1 Relationship to RFC 010 §4 — an amendment, stated as one

[RFC 010](010-rfc-runtime-patterns.md) §4 ("Per-agent queue / lane") already
assigns this exact problem — *"the core identifies agents by roster name, not by
UI instance. Two Codex sessions can both treat `claim codex` as a refresh"* — to
the runtime companion, and draws a boundary: instance-level safety *"must not
change the core identity model, grant the pen, or steal a fresh lane."*

Recording `holder_instance` in the LOCK touches that boundary, and this RFC must
say so rather than quietly cross it.

**What is amended:** the boundary was written when the lane owner was the only
instance-safety mechanism available. A lane covers *managed* runtimes only. The
field observations behind this RFC came from sessions behind no lane, which the
companion cannot see at all — so the boundary as written leaves the motivating
case permanently uncovered, not by choice but by construction.

**What is preserved, and should be read as binding:** the token still does not
grant the pen, still does not steal a fresh lane, and still does not authenticate
anyone. Ordering and routing are untouched. What changes is narrower than "the
core identity model": the core records **who claims to hold** the pen alongside
**which roster name** holds it, and compares the two on pen operations. Agent
identity for every other purpose — turn order, roles, delegation — remains the
roster name alone.

If reviewers judge that even this crosses RFC 010 §4, the alternative is explicit
and should be chosen consciously: keep the field in the companion, and accept that
unmanaged sessions stay uncovered. This RFC argues against that, but the choice
belongs in the open, not in an unremarked contradiction between two documents.

### 4. Advisory detection for the unset case

Adoption is gradual, so most shifts will run with no token for a while. For those,
a `doctor --lint` check reports when a single session shows claims from
**different instance tokens or a mix of set and unset**, at severity *warn*. This
follows the companion doctrine: the core never blocks on it, the lint only names
what it sees.

## What this does not do

- It does not make the pen a security boundary. Same doctrine as the rest of the
  core: passive, cooperative, zero-credential.
- It does not detect two instances that share an identical token. This is a
  **residual gap, not an out-of-scope declaration** — the earlier wording deferred
  it, which would have left the motivating case uncovered while the document
  claimed to address it. §1 closes it for managed sessions, where the launcher
  mints per invocation; for manual sessions it stays open, and the docs must say
  so plainly rather than imply coverage.
- It does not touch routing. `holder_instance` is a field of the LOCK, read by
  pen operations only; it must never influence which agent is next.

## Open questions

1. **Reuse `--force` or add `--takeover-instance`?** Reuse keeps the surface
   small but overloads a flag whose current meaning is "the holder is stale".
   A distinct flag is clearer and lets `--force` keep refusing a live holder.
2. **Who sets the token?** A wrapper is the natural place, but a shift driven by
   hand would then never get the guard. A `claim --new-instance` that mints and
   prints a token for the caller to export is one answer.
3. **Should `status` display it?** Showing a token adds noise for the common
   single-instance case; hiding it makes the refusal message harder to diagnose.
   Possibly `status --brief` hides it and full `status` shows a short prefix.
4. **Interaction with RFC 054.** Pre-exhaustion rotation is the *planned* version
   of the event that motivated this RFC. If a rotation hands over deliberately,
   it should carry the instance change explicitly rather than trip the guard.

## Field note

The two occurrences that motivated this RFC were both **recoveries, not
mistakes**: an agent hit its context limit and work continued in a fresh session,
which is the correct thing to do. The defect is not that two instances existed —
it is that the relay had no way to say so. A tool whose whole purpose is to make
"who holds the pen" unambiguous should not be silent about the one case where the
answer is genuinely ambiguous.

## Provenance of this design

The two occurrences in the field note were observed on another shift, and this
draft was written there and deliberately abstracted — no project, repository,
ticket or subject-matter identity — so it could be adopted as-is. Verified here
against the confidential denylist with the raw fixed-string scan before adoption:
zero matches, and the scan itself validated on a known positive first, because a
zero from an unvalidated instrument is not evidence.

Two corrections were applied on adoption, both invisible from the checkout it was
drafted in: the number (054 was already taken on `main` by the pre-exhaustion
rotation RFC) and the cross-reference in open question 4, which pointed at that
same document under its older number.
