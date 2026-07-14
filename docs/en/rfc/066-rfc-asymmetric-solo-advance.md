# RFC 066 — Asymmetric solo advance with deferred reconciliation

- **Status:** draft / feasibility study; no behavior is active
- **Date:** 2026-07-14
- **Scope:** allow one available relay agent to make bounded progress while a peer is
  quota-blocked or explicitly absent, without erasing the review that normal alternating
  work would have provided.
- **Builds on:** [RFC 016](016-rfc-cooperative-turn-request.md),
  [RFC 021](021-rfc-pause-resume.md),
  [RFC 040](040-rfc-ai-session-usage-monitoring.md),
  [RFC 049](049-rfc-holder-liveness-stale-claim-hardening.md),
  [RFC 054](054-rfc-pre-exhaustion-session-rotation.md),
  [RFC 055](055-rfc-wait-operator-state.md), and
  [RFC 062](062-rfc-listening-ends-only-at-done.md).

## 0. Proposal summary

Add an explicit **solo episode** around the existing relay, with two phases:

1. an available agent opens a bounded, policy-authorized episode, records the exact
   baseline and deferred review obligations, then completes permitted turns without a
   real-time contradictory peer review;
2. when the absent peer returns, the relay blocks ordinary paired progression at the next
   safe boundary until that peer reviews the episode and closes, revises, or disputes each
   obligation.

The core remains degree-1: there is still one pen and never more than one writer. Solo mode
changes who may receive the next turn; it does not create another holder, simulate a peer
message, or declare deferred review complete.

This is a feasibility RFC, not authorization to implement or use the mode. Three policy
forks in §12 require an operator decision first.

## 1. Problem

Strict alternation is valuable because contradictory review catches mistakes before they
accumulate. It also means `AWAITING_<peer>` stops the entire shift when that peer is known
to be unavailable, even if the other agent has fresh quota and logged, reversible work it
could complete.

The existing mechanisms solve adjacent problems but not this one:

- RFC 054 rotates one provider session before context exhaustion; it does not authorize
  the other agent to replace a missing reviewer.
- RFC 040 can identify a usage cooldown and reset; usage telemetry is advisory availability
  evidence, not routing authority.
- RFC 049 distinguishes live, expired, and stale holders; absence is not stale-pen theft.
- RFC 016 requests or steers one turn; it does not establish a sequence of deliberately
  unpaired turns or preserve the reviews owed by that sequence.
- RFC 021 pauses an open session with no active task; it cannot express "one agent may keep
  working while the other owes review later."
- RFC 055 keeps a holder alive while waiting for an operator; it deliberately retains the
  current pen and is not a solo-progress state.

Ad-hoc self-handoffs would hide the loss of contradiction. A safe design must make that
loss visible, bound it, and convert it into explicit reconciliation debt.

## 2. Goals

- Permit conscious, bounded progress by one available agent during a verified absence.
- Preserve the exclusive pen, claim-before-write rule, immutable turns, and append-only
  audit trail.
- Record what changed, what evidence exists, and what the missing peer would have reviewed.
- Make debt survive process/frontend failure and fresh provider sessions.
- Detect a peer's return without treating detection as approval or authority.
- Reconcile before the relay resumes normal paired work beyond a safe boundary.
- Make disagreement useful: the returning peer may identify defects rather than rubber-stamp
  the solo work.

## 3. Non-goals

- No concurrent writers, parallel pen, or hidden specialist lane.
- No synthetic turn attributed to the absent peer and no model impersonation.
- No claim that delayed review is equivalent to real-time co-design.
- No inference that silence, a closed UI, an expired pen, or a quota reset authorizes work.
- No automatic merge, release, deployment, destructive operation, secret access, or scope
  expansion.
- No automatic revert by a companion process.
- No weakening of project binding, prompt-security, raw-proof, delivery, or RFC gates.
- No replacement for normal alternation when both peers are available.

## 4. Terminology

- **solo episode**: a bounded interval in which one named agent may receive successive
  turns without peer review under an approved policy.
- **soloer**: the available agent performing those turns.
- **absent peer**: the roster member whose review is deferred. Absence is a declared or
  externally evidenced availability condition, not presumed from silence.
- **reconciliation debt**: a concrete review or decision the peer would normally have
  performed, linked to exact turns, commits, files, and evidence.
- **return-ready**: availability evidence says the absent peer can likely run again.
  It does not mean the peer has read or accepted anything.
- **reconciled**: every required debt item has a recorded peer disposition and any required
  correction has passed its declared gate.

## 5. Proposed state model

Do not add `WORKING_SOLO` or a second pen. Keep normal LOCK states and add one local,
audited episode record:

```text
AWAITING_absent
  -> solo-open gate
AWAITING_soloer
  -> claim soloer
WORKING_soloer
  -> append --solo-episode N --to soloer
AWAITING_soloer
  -> ... bounded repetition ...
  -> solo-yield
AWAITING_absent
  -> claim absent
WORKING_absent (reconciliation turn)
  -> append to soloer / ordinary alternation restored
```

`append --to self` remains invalid outside an active episode. During an episode it is
accepted only for the named soloer, only with the episode id, only while the episode is
within its scope/turn/time bounds, and only after the turn adds at least one debt record
or explicitly states why no peer review would normally be due.

The transition from `AWAITING_<absent>` to `AWAITING_<soloer>` is a named override, not a
force-claim. It must record the authorizer and reason, preserve the pending handoff
verbatim, and never use RFC 049 stale recovery as a shortcut.

## 6. Durable reconciliation ledger

Add a generated, append-only local artifact:

```text
M8SHIFT.reconciliations.md
```

It follows the existing ignored coordination-artifact model and is archived/bounded like
the relay journal. Each episode begins with an immutable declaration:

```yaml
episode: 7
session: 20260714T190000Z-example
status: open
soloer: codex
absent_peer: claude
baseline_turn: 748
baseline_commit: 0123456789abcdef0123456789abcdef01234567
absence_evidence: usage_cooldown until 2026-07-19T19:00:00Z
authorization_kind: operator|policy
authorization_ref: operator-command|policy-id
allowed_task_classes: [docs, tests, reversible_implementation]
denied_actions: [merge, deploy, release, destructive, secret-bearing]
max_turns: 4
deadline: 2026-07-15T19:00:00Z
```

Every solo turn appends one or more debt items:

```yaml
debt: 7.2
source_turn: 751
task_ref: task-70
commits: [fedcba9876543210fedcba9876543210fedcba98]
files: [docs/en/rfc/066-rfc-asymmetric-solo-advance.md]
evidence: [test-command-and-result-reference]
review_owed: check authorization, design assumptions, diff, tests, and scope
solo_assessment: reversible; not merged
peer_disposition: pending
```

Debt entries never contain hidden reasoning, credentials, raw provider transcripts, or a
fabricated peer position. Exact diffs and logs stay referenced as raw evidence. The final
turn/checkpoint includes a compact **consignes** summary generated from the still-pending
items so a fresh returning session can start without reconstructing chat history.

Commits and push/forge references remain governed by the standing delivery policy. The
ledger does not substitute for versioned source history or the structured ticket.

## 7. Eligibility and bounds

An episode may open only when all mechanical preconditions pass:

1. the relay is `AWAITING_<absent>` or deliberately `PAUSED`; no agent holds the pen;
2. the pending handoff has been read and preserved;
3. absence evidence is explicit and fresh (for example an RFC 040 cooldown with a reset,
   or a first-party operator declaration), never mere silence;
4. the baseline turn, full Git SHA, dirty-tree state, task ids, scope, authorizer, reviewer,
   deadline, and maximum turn count are recorded;
5. the task classifier permits every queued item under the selected operator policy;
6. no earlier episode for the same reviewer has unresolved blocking debt;
7. the soloer passes the normal project binding and may-write gates after claiming.

Recommended conservative default bounds, if the operator selects them, are four turns or
24 hours, whichever occurs first. Reaching a bound routes to the absent peer and waits; it
does not silently renew. Extending an episode requires a new audited authorization.

## 8. Task classification

The mechanism needs a closed, operator-selected policy rather than a free-form agent claim.
A candidate matrix is:

| Class | Candidate solo treatment | Reason |
|---|---|---|
| Documentation/study | allow with debt | reversible and directly reviewable |
| Tests/diagnostics | allow with debt | adds evidence; must not weaken gates |
| Reversible implementation on an unmerged branch | allow with strict bounds | progress is inspectable and revertible |
| Architecture/governance decision | propose only | contradiction is part of the decision |
| Security/privacy boundary | defer or require operator-specific grant | delayed review can expose assets |
| Migration/data mutation | defer | rollback may not restore external state |
| Merge/release/deploy/publish | deny by default | crosses an external or shared-state gate |
| Destructive Git/force/network credential action | deny | existing explicit-human gates still bind |

"Implementation yes" is therefore not a universal permission: it means a branch-local,
reversible change inside the declared task and evidence gates. Classification ambiguity
fails closed to `defer`.

## 9. Return detection and reconciliation

Return detection uses the best local first-party signal available:

- an RFC 040 provider window reset and a fresh normalized usage snapshot;
- a resident listener reporting the peer invocation lane ready;
- an explicit peer or operator return declaration.

A scheduled reset timestamp alone is not return: the snapshot may be stale and the host may
still be unable to invoke the peer. Detection sets `return-ready` and notifies/routs at the
next safe boundary; it does not launch an interactive UI, mutate debt dispositions, or
attribute consent to the peer.

The returning peer must:

1. claim the reconciliation turn and read the original pending handoff plus the consignes;
2. inspect every referenced raw diff/evidence item from the recorded baseline;
3. record one disposition per debt: `accept`, `accept-with-follow-up`, `revise`, or `dispute`;
4. implement or assign required corrections under the normal pen discipline;
5. close the episode only when no blocking `revise`/`dispute` item remains;
6. append to the soloer, restoring ordinary alternation.

Review is about the work, not validating the soloer's simulated account of what the peer
"would have said." The returning peer supplies its own current judgment.

## 10. Command feasibility sketch

The core could expose narrow verbs:

```bash
python3 m8shift.py solo-open codex --absent claude --task 70 \
  --policy operator --reason "operator approved bounded backlog progress" \
  --max-turns 4 --until 2026-07-15T19:00:00Z

python3 m8shift.py append codex --to codex --solo-episode 7 \
  --ask "continue permitted task; record debt" --done "..." --files "..."

python3 m8shift.py solo-yield codex --episode 7 --to claude
python3 m8shift.py reconcile claude --episode 7 --debt 7.2 --disposition revise \
  --reason "missing boundary test"
python3 m8shift.py reconcile-close claude --episode 7 --to codex
```

All mutating verbs use the existing file lock, actor/binding checks, sanitization, and
append-only event ledger. `solo-open` performs no repository write and acquires no pen; it
only changes routing and opens the debt ledger under its authorization gate. Normal
`claim -> work -> append` remains mandatory for each solo turn.

`status --json`, `status --for`, `watch`, and the dashboard should show the episode id,
soloer, absent peer, remaining bounds, pending/blocking debt count, and return readiness.
`doctor` should detect malformed ledgers, missing source turns/commits, expired episodes,
self-handoffs without an episode, scope/class violations visible from metadata, and closed
episodes with pending debt. Diagnostics are advisory and never approve or revert work.

## 11. Failure and recovery

- Soloer becomes unavailable: route to the absent peer and retain all open debt; never
  transfer solo authority automatically to a third agent.
- Usage evidence becomes stale: stop at the current safe boundary and require fresh evidence
  or operator direction.
- Bound expires mid-turn: finish only the safety-preserving checkpoint/append; no new task.
- Ledger write fails: the self-handoff fails atomically and the soloer retains the pen long
  enough to checkpoint or release.
- Commit/reference is missing: mark the debt blocking; do not accept a prose-only claim.
- Peer returns during work: do not interrupt a fresh pen; route to reconciliation at the
  next successful append/checkpoint.
- Peer rejects work: follow the selected reconciliation-authority policy in §12; preserve
  both positions and raw evidence.
- Frontend crashes: the relay, Git history, episode declaration, and debt ledger are the
  recovery source; a foreground waiter alone does not promise invocation.

## 12. Operator decisions required before implementation

These forks are intentionally unresolved. No implementation may encode defaults until the
operator selects each one.

### D1 — Who authorizes solo override?

- **Operator-only:** safest and easiest to audit; cannot progress unattended.
- **Pre-approved policy:** an agent may open an episode when a signed/project-local policy
  and all mechanical predicates match; policy creation/amendment remains operator-gated.
- **Agent-autonomous:** maximum availability, but lets the beneficiary of the override judge
  its own authority; not recommended without stronger constraints.

### D2 — Which task classes are solo-able?

- **Docs/tests only:** lowest blast radius, limited useful progress.
- **Reversible branch-local implementation too:** recommended candidate; excludes the
  irreversible/high-risk classes in §8.
- **All logged work except an explicit denylist:** broadest progress, greatest classification
  and policy-drift risk.

### D3 — What authority does the returning peer have?

- **Acknowledge/advisory only:** solo results stand unless the operator intervenes; weakens
  contradictory review.
- **Revise through normal follow-up commits:** recommended candidate; the peer can block
  episode closure and require corrections, but cannot silently rewrite history.
- **Revert solo work:** strongest review authority; must still obey normal pen, delivery,
  destructive-operation, and external-state gates. Already-merged/deployed effects may not
  be honestly reversible, which is why §8 denies them by default.

The operator may choose a hybrid, but the resulting policy must be explicit, closed-enum,
versioned, and displayed in the episode declaration.

## 13. Security and governance

- Relay text, debt text, and consignes are untrusted coordination data. They cannot grant
  solo authority, expand scope, reveal secrets, or waive human gates.
- Only typed command arguments or a governed project-local policy identify authorization;
  never infer it from an `ask`, issue body, model prose, or provider output.
- Provider usage is untrusted advisory input. Validate schema, freshness, agent mapping, and
  project/session binding before using it as absence/return evidence.
- Preserve RFC 052 compartmentalization: project-relative examples, no cross-project paths
  or literal external session captures in source, tests, or relay records.
- Solo turns receive the same forge ticket, commit, push/gateway, test, and RFC treatment as
  paired turns. "The reviewer is absent" is not a delivery exemption.
- A self-handoff without an active episode is a protocol error. A companion never edits the
  LOCK or reconciliation ledger directly; it calls the core.
- The absence of immediate review must be visible in PR/ticket status. Work must not be
  presented as paired-approved until reconciliation closes.

## 14. Acceptance criteria for a future implementation

1. At most one `WORKING_*` holder exists throughout every episode and race test.
2. Solo routing is impossible without an audited authorization satisfying D1.
3. Silence, TTL expiry, reset prediction, or relay prose alone cannot open an episode.
4. Self-handoff is accepted only for the episode soloer and fails outside declared bounds.
5. Every solo turn creates traceable debt linked to immutable turns and exact Git evidence.
6. A process crash preserves enough durable state for a fresh session to reconcile.
7. Return detection marks readiness only; it never launches a UI or accepts debt.
8. Ordinary paired work cannot pass the reconciliation boundary with blocking debt.
9. The returning peer can exercise exactly the authority selected in D3, with all existing
   safety and delivery gates still enforced.
10. `status`, JSON, dashboard, journal, and doctor expose the same episode/debt truth.
11. Existing relays with no episode retain byte-for-byte routing behavior and reject
   `append --to self` as before.
12. Tests cover concurrent open attempts, stale/malformed usage data, expiry mid-turn,
   ledger-write failure, peer return during a fresh pen, dispute, and crash recovery.

## 15. Feasibility and staged delivery

The design is feasible with local stdlib-only mechanisms already used by the relay:
exclusive file locking, immutable turns, append-only ledgers, normalized usage sidecars,
project binding, and dashboard snapshots. The hard problem is policy, not process control.

After D1–D3 are decided, deliver in gated slices:

1. ledger schema, parser, read-only status/doctor, and fixtures;
2. `solo-open`/`solo-yield` plus bounded self-handoff state transitions;
3. reconciliation dispositions/closure and return-ready integration;
4. runtime/dashboard surfacing and end-to-end crash/race tests;
5. dogfood only on a reversible documentation/test episode before implementation work.

Until all slices are accepted, the supported behavior remains strict alternation or an
explicit pause. No agent should emulate this RFC with manual LOCK edits or ad-hoc force.
