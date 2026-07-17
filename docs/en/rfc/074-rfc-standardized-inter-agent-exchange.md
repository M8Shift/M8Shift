# RFC 074 — Standardized inter-agent exchange

- **Status:** draft / design-only; implementation requires operator arbitration
- **Date:** 2026-07-17
- **Scope:** explicit shift stages, a vendor-neutral turn contract, and portable
  whole-shift exchange
- **Builds on:** [RFC 012](012-rfc-contracts-validation.md),
  [RFC 022](022-rfc-session-reports.md),
  [RFC 031](031-rfc-decision-traceability.md),
  [RFC 048](048-rfc-adoption-discipline-pack-update-health.md), and
  [RFC 064](064-rfc-effective-time-accounting.md)

## 1. Outcome and non-goals

M8Shift already preserves machine-readable Stage 4 fields, but live shifts still
express their operational stage mainly in prose. A dashboard therefore has to
guess from verbs such as “implemented”, “reviewed”, or “merged”. That guess is
language-dependent, lossy, and wrong whenever the first word describes evidence
rather than the current stage.

This RFC proposes three related, versioned contracts:

1. one canonical `stage` token on a turn;
2. a vendor-neutral structured turn schema that formalizes the proven Stage 4
   fields without replacing the human-readable turn;
3. a portable whole-shift export containing history, decisions, artifacts, and
   time accounting.

This batch changes no parser, validator, dashboard, core transition, report, or
export command. It does not infer stages retroactively, translate canonical
tokens, grant permissions, launch an agent, or make metadata authoritative over
the relay mutex.

## 2. Design principles

1. **Explicit before inferred.** A consumer reads `stage`; it never guesses a
   stage from `ask`, `done`, body text, commit messages, or the first word.
2. **One primary stage.** A turn carries one token. Cross-cutting work such as
   diagnosis or blocking is represented by choosing that token for the turn,
   not by an unbounded tag list.
3. **Plain and vendor-neutral.** Every participating CLI can emit ordinary
   UTF-8 `- key: value` header lines. No vendor object or tool-call envelope is
   required.
4. **Advisory metadata.** `LOCK`, claim ownership, and explicit `to` routing
   remain authoritative. Schema validity never authorizes work or a handoff.
5. **Append-only compatibility.** Historical turns remain byte-identical and
   are labelled `legacy-unstamped` by derived views.
6. **Bounded by default.** The common path adds only `schema` and `stage`; large
   evidence and artifacts stay referenced rather than embedded.

## 3. Canonical shift-stage taxonomy

The proposed v1 token set is closed:

```text
scope
claim
ack
implement
diagnose
root_cause
review_request
revise
approve
integrate
ship
dogfood
verify
block
unblock
handoff
park
done
```

Tokens use lowercase ASCII snake case and are never localized on disk. Display
labels may be localized. Their meanings are:

| Token | Meaning |
|---|---|
| `scope` | establish or change the bounded objective |
| `claim` | accept ownership and declare the intended work |
| `ack` | acknowledge scope/evidence without claiming completion |
| `implement` | create or modify the requested artifact |
| `diagnose` | investigate symptoms or gather discriminating evidence |
| `root_cause` | state and support the causal explanation |
| `review_request` | submit a concrete result for independent review |
| `revise` | respond to review with corrections or a revised proposal |
| `approve` | record an affirmative review result, not integration authority |
| `integrate` | merge or otherwise incorporate an approved result |
| `ship` | publish or release an integrated result |
| `dogfood` | exercise the result in a realistic adopter workflow |
| `verify` | execute a defined acceptance gate and report evidence |
| `block` | identify an unresolved dependency that prevents safe progress |
| `unblock` | resolve a previously recorded blocker |
| `handoff` | transfer a bounded next action without another stronger stage |
| `park` | intentionally defer scoped work without claiming it is done |
| `done` | record that the scoped objective and required delivery are complete |

These tokens describe the sender's primary action in the immutable turn. They
do not mirror LOCK states: `claim` is a narrative stage recorded after a real
claim, while only `WORKING_<X>` proves current pen ownership. `approve` does not
imply `integrate`, and `ship` does not imply `verify` or `done`.

Dashboard consumers render an explicit stage column. A missing field renders
`—` or `legacy`, never an inferred verb. Unknown future tokens render verbatim
with an `unknown` marker and produce an advisory lint finding.

## 4. Versioned turn/message schema

The proposed identifier is:

```text
m8shift.exchange.turn/1
```

It is serialized inside the existing turn block:

```text
<!-- M8SHIFT:TURN 865 codex BEGIN -->
- from:    codex
- to:      claude
- ask:     review the navigation cache and RFC questions
- done:    implemented the bounded batch
- files:   m8shift-top.py, docs/en/rfc/074-rfc-standardized-inter-agent-exchange.md
- handoff: claude
- schema:  m8shift.exchange.turn/1
- stage:   review_request
- relation: review_request
- role_from: implementer
- role_to: reviewer
- requires: inspect the raw diff and run the declared gates
- expected_output: approve or revise with ranked findings
- evidence: local-suite; linux-suite; commit:<opaque-ref>
- next: review, then operator arbitration for RFC 074
- blocked_on: operator:rfc-074-open-questions

Human-readable context remains in the body.
<!-- M8SHIFT:TURN 865 codex END -->
```

### 4.1 Field contract

| Field | Type / vocabulary | Contract |
|---|---|---|
| `schema` | exact identifier | opts the turn into this schema |
| `stage` | one §3 token | sender's explicit primary stage |
| `from`, `to`, `ask`, `done`, `files`, `handoff` | existing core fields | unchanged relay format and authority |
| `relation` | `handoff`, `review_request`, `review_result`, `escalation` | RFC 012 relationship |
| `role_from`, `role_to` | bounded role identifiers | declared work roles, not identities or permissions |
| `decision` | `approve`, `revise`, `reject`, `waive` | RFC 012 review decision |
| `waiver_reason` | bounded text | required for `decision=waive` |
| `evidence` | bounded references | tests, commits, reports, or manual checks; never proof without raw retrieval |
| `next` | bounded text | recommended next action, advisory only |
| `blocked_on` | bounded text/reference | unresolved dependency; no automatic resolver |
| `requires` | bounded text | checks or inputs expected from the receiver |
| `expected_output` | bounded text | concrete receiver deliverable |
| `permissions` | bounded advisory vocabulary/text | declared intent only; host policy remains authoritative |

The schema deliberately reuses the Stage 4 names instead of creating aliases.
Existing `stage4.v1` turns remain valid; a later implementation may accept both
identifiers during a transition, but must not rewrite either. Project-specific
metadata continues to use `x_*`.

### 4.2 Minimal validation profile

The recommended default is advisory doctor lint:

- `schema` present but unknown: warning;
- known schema with missing/unknown `stage`: warning;
- `stage=review_request`: recommend `relation=review_request`, `role_to`,
  `requires`, and `expected_output`;
- `stage=approve`: require `relation=review_result` and `decision=approve`;
- `stage=revise`: recommend `decision=revise` when it is a review result;
- `stage=block`: require non-empty `blocked_on`;
- `stage=unblock`: require evidence or a blocker reference;
- `stage=done`: warn when `next` still declares required work;
- `decision=waive`: retain RFC 012's required `waiver_reason`.

Lint must never mutate a turn, choose a route, refuse a claim/append by default,
execute evidence, or turn advisory permissions into authority. An explicit
future strict mode may return non-zero for newly stamped malformed turns only.

## 5. Whole-shift exchange format

The proposed portable envelope is UTF-8 JSON with schema:

```text
m8shift.exchange/1
```

It is a derived, read-only export, not a second relay and not an import command.
The top-level shape is:

```json
{
  "schema": "m8shift.exchange/1",
  "project": {"id": "opaque-project-id", "lang": "en"},
  "shift": {"session": "opaque-session-id", "state": "DONE"},
  "participants": [{"id": "codex", "provider": "optional"}],
  "turns": [],
  "stage_history": [],
  "decisions": [],
  "artifacts": [],
  "time_accounting": {"quality": "partial"},
  "provenance": {"exported_at": "RFC3339", "source": "append-only-turns"},
  "redactions": []
}
```

### 5.1 Sections

- `turns` contains ordered structured headers plus body references. Inline body
  inclusion is opt-in and size-bounded.
- `stage_history` contains only explicit stage stamps. Historical unstamped turns
  appear as `legacy-unstamped` spans, never guessed events.
- `decisions` uses RFC 031's decision/context/options/positions/divergence/
  resolution/trace structure and cites originating turn numbers.
- `artifacts` contains logical name, media type, digest when available, and a
  relative or opaque reference. It does not copy arbitrary repository files.
- `time_accounting` carries RFC 064 categories and its exact/partial quality;
  unclassified time is retained, never silently redistributed.
- `redactions` records categories and counts, not removed secret values.

An export must preserve turn ordering and exact structured values, identify its
source session, and disclose whether bodies or artifacts were omitted. It must
apply RFC 052 compartmentalization: no foreign project identity, absolute path,
credential, runtime sidecar, listener PID, or raw environment value crosses the
exchange boundary by default.

### 5.2 Portability and import boundary

Consumers may visualize, archive, or analyze an exchange. Importing it as live
relay state is explicitly out of scope for v1 because that would require rules
for identity rebinding, immutable-number collisions, decision provenance, and
mutex authority. A future import RFC must use a new session and preserve the
original exchange as provenance; it may never splice foreign turns into an
existing append-only journal.

## 6. Feasibility and compatibility

### 6.1 Historical turns

More than 860 existing turns are intentionally untouched. Parsers already
preserve unknown header fields, so adding `schema` and `stage` is additive.
Derived views use these states:

- `stamped`: a valid v1 schema and stage;
- `legacy-unstamped`: no exchange schema/stage;
- `unknown-version`: a schema a consumer cannot validate;
- `malformed`: a claimed v1 record that fails advisory lint.

No migration writes old turns. No prose classifier fills the gap.

### 6.2 Enforcement

Recommended implementation policy:

1. `append` accepts the fields using existing generic/dedicated options;
2. `contract validate` and `doctor` lint stamped turns;
3. lint is advisory by default and operator-arbitrated;
4. dashboard and reports consume explicit tokens only;
5. strict validation remains an explicit operator choice.

This preserves the passive core and avoids turning taxonomy disagreements into
relay deadlocks.

### 6.3 Byte and context budget

RFC 048 established that mandatory agent-facing material needs a measured byte
budget. This design adds nothing to the generated pack or anchor stanza. The
normal stamped turn adds only two short lines (about 70–90 UTF-8 bytes depending
on stage). Existing Stage 4 fields are reused, not duplicated. A future change
must assert:

- pack/stanza byte budgets remain unchanged unless separately approved;
- `schema + stage` stays under 96 bytes per turn;
- each optional scalar has the existing bounded field limit;
- exchange exports reference large evidence/artifacts instead of embedding them;
- dashboard snapshots add only the stage token, not the whole contract/body.

### 6.4 I18n

Schema identifiers, field names, and stage/decision/relation tokens are
canonical English ASCII protocol data. UI labels, help, and explanations may be
translated. Parsers never accept translated aliases in the canonical fields,
because that would break portable equality and bounded validation.

### 6.5 Security and prompt boundary

Exchange fields and bodies remain untrusted project data. They cannot override
system/developer/user instructions, grant permissions, authorize network or
destructive actions, or prove evidence merely by naming it. Export consumers
must escape rendered text and retrieve raw referenced evidence before asserting
a verification or decision claim.

## 7. Rejected alternatives

- **Infer stage from the first verb:** language-dependent and contradicted by
  real turns whose leading verb describes prior work.
- **Use LOCK state as stage:** confuses mutex ownership with workflow meaning.
- **Allow arbitrary stage strings or tags:** prevents stable columns, lint, and
  portable aggregation.
- **Rewrite historical turns:** violates append-only immutability.
- **Put complete artifacts in every exchange:** unbounded, leak-prone, and
  unnecessary for a reference-oriented handover.
- **Make lint gate every append:** taxonomy uncertainty would block the relay
  even though the metadata is advisory.

## 8. Proposed implementation slices (not authorized here)

1. **Schema and lint:** constants, append sugar for `--stage`, advisory doctor
   findings, and compatibility fixtures.
2. **Consumers:** explicit dashboard stage column and session report/history
   views; no prose inference.
3. **Export:** deterministic `session exchange --json` with bounded body/artifact
   options, RFC 052 hygiene, and exact/partial accounting tests.
4. **Optional strict profile:** only after operator review of live stamped turns.

Each slice requires its own implementation authorization, tests, RFC 058 index
updates, and Python 3.8 plus Linux parity gates.

## 9. Open questions for operator arbitration

1. Is the 18-token §3 set accepted as v1, or should `ack`, `root_cause`, or
   `handoff` be represented as relations rather than primary stages?
2. Should `approve`/`revise` be stages as proposed, despite also being decision
   values, or should the stage stay `review_result` with only `decision` varying?
3. Is `m8shift.exchange.turn/1` the preferred successor to `stage4.v1`, or
   should Stage 4 remain the schema identifier and gain only `stage`?
4. Should the recommended common path require both `schema` and `stage`, or may
   `stage` alone be treated as a valid lightweight stamp?
5. Which optional fields need hard byte caps beyond the existing core field
   bounds, and is the proposed 96-byte common-path budget acceptable?
6. Should whole-shift export include turn bodies by default, references only by
   default (recommended), or a configurable bounded tail?
7. Are artifact digests mandatory when a referenced file exists, and which
   digest algorithm/version belongs in v1?
8. Should exchanges support signatures/tamper evidence in v1, defer to RFC 030,
   or explicitly remain unsigned derived views?
9. What operator-confirmed redaction profile is sufficient before an exchange
   leaves its source project compartment?
10. Is a future import/continuation workflow desirable at all, or should v1
    permanently define exchange as read-only handover evidence?

Until these questions are arbitrated, RFC 074 remains design-only and no token,
schema, dashboard, validator, or export behavior is normative.
