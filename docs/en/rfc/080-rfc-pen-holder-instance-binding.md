# RFC 080 — Binding the pen to a holder *instance*, not just a roster name

- **Status:** draft / design-only — no code until the open questions are settled
- **Date:** 2026-07-29
- **Issue:** #286
- **Scope:** core relay — `claim` / `append` / `release` / `done` and the LOCK
  schema — plus an advisory lint in `doctor`. Must stay minimal and
  backward-compatible.
- **Siblings:** [RFC 049](049-rfc-holder-liveness-stale-claim.md) (holder
  liveness / stale-claim hardening),
  [RFC 054](054-rfc-pre-exhaustion-session-rotation.md) (pre-exhaustion session
  rotation), [RFC 079](079-rfc-out-of-roster-observer.md)

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

### 1. An opt-in instance token in the environment

`$M8SHIFT_INSTANCE` — an opaque, non-secret string set once per agent session by
whatever launches the agent (harness, wrapper, runner, or the operator).

- **Set** → recorded in the LOCK at claim as `holder_instance:<token>`, and
  verified by every operation that requires the pen: claim refresh, `append`,
  `release`, `done`.
- **Unset** → behaviour byte-identical to today. This is what keeps the change
  backward-compatible and adoptable one agent at a time.

The token is **not** an authentication secret. Anyone able to write the LOCK can
write any token. It is a coordination aid, consistent with a core that detects
rather than enforces: it makes an accident visible, it does not stop an attacker.

### 2. Refusal that names the situation

A pen operation whose `$M8SHIFT_INSTANCE` differs from `holder_instance` is
refused with a message that says *what* happened rather than a generic denial —
the reader must not confuse it with a stale-lock case:

> the pen is held by a **different instance of the same agent**; this is not a
> stale lock and force-taking it would strand the other instance mid-task

### 3. Recovery must stay possible, and must be named

The legitimate recovery path — a process dies or exhausts its context, a fresh
one continues — is **exactly the same event** as an illegitimate concurrent
drive, seen from the lock. A design that refuses the second instance outright
would break the recovery it is meant to protect.

Therefore takeover stays available but stops being silent: an explicit
`claim <agent> --takeover-instance` (or reuse of the existing `--force`, to be
settled in §Open questions) records an **instance-change event** in the session
ledger, so the transition appears in `history` and `recap` instead of being
inferred later from commit timestamps.

### 4. Advisory detection for the unset case

Adoption is gradual, so most shifts will run with no token for a while. For those,
a `doctor --lint` check reports when a single session shows claims from
**different instance tokens or a mix of set and unset**, at severity *warn*. This
follows the companion doctrine: the core never blocks on it, the lint only names
what it sees.

## What this does not do

- It does not make the pen a security boundary. Same doctrine as the rest of the
  core: passive, cooperative, zero-credential.
- It does not detect two instances that share an environment (same exported
  token). That case is out of scope and should be named as such in the docs
  rather than half-covered.
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
