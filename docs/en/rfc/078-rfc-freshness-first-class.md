# RFC 078 — Freshness is a first-class property of every derived value

- **Status:** draft / design-only, with one shipped instrument
- **Date:** 2026-07-27
- **Issue:** #273
- **Scope:** every surface that renders, or decides on, a value carrying a
  validity deadline — status text, status JSON, the TUI, admission gates,
  accounting folds, and the publication gate
- **Siblings:** [RFC 058](058-rfc-go-forward-rfc-discipline.md),
  [RFC 065](065-rfc-ticketed-committed-pushed-delivery.md),
  [RFC 076](076-rfc-incident-first-deterministic-reentrant-discipline.md)

## 1. The incident that produced the rule

This RFC exists because the same defect was found six times in five subsystems
inside two days, by six unrelated investigations. Each occurrence was verified
by reading the code and comparing a deadline the engine had **already parsed**
against `now()`.

| Subsystem | What the engine knew | What it did anyway |
|---|---|---|
| Core status (#271) | snapshot 20 h old; the runtime classified it `unknown` | printed `weekly left 94%` and a 5 h reset that had rolled about three times |
| TIME accounting (#270) | `⚠ stale lock` printed two blocks above, in the same frame | billed 15 h of a sleeping machine as effective work |
| Usage hold display (#258) | `resets_at` parsed | rendered `state: active` with a deadline in the past |
| Admission gate (#258) | the same record | refused a pen claim 45 minutes after the reset, blocking the reviewer in production |
| Listener lane | reported `coverage: absent` honestly | announced `phase: "polling"` for a pid dead for nine days |
| Publication gate (#262) | a local remote-tracking ref | treated it as the remote's current state, so a zero-commit walk printed `clean` |

Two are fixed. Four are open.

The pattern is **not** a rendering bug. In four of the six, another component
already publishes the correct answer and the consumer re-derives its own from
raw fields. The engine is not ignorant; it is inconsistent with itself.

### 1.1 The engine already half-implements the rule

Building the fixture for the contract test made this concrete. Three attempts
produced nothing, and each time the fold refused to bill the time and said
exactly why: `transition_outside_session` when the session start postdated the
transition, `transition_clock_regression` when the chain was not monotonic,
`current_lock_timeline_gap` when the LOCK disagreed with the ledger by a second.

The accounting fold is therefore **rigorous about the freshness of its inputs**
and publishes a diagnostic vocabulary for every way they can be untrustworthy.
It then bills an expired lease as work. The rule is not foreign to this codebase;
it is applied to ledger evidence and skipped on rendered values.

## 2. The rule

> Once its validity deadline has passed, a value MUST NOT influence a live
> decision, and MUST NOT be described as current. If it is still rendered — for
> audit, for diagnosis, for history — its expired state MUST be colocated with
> it.

An earlier wording of this rule said "MUST be evaluated against `now()` at the
point of use, and no surface may render it without an explicit freshness state".
Adversarial review broke it with two counterexamples that satisfy the letter and
reproduce the harm:

1. A gate compares the deadline with `now()`, **ignores the result**, denies
   admission on the stale value, and renders `freshness: stale`. It has
   evaluated the deadline and emitted an explicit state — and still reproduces
   the defect this RFC exists to stop.
2. A producer **persists** `freshness: fresh` at capture time. Hours later a
   consumer dutifully obeys §2.1 and displays the owner's classification without
   re-deriving it. The classification has aged into a lie.

The wording above closes both, because it constrains the *effect* (influence on
a decision, description as current) rather than the *ritual* (having called a
comparison). Keep the operational implication in view: evaluate the deadline
where the value is used, not where it was produced.

"Validity deadline" means any field that answers *until when is this true*:
`expires`, `resets_at`, `captured_at` paired with a staleness bound, a lease
TTL, a heartbeat cadence, a pid whose liveness is the deadline.

### 2.1 Corollary — single owner of freshness

There MUST be one freshness evaluator, and consumers MUST NOT re-derive their
own from the underlying fields. The divergence in #271 exists because two
components read the same record and answered differently; one of them has to be
the owner.

**But a classification MUST NOT be serialized as a timeless fact.** A stored
`freshness: fresh` is a statement about the moment of capture, and it decays.
What a producer may persist is the *boundary* — `evaluated_at`, `fresh_until`,
`resets_at` — which the consumer rechecks at the point of use. Owning the rule
is not the same as owning a verdict with no expiry of its own; without this
sentence, §2.1 contradicts §2.

### 2.2 Corollary — a cache of a remote authority is not the remote

Remote-tracking refs, last-known snapshots, copied state and previously fetched
manifests are evidence of a **past observation**. They are never evidence of the
current state of the authority they mirror.

Any decision that turns on *is this still true over there* MUST re-observe, or
fail closed. #262 is the worked counter-example: the publication gate excluded
history "already published" according to tracking refs that no longer described
the remote, so the walk covered zero commits and reported clean.

This corollary is deliberately stated in terms of authority rather than of git:
it applies equally to a cached quota snapshot, a cached kit manifest, and a
cached listener pid.

### 2.3 Corollary — one frame, one truth

An engine that knows a value is stale in one part of an output MUST NOT present
it as current in another part of the same output.

This is the cheapest of the three to check and the most damaging to violate: a
single frame that contradicts itself teaches the operator to distrust the whole
surface. #270 printed `⚠ stale lock` and an inflated effective-work total eight
lines apart.

## 3. What the rule does not say

- It does not require hiding stale data. Stale data is often the most useful
  thing on screen — it is the *unmarked* presentation that is forbidden.
- It does not require a network call at every read. Corollary 2.2 offers
  re-observe **or fail closed**; a gate that refuses to answer is compliant, a
  gate that answers from a cache as if it were current is not.
- It does not forbid caching. It forbids a cache from claiming the authority of
  what it caches.

## 4. The instrument, and why it ships with the rule

A rule with no detector is re-broken at the next commit, and an audit claim with
no method cannot be contested. This RFC therefore ships a behavioural contract
test rather than a lint:

`test_freshness_contract_on_four_enumerated_projections` builds one fixture in
which **every** deadline is already in the past — a usage snapshot far beyond its
staleness bound, a usage hold whose reset has elapsed, a lock whose lease has
expired while the state still reads `WORKING_*` — and feeds it to four named
projections: the status-JSON usage freshness, the status-JSON hold state, the
human status line, and the TIME accounting total.

Four, not "every": the list is hand-written and the test **discovers nothing**.
A new renderer, gate, companion lane or derived aggregate passes without ever
appearing here. The earlier name said "every surface" and was wrong.

A lint over source would be weaker: the rule is about behaviour at the point of
use, and the same field is legitimately rendered raw in one context (an audit
record) and forbidden in another (a live dashboard). Only the rendered output
can tell them apart.

### 4.1 The known-failure list — and exactly what it does not guarantee

Projections that still fail are listed in a `KNOWN_FAILURES` table inside the
test, each entry naming its open ticket. For those, the test asserts the failure
**still holds**; for the others it asserts compliance.

**What this guarantees:** fixing a listed projection makes the test fail until
its entry is removed, so an unfinished fix cannot look green, and a fix cannot
land silently without updating the record.

**What it does NOT guarantee, and an earlier draft of this RFC wrongly claimed
it did:** nothing prevents the table from *growing*. A contributor who
introduces a failure on a covered projection can turn the suite green by adding
one line here. Membership merely reverses the expected boolean; the ticket value
is not validated, and the set is not compared against the base branch. Calling
it a ratchet was false — adversarial review established this before merge, and
the name was changed to match the mechanism rather than the intention.

Real monotonicity needs a gate the contributor **cannot edit in the same change**
that adds the exemption: a default-branch CI check comparing the set with the
merge base and rejecting additions while allowing removals. A self-check living
in the same file does not establish it. Tracked separately; until it exists,
this is an expected-failure list with useful assertions, and nothing more.

### 4.2 What the instrument does not cover

Stated so the test is not mistaken for full coverage of the rule:

- **The publication gate (#262) is out of scope of this test.** Its deadline is
  the freshness of a remote-tracking ref, which needs a git fixture with a real
  remote rather than a status fixture. Corollary 2.2 governs it; the detector
  does not yet reach it.
- **The listener lane is not asserted.** Its violation (`phase: "polling"` on a
  dead pid) lives in the runtime companion, whose surfaces are exercised by a
  different suite. It belongs in the table once someone extends the fixture with
  a lane record.
- **The TUI is covered only through the payload it renders**, not through its
  drawn output. A regression that appears purely in the drawing code would pass.

Each of these is a gap in the *instrument*, not an exception to the rule.

## 5. Acceptance

1. Each of the **four enumerated projections** either complies or appears in
   `KNOWN_FAILURES` with a ticket reference. No third category. The four are the
   status-JSON usage freshness, the status-JSON hold state, the human status
   line, and the TIME accounting total — enumerated because the test discovers
   nothing beyond them.
2. `KNOWN_FAILURES` is empty once **#270 and #271** close. Those two are the
   machine-checked part, and only those two: **#262 is deliberately excluded**,
   because the detector does not reach the publication gate (§4.2). An earlier
   draft claimed the table also emptied when #262 closed, which would have let
   this criterion report completion while #262 stayed open.
3. New surfaces that render a deadline-bearing value should add themselves to
   the test in the same change. This is a **contribution rule, not a
   machine-checked contract** — nothing detects a surface that omits itself.
   Making it a contract requires deadline-bearing surfaces to register through
   one enumerable production abstraction the test can iterate; separate work,
   not done here.

## 6. Open questions

1. **Does the rule extend to derived aggregates?** #270 is an aggregate: the
   inflated total was correct arithmetic over a wrong input classification.
   Aggregates probably need a coverage figure rather than a freshness state —
   the TIME fold already publishes `coverage_ratio`, which suggests the answer is
   yes, with a different vocabulary.
2. **What is the tolerance for clock skew?** The provider-hold work landed an
   explicit horizon for exactly this reason. A shared constant is probably better
   than per-surface judgement, but the acceptable skew for a local lease and for
   a vendor-supplied reset are not obviously the same number.
3. **Should the pid liveness case use the same vocabulary?** A dead pid is a
   deadline that has passed, but `elapsed` reads oddly for it. `absent` already
   exists in the lane vocabulary and may be the right term, at the cost of two
   words for one concept.
