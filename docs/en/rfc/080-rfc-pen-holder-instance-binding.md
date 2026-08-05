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
  liveness / stale-claim hardening — adjacent but *not* covering this case; see the
  correction in §3, which is why a distinct operation is defined here),
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
| --- | --- |
| pid / process start time | new process per command |
| controlling terminal (tty) | absent in headless, CI and runner contexts |
| a daemon holding session state | against the passive-core doctrine |
| lock file descriptor held open | requires a long-lived process; same objection |

## Proposal

### 1. An opt-in instance token, and its lifecycle

`$M8SHIFT_INSTANCE` — an opaque, non-secret string identifying one agent session.

**Grammar, because this value lands in a one-line LOCK field and on display
surfaces.** It reuses the run-id grammar the runtime already enforces rather than
inventing a second one: 1–128 characters, from the safe set that grammar already
defines, no whitespace and no newline. A value that does not conform is rejected at
`claim` with a message naming the constraint — never silently truncated, since a
truncated token would compare unequal to itself and manufacture the very mismatch
this RFC exists to detect.

**Display, and why the obvious truncation is wrong.** An earlier revision showed
the first 8 characters on human surfaces. Review measured what that produces
against the managed grammar, which is `YYYYMMDDTHHMMSSZ-<agent>-<uuid8>`: the first
8 characters are `YYYYMMDD`, so **every managed invocation on the same day renders
identically** — verified on three real run ids, two of which collapsed to the same
display. The core would still compare the full value, but the human evidence would
be misleading at exactly the recovery moment where an operator has to tell two
invocations apart.

Human surfaces therefore show a **short digest** — the first 8 hex characters of
the SHA-256 of the whole token, rendered as `inst:3f9a1c02`. It is independent of
any token grammar, so it stays correct if the managed format changes or a manual
token is used, and equal tokens always render equally. Its collision resistance is
stated rather than assumed: 32 bits, so distinct instances collide with meaningful
probability only in the tens of thousands, far above the scale of one relay
session. Machine surfaces carry the token whole.

- **Set** → recorded in the LOCK at claim as `holder_instance:<token>`, together
  with `holder_mode` (see the classifier under §3), and compared by every
  operation that requires the pen: claim refresh, `append`, `release`, `done`.
- **Unset on both sides** → behaviour byte-identical to today. This is what keeps
  the change backward-compatible and adoptable one agent at a time. Note the
  qualifier: it holds when *neither* the caller nor the LOCK carries a token. The
  mixed state is a real behavioural change and is specified in §3, not glossed
  here.

The token is **not** an authentication secret. Anyone able to write the LOCK can
write any token, so it stops an accident and not an attacker.

An earlier revision described this as "a core that detects rather than enforces".
That is no longer accurate and should not be left standing: §3 **does** enforce —
a mismatch refuses the operation. The honest distinction is not detection versus
enforcement but *cooperative* enforcement versus *authentication*: the guard binds
participants who pass their own token honestly, and offers nothing against a
writer who chooses to forge one. Every other guard in this core has the same
shape.

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
| Value | the run id the runtime already mints — not a parallel concept | any token conforming to the grammar above |
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

#### A correction: RFC 049 does not cover this, and a previous revision said it did

A previous revision of this section claimed the unmanaged case could defer to "the
explicit audited override RFC 049 already defines", and that this RFC therefore
introduced no new takeover model. **That was false**, and it was asserted without
checking — the same failure this project names everywhere else. Verified against
both documents before rewriting:

- [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md) §`claim --force`
  step 3 is verbatim *"refuse if peer `WORKING_*` TTL is still valid, as today"*,
  and the heartbeat is read only at step 4, *"if stale"*. Liveness is therefore
  consulted **after** staleness, never instead of it — and the subject is a
  **peer**, a different roster name, not another instance of the same one.
- The shipped `claim` never reaches that guard for our case at all. It computes
  `mine = st in ("IDLE", f"AWAITING_{agent.upper()}", f"WORKING_{agent.upper()}")` and gates the
  whole force-recovery block on `not mine`. A claim under the **same roster name**
  against `WORKING_<same agent>` is treated as the holder refreshing its own work
  window, so no override, no audit event, and no liveness check occurs.
- `--live-override` consequently audits *a different holder being displaced*. It
  neither defines nor records a same-agent, different-instance takeover.

So there is no existing contract to defer to. This RFC must define the operation,
and it now does — which also settles the contradiction the reviewer found between
§3's "no second verb" and open question 1: **there is a second operation**,
because none exists today.

#### `claim <agent> --takeover-instance --reason <text>`

A distinct, audited operation. It is not `--force`: `--force` answers *the holder
is gone*, this answers *the holder may be a different me*. Conflating them would
make the audit record unable to say which question was answered.

It requires `--reason`, records an **instance-change event** in the session ledger
so the transition appears in `history` and `recap` rather than being inferred from
commit timestamps later, and is refused outright where the table below says
`refuse`.

#### The decision table

**Domain.** The table is read against a `WORKING_<agent>` lock, for a caller using
the same roster name. Every column below is therefore a property of that lock;
nothing outside `WORKING_<agent>` appears in it. Adoption from `AWAITING_<agent>`
or `IDLE` is specified in prose after the table, because a fresh work window has
no lease, no beat and no holder to displace — putting it in a lease column, as an
earlier revision did, broke both the domain and the schema.

**Columns.** `Identity` compares the caller's `$M8SHIFT_INSTANCE` with the LOCK's
`holder_instance`, over four values: `match`, `mismatch`, `caller unidentified`
(caller unset, LOCK set) and `holder unidentified` (caller set, LOCK unset).
`Beat` is read from the heartbeat sidecar and has exactly two values: `fresh`, or
`stale or missing`. An earlier revision carried a third, `unobservable`, meant for
*no producer exists to read*; it was removed because it let missing **metadata**
erase a **present** observation. Whether a producer was expected is now `Mode`'s
business alone, and it never rewrites what the sidecar says.

#### Where `Mode` comes from, since it decides who owns the pen

`Mode` is authority-bearing, on exactly one question: whether a **missing** beat
under an expired lease may be read as *a declared producer failed to deliver*,
which permits automatic takeover, rather than as *nothing was ever watching*, which
demands an audited operator decision. An earlier revision used the column without
saying how the core obtains it, which left the table unevaluable — combinatorially
complete but operationally undefined.

It cannot be inferred from the heartbeat, and this is the crux: `read_heartbeat`
returns a missing file as `absent`, and a missing file cannot distinguish an
unmanaged holder from a managed holder whose producer never started, crashed, or
lost its sidecar. Inferring mode from the very signal whose meaning depends on the
mode is circular.

So the mode is **declared at claim and recorded with the work window**, beside
`holder_instance`, as `holder_mode`. An earlier revision stopped there, naming
actors — "the launcher", "the operator" — rather than a command boundary, which
left the column unimplementable. The contract in full:

**Input.** `$M8SHIFT_INSTANCE_MODE`, read at `claim` from the same environment as
`$M8SHIFT_INSTANCE`, so one launcher sets both or neither. Accepted values are
exactly `managed` and `manual`, compared case-sensitively. No flag, no config file,
no other source — a second source would reintroduce the ambiguity this section
exists to remove.

**Persisted domain.** `holder_mode` stores `managed`, `manual`, or `unknown`.

| Input at claim | Persisted | Why |
| --- | --- | --- |
| `managed`, with a token set | `managed` | a producer is expected to emit protective beats for this window |
| `manual`, with a token set | `manual` | no producer exists for this window |
| unset, with a token set | `unknown` | the caller identified itself but said nothing about producers |
| any value not in {`managed`, `manual`} | `unknown` | malformed; never guessed at |
| any value, **token unset** | not recorded | there is no window identity to qualify. This is the legacy row, unchanged |

That last row is the predicate an earlier revision left as the vague phrase
"inconsistent with the token": a mode without a token qualifies nothing, so it is
ignored rather than stored. There is no other inconsistency to define, because the
two values are independent otherwise.

**Evaluated domain — and the correction that mattered most in this document.**

An earlier revision normalised `unknown` and `manual` to a single `unmanaged` mode
*and* made that mode imply an `unobservable` beat. Review showed that this is not
fail-closed at all, and the counter-example is worth keeping in the text so nobody
reintroduces it:

> A holder has a token, a **fresh heartbeat**, and `holder_mode: unknown` — because
> the launcher is partially adopted, or its mode export failed. A second caller
> arrives. Under the old normalisation the fresh beat became `unobservable`, so the
> caller reached a row requiring only `--takeover-instance --reason`, where the real
> evidence — a fresh beat — demands outright refusal under a valid lease, and
> `--live-override` under an expired one.

The metadata being absent had **erased an observation that was present**. That is
the same error as the previous revision in a new place: a missing declaration
treated as though it negated a signal. Two properties now govern the classifier,
and they are stated as properties rather than left implicit in rows:

1. **A fresh beat is never downgraded.** Missing, malformed, `unknown`, or even a
   false `manual` declaration cannot remove a sidecar that exists and is fresh. The
   refusal and `--live-override` floors hold on the beat alone.
2. **Only an explicit persisted `managed` enables the automatic row.** Every other
   mode value — `manual`, `unknown`, unrecorded — takes the audited path when the
   beat is stale or missing.

So `Mode` is not a normalisation of the beat. It gates exactly one outcome: whether
a *missing* beat may be read as *the producer failed to deliver*. Everything else in
the table reads the sidecar directly.

**Immutability across the work window.** `claim --refresh` is a `claim`, so the
question is real: `holder_mode` is written **once**, when the window opens, and a
refresh never rewrites it. A refresh presenting a different mode is a signal that
something changed identity mid-window; it is reported by the lint, not silently
applied. This is [RFC 078](078-rfc-freshness-first-class.md) §2.1 again — the
persisted boundary describes the moment it was captured and does not get quietly
restated later.

#### The trust limit, stated because the design leans on it

`managed` is a **cooperative declaration by the caller**, not an attestation the
core can verify. Nothing proves the value came from a real launcher; a process may
export `managed` and no producer need exist.

This matters for exactly one row: `not match / expired / stale or missing /
managed`, the only automatic outcome. It allows takeover on the strength of a
declaration rather than of proof. A caller wishing to displace a holder could
declare `managed`, wait for the lease to lapse, and take the pen **without an
operator decision and without a stated reason**.

To be exact, since an earlier revision overstated this and contradicted the table:
the takeover is still **recorded** — every row that changes the holder emits an
instance-change event. What the automatic row skips is the *reason* and the
*operator override*, not the audit trail. The event is what makes a false
declaration visible afterwards.

Three reasons to accept that, stated so a reader can disagree with the reasoning
rather than discover it later:

1. it is the same trust model as the token itself, which §1 already says stops an
   accident and not an attacker — this RFC adds no authentication anywhere;
2. the same actor could equally set a matching `holder_instance` and skip the whole
   mechanism, so the declaration is not the weakest link;
3. every other outcome in the table is *stricter* under a false declaration, since
   `unmanaged` is the fail-closed normalisation.

What the design must therefore **not** claim is that the automatic row rests on
evidence the previous instance is gone. It rests on a declaration that a producer
was expected, plus a beat that did not arrive. The lint finding
`instance_tokens_diverge` is where a false declaration becomes visible after the
fact, and that is the honest limit of it.

Recording the mode rather than re-deriving it later is [RFC
078](078-rfc-freshness-first-class.md) §2.1 applied directly: what a producer may
persist is the *boundary* — here, what was expected of this window — while the
evaluation of whether a beat is fresh still happens at the point of use.

**A declared producer that never emitted still reads as `stale or missing`.** The
declaration says a producer was expected; the beat says it did not deliver. Those
are two facts and the table wants both — which is why `Mode` and `Beat` stay
separate columns rather than one collapsed verdict.

| Identity | Lease | Beat | Mode | Outcome |
| --- | --- | --- | --- | --- |
| match | valid | any | any | **refresh** — today's behaviour, unchanged |
| match | expired | any | any | **refresh** — the holder reclaims its own expired window |
| not `match` | valid | **fresh** | **any** | **refuse outright.** The holder is provably alive; taking the pen would strand it mid-task. Mode is irrelevant — a beat that exists is evidence whatever the metadata says |
| not `match` | valid | stale or missing | any | **refuse ordinary claim; `--takeover-instance --reason`.** A live lease with no live beat is ambiguous, so it costs a reason and an audit record |
| not `match` | expired | **fresh** | **any** | **refuse ordinary claim; `--takeover-instance --live-override --reason`.** A fresh beat proves the holder alive and lease expiry does not weaken that proof — the [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md) human-authorization floor applies unchanged |
| not `match` | expired | stale or missing | **`managed` only** | **allow** with an instance-change event. A producer was declared, and it did not deliver |
| not `match` | expired | stale or missing | any other mode | **refuse ordinary claim; `--takeover-instance --reason`.** Without a declared producer, a missing beat is not evidence of anything |
| absent both sides | any | any | any | **today's behaviour, byte-identical** |

**Completeness, so a reviewer can check it rather than trust it.** Eight outcome
rows cover the domain exactly. `Beat` is read from the sidecar and has two values,
`fresh` or `stale or missing` — there is no third, because "no sidecar" and "a
sidecar that lapsed" are treated alike once no fresh reading exists. `Mode`
therefore appears in exactly one row pair, splitting `expired / stale or missing` by
whether a producer was declared.

Count it: 2 rows where identity matches (lease valid or expired, everything else
irrelevant); 2 rows for `not match` with a **fresh** beat, one per lease state, mode
irrelevant by property 1; 3 rows for `not match` with a stale or missing beat —
`valid` lease regardless of mode, then `expired` split by `managed` versus anything
else; and 1 legacy row where neither side carries a token. Two plus two plus three
plus one is eight, and every persisted `holder_mode` value lands in one of them.

The earlier nine-row claim covered a table whose `unobservable` beat value no longer
exists, and it was in any case false over the persisted domain — a real window
carrying `holder_mode: unknown` matched no row at all. Both defects are gone; this
count is over stored values, not over vocabulary.

**Why `not match` covers three identity values and not one.** `mismatch`, `caller
unidentified` and `holder unidentified` all take the same rows. An earlier revision
gave the two mixed states their own permissive row with `any / any / any`, which
let a tokenless caller displace a token-bearing holder that had a valid lease *and*
a fresh beat — evidence the table refuses one row above for a mere token mismatch.
**An unidentifiable caller has no stronger claim than a caller with the wrong
token**, and an unidentifiable holder is not thereby a dead one.

Four rows deserve prose, because each is a place where the table either changes an
existing outcome or was got wrong in an earlier revision.

**`mismatch / valid / fresh / managed` refuses** where today's code silently
refreshes. This is the row the whole RFC is for.

**`expired / absent / managed` allows**, agreeing with RFC 049's peer flow. The
agreement is deliberate: it is the one row where both documents weigh the same
evidence and reach the same answer. Note both qualifiers — the beat must be
*absent where a producer exists to emit one*, and the mode must be managed.

**`expired / stale or missing / any mode but `managed`` does NOT allow**, and the
history of this row is the most instructive thing in the document. One revision
concluded that "both signals agree the holder is gone" where there was no second
signal at all — a missing beat under no declared producer is not evidence, and
enumerating the case did not turn missing evidence into agreement. The next
revision over-corrected: it made the missing declaration *erase a fresh beat that
was actually present*.

Both errors are the same mistake pointing in opposite directions — treating the
absence of one input as though it settled another. That is precisely what
[RFC 078](078-rfc-freshness-first-class.md) exists to name, committed twice, in a
table written by the author of RFC 078's own corrections. The two properties above
exist so the mistake cannot be made a third time in either direction.

**`mismatch / expired / fresh / managed` requires `--live-override`,** not merely a
reason. An earlier revision let a reason string suffice here, which contradicted
the row above it: if a fresh beat is authoritative enough to prove the instance
alive under a valid lease, lease expiry does not make that proof weaker. RFC 049
reserves overriding a fresh heartbeat for *"explicit human authorization"*, and
this row now inherits that floor verbatim rather than inventing a cheaper one.

#### Adoption, which lives outside the table

A claim against `AWAITING_<agent>` or `IDLE` opens a **fresh work window**: there
is no lease to weigh, no beat to read and no holder to displace, so none of the
table's columns apply. The caller's token is simply recorded. This is where
adoption belongs, and it is stated here rather than as a table row because an
earlier revision put those lock states in the *lease* column, which broke both the
table's stated domain and its schema.

Against a live `WORKING_<agent>`, adoption is not free. An earlier revision allowed
any token-bearing caller to claim a tokenless LOCK unconditionally, reasoning that
the LOCK "predates adoption". It does not prove that. A tokenless holder may be a
live legacy or manual instance, and the token-bearing caller may be exactly the
second instance this RFC exists to catch — so the permissive reading would have let
the design **be defeated by being adopted**. That case is `holder unidentified` in
the table, and it takes the same gates as any other non-`match`.

#### The mixed state, stated rather than glossed

The earlier draft said an unset token leaves behaviour "byte-identical to today".
That is true only when **neither** side carries one. Once a holder has recorded an
instance, a caller with no token is not indistinguishable from that holder — it is
unidentifiable, which is a different thing — and the table above refuses it.

This is a real behavioural change in the mixed state, and it is the honest choice:
the alternative, letting an unset caller through, would mean opt-in protects
nobody, since any un-instrumented process could still walk over an instrumented
holder. Adoption cost stated plainly: the first agent to set a token makes
un-instrumented callers of the *same roster name* take an audited path.

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

**What is amended, said without softening.** An earlier revision called this
"narrower than the core identity model". Review was right that this understates
it: once a mismatch refuses `append`, `release`, `done` or a refresh, the pen owner
is operationally the pair **(roster name, instance)**, and calling an
authority-bearing comparison something other than an identity-model change would
be exactly the kind of reassuring phrasing this project refuses elsewhere.

So, plainly: **this RFC amends the core identity model for pen ownership only.**

**What is preserved, and should be read as binding:** roster name remains the sole
identity for routing, turn order, roles and delegation. The token grants no pen,
steals no fresh lane, authenticates nobody, and never influences who is next.

If reviewers judge that even this crosses RFC 010 §4, the alternative is explicit
and should be chosen consciously: keep the field in the companion, and accept that
unmanaged sessions stay uncovered. This RFC argues against that, but the choice
belongs in the open, not in an unremarked contradiction between two documents.

### 4. Advisory detection for the unset case

Adoption is gradual, so most shifts will run with no token for a while. For those,
`doctor --lint` reports **two distinct findings**, at severity *warn*. An earlier
draft described one of them here and the other in §1 as though they were the same
check; they are not, they detect opposite conditions, and either alone leaves a
blind spot.

| Finding | Condition | What it suggests |
| --- | --- | --- |
| `instance_tokens_diverge` | one relay session shows claims under **different** tokens, or a mix of set and unset | a rotation happened without an instance-change event, or adoption is partial |
| `instance_token_reused` | **one** token appears across session boundaries the runtime can independently see | the token was inherited rather than minted — the §1 failure mode, and the only signal available for it |

The first sees too many tokens, the second too few. Both follow the companion
doctrine: the core never blocks on either, the lint only names what it sees.

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

1. ~~**Reuse `--force` or add `--takeover-instance`?**~~ **Settled in §3**: a
   distinct operation. Leaving this open contradicted the body once §3 committed,
   and the reviewer was right to say one position had to remain. `--force` answers
   *the holder is gone*; `--takeover-instance` answers *the holder may be a
   different me*. One flag cannot record which question was answered.
2. **Who sets the token in manual mode?** A wrapper is the natural place, but a
   shift driven by hand would then never get the guard, and §1 is explicit that
   manual mode carries no freshness guarantee. `claim --new-instance` that mints
   and prints a token is one answer, but it is **not sufficient on its own**: a
   child process cannot export a value into its parent shell, so the RFC still
   owes an exact transport contract — what the operator does with the printed
   token so that the subsequent `claim --refresh`, `append`, `release` and `done`
   carry it. Printing a token and calling the problem solved would be the same
   half-measure this RFC was revised to remove.
3. ~~**Should `status` display it?**~~ **Settled in §1**: an 8-hex SHA-256 digest
   on human surfaces, the whole token on machine surfaces. This entry said
   "truncated to 8 characters" until the truncation was measured and found to carry
   no per-run entropy — left stale one revision too long, which is why it is called
   out here rather than quietly rewritten.
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
