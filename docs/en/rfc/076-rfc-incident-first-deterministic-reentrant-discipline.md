# RFC 076 — Incident-first, deterministic, re-entrant change discipline

- **Status:** draft / design-only
- **Date:** 2026-07-18
- **Issue:** #213
- **Scope:** contribution workflow for defects, regressions, bootstrap failures,
  and operational contradictions
- **Siblings:** [RFC 058](058-rfc-go-forward-rfc-discipline.md),
  [RFC 065](065-rfc-ticketed-committed-pushed-delivery.md), and
  [RFC 074](074-rfc-standardized-inter-agent-exchange.md)

## 1. The RFC applies its own rule

### Ticket and incident

Ticket #213 exists before this draft. Its incident is the bootstrap batch that
began from one adopter-visible failure chain and repeatedly exposed missing
durable contracts: incompatible runner/runtime generations, a deterministic
read-only environment classified as retryable, contradictory listener status,
and a recovery process that initially depended on live conversational context.

### Reproduction

Give a fresh agent only the repository plus the durable adoption artifacts.
Withhold chat history, shell scrollback, process memory, and knowledge of the
original operator. Ask it to:

1. identify the active relay root and installed component versions;
2. explain why the listener halted;
3. reproduce the failure hermetically;
4. locate the ticket, root cause, and regression guard; and
5. resume or safely stop according to the runbook.

The pre-discipline workflow fails whenever any required fact exists only in the
originating conversation, a host-specific golden, wall-clock timing, or an
unrecorded operator action.

### Root cause

The project had strong relay and delivery rules, but no single contract required
each problem to become a causal incident packet, its tests to be hermetic, and
its recovery to be reconstructible by a context-free successor. Those qualities
were achieved inconsistently by review rather than guaranteed at intake.

### Anti-recurrence guard

This RFC's acceptance fixture is a **blank-agent reconstruction drill**. The
agent receives only the durable artifacts enumerated in §5 and an empty runtime
process state. Success requires a deterministic diagnosis and next command; a
hidden chat fact, absolute host path, live PID, or uncaptured environment value
is a test failure.

## 2. Decision

Every problem-driven change follows three inseparable disciplines:

1. **Incident-first:** create or reconcile a structured ticket and incident
   packet before or with the fix. Record reproduction, impact, causal root, and
   an executable anti-recurrence guard.
2. **Deterministic:** make the reproduction and gates depend on controlled
   fixtures and injected boundaries, not the host's clock, process table,
   locale, network, credentials, or incidental repository state.
3. **Re-entrant:** make the operational state reconstructible by a fresh agent
   from durable project artifacts alone. Re-running a documented step either
   converges, reports a stable no-op, or refuses before mutation with an
   actionable reason.

The policy applies to bugs, production incidents, bootstrap/adoption failures,
test flakes with a product cause, state contradictions, and newly discovered
security or reliability gaps. Pure editorial corrections may use the ordinary
RFC 065 ticketed delivery path without manufacturing an incident.

## 3. Incident-first contract

### 3.1 One problem unit

A coherent problem unit contains:

```text
ticket -> incident packet -> failing reproduction -> causal decision
       -> fix/design -> anti-recurrence guard -> verification -> delivery evidence
```

The ticket is the remote coordination identity. The incident packet is durable
causal evidence in the repository or a repository-referenced forge artifact.
The relay task is temporary intake and never the only record.

If investigation reveals a distinct cause or independently shippable risk, open
a sibling problem unit instead of silently widening the first. A symptom may
have several causes; a cause may require several implementation slices. The
mapping must remain explicit.

### 3.2 Minimum incident packet

Each packet records:

- stable incident/ticket reference and discovery date;
- user-visible symptom and bounded impact;
- minimal reproduction using placeholders;
- expected and actual result;
- evidence class and exact raw-evidence reference;
- causal graph separating external trigger, product cause, and amplifiers;
- decision: confirmed, refuted, or still unknown;
- fix boundary and explicit non-goals;
- anti-recurrence guard/test, including why it would fail before the fix;
- recovery/rollback behavior;
- validation and delivery references.

“Caught exception X” is not a root cause. The causal statement must explain why
the product admitted, misclassified, hid, or repeated the failure. Ambiguity is
recorded as unknown and remains retryable/advisory according to the governing
runtime contract; it is never converted into certainty by prose.

### 3.3 Before or with, never after as archaeology

For a known failure, the packet and failing reproduction precede behavior
changes. When the failure is discovered during implementation, the same commit
may add the packet, an expected failure, and the fix, provided review can see the
pre-fix expectation and the test demonstrably distinguishes old from new.

An emergency may shorten review latency, but it still records the incident and
guard before merge. A retrospective written after delivery is useful history,
not compliance with incident-first.

## 4. Deterministic contract

### 4.1 Hermetic inputs

Tests and reproductions use generated temporary roots and placeholder identities
such as `My Project`, `~/code`, `agent-a`, opaque session IDs, and fixed digests.
They do not copy a live relay, provider response, process listing, credential
path, private forge address, or adopter identity into fixtures.

All unstable boundaries are injected or abstracted:

- clock and timezone;
- random/nonces and generation IDs;
- PID liveness and process exit;
- filesystem permissions and atomic-write failures;
- environment variables and current directory;
- terminal width, TTY/color capability, and locale;
- subprocess output, timeout, and truncation;
- provider/network responses;
- Git branch/upstream state.

### 4.2 Stable assertions

Assertions target schemas, state transitions, stable reason IDs, byte bounds,
and semantic invariants. They do not bless complete host-rendered output when a
small structural assertion is sufficient.

Golden files are permitted only for a genuinely byte-normative portable
artifact. Such a fixture must pin every input, contain placeholders, declare the
schema/version, and prove independence from environment and time. A golden made
from current shell output is evidence contamination, not a regression test.

### 4.3 Failure classification

A deterministic impossibility fails fast without consuming retry budget. A
terminal classification requires a controlled probe or explicit protocol
contract. Text signatures alone are advisory corroboration when they can be
quoted, localized, or reformulated. Ambiguous failures remain ambiguous.

Tests assert both sides of the boundary: the exact known failure becomes
terminal, while neighboring text/state stays retryable or unknown. This prevents
the anti-recurrence guard from creating a false-positive halt.

### 4.4 Gate declaration

Each change declares its gates before review:

- focused reproduction and neighboring negative controls;
- supported interpreter/platform floors;
- full project suite where the risk surface requires it;
- deterministic checksum/index/schema checks;
- raw hygiene/leak scan over the exact change range; and
- delivery evidence under RFC 065.

A filtered or compressed log is orientation only. Review verdicts cite the raw
diff or retrievable raw test evidence.

## 5. Re-entrant contract

### 5.1 Durable reconstruction set

For an adopted relay, a fresh agent may rely on:

1. the append-only journal and current lock (`M8SHIFT.md` plus archived/session
   history when explicitly required);
2. the generated agent pack;
3. the core protocol and on-demand reference;
4. `.m8shift/kit.json` for installed component version/digest identity; and
5. the marker-managed bootstrap runbook.

Repository work may additionally rely on committed RFCs, incident documents,
tests, the issue lifecycle, changelog/release notes, and exact Git history.
Runtime sidecars are recoverable evidence, never the only source of an invariant.
Chat transcript, model memory, shell scrollback, a living process, and an
operator's recollection are explicitly non-durable.

When durable sources disagree, the protocol/lock controls routing, `kit.json`
controls installed component identity, immutable journal history controls what
was handed off, and the runbook explains recovery. The disagreement itself
becomes an incident; an agent does not silently choose the most convenient copy.

### 5.2 Re-entry properties

Every operational step is one of:

- **idempotent:** repetition converges to the same bytes/state;
- **no-clobber:** existing operator-owned content is preserved;
- **preflighted mutation:** all refusal conditions are checked before the first
  write; or
- **append-only:** repetition creates a separately identified event rather than
  rewriting history.

Generated documents use marker-delimited regions when operator prose may coexist.
Component-dependent runbook steps first verify the corresponding `kit.json`
entry and emit the install command when absent. A halt records a stable cause ID
and a next action; it does not require the original agent to explain itself.

### 5.3 Blank-agent drill

High-risk bootstrap/runtime changes include a reconstruction test or documented
drill:

```text
Given: only the durable reconstruction set, no live listener, fixed time
When:  a fresh agent follows the runbook from the first read-only command
Then:  it identifies versions/state/cause, refuses unsafe writes before mutation,
       and reaches the same resume, repair, or clean-halt recommendation twice
```

The second run is mandatory: a workflow that succeeds once but corrupts or
duplicates state on repetition is not re-entrant.

## 6. Workflow and review gates

### Intake

1. Create/reconcile the structured forge ticket.
2. Add the minimum incident packet using abstract fixtures.
3. Reproduce or explicitly record why reproduction is currently impossible.
4. State the causal hypothesis and disconfirming evidence.

### Design gate

5. Separate trigger, root cause, amplifier, and recovery behavior.
6. Define the deterministic boundary and negative controls.
7. Identify the durable artifacts needed for blank-agent reconstruction.
8. Obtain the normal propose-first/operator gate when the governing RFC requires
   it.

### Implementation and verification

9. Land the failing guard before or visibly with the fix.
10. Keep each independently discovered problem in its own ticket/incident unit.
11. Run focused, floor, full-suite, integrity, and raw hygiene gates appropriate
    to the risk.
12. Perform the second-run/re-entry check.

### Delivery

13. Commit the coherent unit and cite the ticket and incident.
14. Push/review through the direct or named-gateway RFC 065 path.
15. Close only with remote SHA/review evidence and the passing anti-recurrence
    guard. Opened tickets, local commits, or draft PRs are not completion.

## 7. Abstract bootstrap case study

The batch from intake #92 through delivery PRs #216/#217/#219/#220 is the model
for this discipline. The references are project-local workflow evidence; all
fixtures and examples remain placeholders.

| Slice | Incident-first move | Deterministic guard | Re-entrant result |
|---|---|---|---|
| #216 | Captured the four-cause bootstrap incident before behavior correction | Executable expected failures reproduced an old runner and a write-denied provider with synthetic processes | The causal record no longer depended on the original adopter session |
| #217 | Split compatibility, launch classification, and provisioning causes instead of treating all as `non_completion` | Version/capability handshake, bounded probes, fixed exit taxonomy, neighboring false-positive tests | A fresh runtime can identify an incompatible/missing runner and emit a stable repair action |
| #219 | Recorded the same-frame listener contradiction as a product incident | One pure truth table with injected time/PID/sidecars and full state matrix | Every consumer reconstructs the same lifecycle/coverage/attention verdict and stable cause |
| #220 | Treated wrong-root writes and missing recovery knowledge as bootstrap incidents | Preflight-before-write tests, marker/no-clobber fixtures, bare-invocation CLI contracts | The durable runbook plus journal/pack/protocol/kit reconstructs setup and halted recovery twice |

Additional findings discovered during the batch were opened as separate incident
work (#214, #218, and #222) rather than silently folded into a convenient PR.
That separation is a feature: incident-first limits causal ambiguity and lets
each guard close the risk it actually proves.

## 8. Relationship to existing RFCs

- **RFC 058** requires architecture/behavior changes to carry their governing
  RFC and keeps RFC indices mechanically honest. RFC 076 adds the problem-causal,
  deterministic, and reconstruction requirements; it does not replace same-PR
  documentation.
- **RFC 065** governs ticket, commit, push, review, and gateway evidence. RFC 076
  defines what a problem ticket must contain before that delivery path can call
  the defect resolved.
- **RFC 074** defines portable structured turns and whole-shift export. Such an
  export can carry incident and evidence references, but it is a derived view,
  not the durable reconstruction set and not proof that cited gates ran.
- **RFC 048** supplies marker-managed adoption artifacts and pack/update health;
  RFC 076 applies those mechanics to re-entry and blank-agent recovery.

## 9. Enforcement posture

The initial policy is review-enforced and advisory in tooling. A later authorized
implementation may add templates and doctor findings for missing packet fields,
host-coupled fixtures, or absent reconstruction evidence. It must not attempt to
infer root cause from prose, contact the forge, mutate incident files, or block
the relay mutex.

No implementation is authorized by this RFC draft.

## 10. Rejected alternatives

- **Fix first, write the incident later:** loses the pre-fix contract and invites
  a retrospective story that the guard never actually distinguished.
- **One umbrella incident for every finding in a batch:** obscures independent
  causes, ownership, and completion evidence.
- **Full-output goldens from a live machine:** couple tests to paths, clocks,
  PIDs, locale, secrets, and unrelated formatting.
- **Retry every unknown:** wastes budget on deterministic impossibilities.
- **Treat a keyword as terminal proof:** creates false halts when an agent quotes
  the phrase and misses localized/reworded failures.
- **Assume the previous agent will return:** makes recovery depend on ephemeral
  conversational state and defeats relay handoff.
- **Store everything in the journal:** bloats the routing path and turns
  credentials/runtime noise into durable project data; large evidence stays in
  bounded referenced artifacts.

## 11. Acceptance criteria

1. Every problem-driven change maps to a ticket and minimum incident packet
   before or with its fix.
2. The packet contains reproduction, causal root, negative controls, and an
   executable anti-recurrence guard.
3. Fixtures are placeholder-only and inject unstable host/runtime boundaries.
4. Deterministic impossibilities fail fast; ambiguous evidence remains unknown
   or retryable under the governing contract.
5. A fresh agent reconstructs state and cause from the §5 durable set without
   chat, memory, live processes, credentials, or shell history.
6. Running the documented recovery twice converges or safely no-ops/refuses
   before mutation.
7. Newly discovered independent causes receive separate incident units.
8. Review and final delivery cite raw/retrievable evidence and satisfy RFC 065;
   no local-only checkpoint is reported as shipped.
9. The policy remains passive, vendor-neutral, Python-version-neutral, and
   compartmentalized.
