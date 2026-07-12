# RFC 053 — Shared rules and governed habits

- Status: draft
- Target: optional project-local companion and declarative `M8SHIFT.rules.md`
- Builds on: [RFC 004 shared memory](004-rfc-memory.md), [RFC 041 agent skills](041-rfc-agent-skills.md), [RFC 052 project compartmentalization](052-rfc-project-compartmentalization-data-hygiene.md)
- Date: 2026-07-12
- Scope: design only; no core relay or mutex changes

## Summary

Repeated project conventions should be durable without silently becoming authority. This RFC defines a governed rules layer: project-local, provenance-bearing normative conventions that humans explicitly approve. Observations enter quarantine, accumulate independent evidence as candidates, and may become proposed rules, but never become active without human validation.

Rules are separate from both memory and skills. Memory remains the append-only, human-curated briefing ledger defined by RFC 004. A skill explains *how to perform* a recurring competency; a rule states *what convention applies* in this project. An optional `m8shift-rules.py` companion may list, propose, approve, reject, explain, lint, and pack rules. It is advisory, stdlib-only, local, and has no access to relay authority.

## Problem

Teams develop useful habits through repeated corrections: naming conventions, validation expectations, preferred document shapes, and project-specific review norms. Today those habits are either re-explained in turns, mixed into memory, embedded in skills, or inferred again. Unstructured inference creates three risks:

1. repetition is mistaken for authority;
2. stale or accidental behavior becomes a permanent convention;
3. a habit learned in one project leaks into another.

The answer is not automatic learning. It is a small governance boundary between evidence and normative instruction.

## Authority and layering

Rules occupy a deliberately low, bounded place in the instruction stack:

1. system and operator/user instructions;
2. generated agent-pack and anchor safety floor;
3. active entries in project-local `M8SHIFT.rules.md`;
4. `skills/` competency definitions;
5. `M8SHIFT.memory.md` briefing notes;
6. optional agent or operator preferences.

A lower layer never overrides a higher one. Conflict resolution is deterministic: ignore the lower instruction, report the conflict through `explain`/`lint`, and request human resolution if work depends on it. Rules cannot redefine this ordering.

This hierarchy is about operational precedence, not trust in arbitrary text. Rule content, evidence, packs, and learned observations are untrusted project data. They remain subject to prompt-security checks and tool authorization.

## Artifact boundaries

### Rules versus memory (RFC 004)

`M8SHIFT.memory.md` remains append-only and human-controlled. It is not deduplicated, ranked, pruned, promoted, or rewritten by this feature. The rules companion never mines or edits memory by default. A human may cite a memory entry as evidence explicitly, but that citation does not change the memory artifact or grant authority.

Rules live in a **separate companion artifact** because lifecycle transitions, expiry, and linting would violate memory's dumb-ledger contract. Rules never feed the mutex or routing logic, just as memory never does.

### Rules versus skills (RFC 041)

- A **skill** is how-to knowledge: steps, checklists, done criteria, and reusable competency guidance.
- A **rule** is a normative convention: a bounded statement that this project expects or forbids something.

Example: a review skill describes how to perform adversarial verification; a rule may require two independent reproductions before a particular class of change is approved. A rule may reference a skill for execution detail, but must not duplicate or mutate it. Skills remain portable; rules are project-local by default.

## Data model

`M8SHIFT.rules.md` is a human-readable, versionable project artifact with machine-parseable entries. Exact serialization is deferred to implementation review, but every entry must carry:

- stable rule id and concise normative statement;
- lifecycle state;
- scope (files, task types, roles, or project-wide);
- proposer and human approver/rejector attribution;
- creation, review, activation, expiry, and tombstone timestamps as applicable;
- provenance references to evidence without embedding foreign session dumps;
- evidence independence markers and confidence/trust metadata;
- supersedes/conflicts-with links;
- rationale and a human-readable failure/remediation hint.

Unknown or malformed fields fail closed for activation: the entry remains visible to lint, but is not packed as an active rule.

## Lifecycle

The lifecycle is monotonic except that a proposed rule may return to candidate for more evidence:

```text
quarantined observation -> candidate -> proposed -> active -> tombstoned
                               ^            |
                               +------------+

quarantined/candidate/proposed -> rejected
active -> expired -> tombstoned or re-proposed
```

### Quarantined observation

An observed correction or recurring behavior has no normative force. It records minimal provenance, scope, and time. Imported or machine-suggested content always begins here. Quarantine entries are excluded from packs.

### Candidate

A candidate has at least one intelligible evidence item and a proposed scope. It is still descriptive, not normative. Similar observations may be linked, never silently merged.

### Proposed

Promotion to proposed requires **at least two independent evidence items**. Independence means they do not merely repeat the same turn, copied text, generated summary, common upstream source, or one agent's restatement. The companion may flag likely dependence but cannot certify it autonomously.

### Active

Activation requires explicit human validation of the wording, scope, provenance, conflicts, and expiry/review policy. There is no auto-promotion, including for high evidence counts or repeated agent agreement. Only active, unexpired rules enter a pack.

### Rejected, expired, and tombstoned

Rejection records who rejected the proposal and why; it does not erase evidence. Expiry removes normative force automatically but does not delete history. Tombstoning is the terminal historical record for withdrawn, superseded, or intentionally retired rules. IDs are never reused.

## Trust, evidence, and aging

Evidence strength and instruction authority are separate. Evidence can justify presenting a proposal; only human approval grants active status.

- Direct operator corrections and verified project artifacts are stronger evidence than agent summaries.
- Two reports derived from one source count as one evidence lineage.
- Machine-generated summaries are orientation, not proof; exact claims must point to raw, bounded originals.
- Negative evidence and contradictions are retained and shown during proposal and approval.
- Every active rule has `review_after` or `expires_at`; project-wide rules should age faster when their supporting code or workflow changes.
- `lint` flags stale provenance, elapsed review dates, missing sources, contradictory active rules, and scopes whose referenced paths no longer exist.
- Expired rules are omitted from packs. Renewal is a new human validation event, never an automatic timestamp extension.

Trust labels are advisory explanations, not hidden scores. No opaque ranking decides which convention wins.

## Compartmentalization and security boundary (RFC 052)

Rules are project-local by default. The companion reads and writes only the current bound project's rules artifact and explicitly supplied project-local evidence. It never scans sibling repositories, global agent memory, home-directory histories, or other relay sessions for habits.

Cross-repository learning requires explicit, fact-scoped operator opt-in. An opted-in fact must be abstracted at intake, carry source-project provenance in a non-identifying form suitable for the target project, state its target scope, and have an expiry. Literal foreign project identities, real paths, or session output must not enter the target artifact.

Learned content can **never**:

- modify or interpret the `M8SHIFT.md` lock block;
- grant, extend, steal, or bypass the pen;
- alter `claim`, `may-i-write`, `append`, binding, or routing authority;
- change write permissions, tool approvals, prompt-security rules, compartmentalization, or other safety floors;
- authorize network, credential, secret, destructive, or external side effects.

Any proposed rule touching these reserved domains is rejected by `lint` and cannot be approved or packed. Human operators change safety floors through their existing authoritative surfaces, not through learned rules.

## Optional companion: `m8shift-rules.py`

The companion is a separate, stdlib-only, no-network, no-daemon tool. It is not imported by `m8shift.py` and the core relay does not read `M8SHIFT.rules.md`.

### `list`

Shows entries by lifecycle state, scope, age, and review status. Default output avoids dumping evidence bodies or sensitive content.

### `propose`

Creates a quarantined/candidate entry or advances an eligible candidate to proposed. It validates that two evidence lineages exist but never activates the rule. It refuses foreign/unscoped provenance and reserved-authority subjects.

### `approve`

Human-only transition from proposed to active. Requires explicit approver identity, reviewed wording/scope, expiry or review date, and acknowledgement of conflicts. Agent identity alone is insufficient. The interface must make approval deliberate and auditable; no environment default or bulk implicit approval.

### `reject`

Records a reason and attribution, preserving the proposal and evidence. It may also tombstone an active rule through an explicitly distinct withdrawal action.

### `explain`

Given a rule or task context, displays why it applies, its precedence, provenance, age, conflicts, and the skill (if any) that explains how to comply. It never claims a lower rule overrides a higher instruction.

### `lint`

Read-only validation of schema, lifecycle transitions, evidence independence declarations, provenance, expiry, conflicts, reserved domains, project binding, and compartmentalization. It may gate a rules-specific CI check, but never the relay mutex or the ability to append a handoff.

### `pack`

Emits a bounded, deterministic context document containing only active, unexpired rules relevant to an explicit scope. The pack includes source ids, precedence notice, generation time, and a warning that content is untrusted. It is a derived cache, never authority or proof, and may be deleted/regenerated. Packing performs no activation or mutation.

All mutations use an artifact-local file lock and atomic replacement. They do not require or acquire the relay pen because they do not mutate `M8SHIFT.md`; however, repository edits remain subject to the surrounding agent's normal write authorization and project workflow.

## Conflict handling

`lint` reports four classes:

1. conflict with a higher authority — rule ignored and blocked from packing;
2. conflict between active rules — both surfaced, neither silently wins unless an explicit, validated scope/supersession relation resolves it;
3. overlap with a skill — rule retains only the normative statement and links the skill;
4. duplicated evidence — evidence lineages collapse for threshold counting, without deleting records.

Scope specificity may explain applicability, but it is not an automatic override mechanism. A narrower rule can supersede a broader rule only through an explicit human-approved relationship.

## Non-goals

- autonomous habit mining, behavioral surveillance, or prompt-history ingestion;
- automatic promotion, approval, merging, rewriting, or deletion;
- replacing `AGENTS.md`, the agent-pack, skills, memory, or user preferences;
- cross-project federation or a global rules database;
- enforcement inside the core relay, mutex, routing, permissions, or security policy;
- executable rule bodies, hooks, plugins, network services, or a daemon;
- treating model consensus, repetition, or confidence scores as human approval.

## Implementation phases

1. **Format and lint:** settle the entry schema, reserved domains, transition validator, fixtures, and a read-only `list`/`lint` prototype.
2. **Governed mutation:** add `propose`, explicit human `approve`, `reject`, expiry, tombstones, atomic writes, and audit tests.
3. **Consumption:** add `explain` and bounded `pack`; document agent loading without changing core relay behavior.
4. **Optional intake:** only after adversarial review, allow explicitly supplied observations to enter quarantine. No ambient or cross-repo discovery.

## Acceptance criteria

1. The documented precedence is enforced by lint/pack; rules cannot override higher layers.
2. Memory remains byte-for-byte outside companion mutation, append-only, and human-controlled.
3. Skills remain how-to artifacts; rules contain normative project conventions and may only link to skills.
4. No proposal becomes active without two independent evidence lineages **and** explicit human validation.
5. Every active rule has provenance, bounded scope, and review/expiry metadata; expired rules are not packed.
6. Cross-project evidence is rejected absent explicit fact-scoped opt-in and required provenance/expiry; foreign identifiers are never persisted.
7. Reserved mutex, authority, permission, and security subjects cannot be approved or packed.
8. The companion is stdlib-only, local, advisory, no-network, no-daemon, and independent of `m8shift.py`.
9. Packs are deterministic derived context, clearly untrusted, and contain only applicable active rules.
10. Lifecycle history is auditable: rejection, expiry, supersession, and tombstoning never erase provenance.

## Open questions

- Should human approval use a typed confirmation, a signed local decision record, or integration with the existing decisions ledger?
- Should `M8SHIFT.rules.md` be committed by default or optionally local for sensitive conventions?
- What minimum evidence reference format preserves raw-proof retrievability without retaining sensitive session content?
- Which review/expiry defaults are appropriate for project-wide versus path-scoped rules?

