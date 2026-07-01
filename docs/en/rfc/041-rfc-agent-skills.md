# RFC 041 — Agent Skills: reusable multi-agent competency definitions

- Status: draft
- Target stage: repository artifact (`skills/`) + curated docs; optional argv-only verification (Phase 2)
- Builds on: [RFC 003 i18n packs](003-rfc-i18n-packs.md) (EN-only convention), the `agents-guide.md` collaboration contract
- Related: [RFC 032 tiered delegation](032-rfc-tiered-delegation.md) (a delegated sub-agent can be handed a skill), [RFC 039 model/task routing](039-rfc-model-task-routing.md) (routing "skills" = capability tags — a **different** concept, see §Positioning), [RFC 034 companion adapter interface](034-rfc-companion-adapter-interface.md) (the argv-only runner reused by optional Phase-2 hooks)
- Date: 2026-07-01
- Origin: operator request — codify the recurring competencies used to build M8Shift so any agent can load them consistently. Scope chosen by the operator: **hybrid, docs-first**.

## Summary

Building M8Shift exercises the same competencies on every cycle — adversarial
verify-as-authority, RFC review/placement, the release + dogfood cadence, the
forge workflow, identity hygiene, relay pen-discipline, token-economy, the
decision/issue templates. Today they live implicitly in `agents-guide.md` prose,
in memory, and in habit. This RFC makes them **first-class, reusable, generic,
multi-agent artifacts**: a `skills/` directory of declarative **skill
definitions** any agent (Claude, Codex, or a future one) can load to work
consistently, and which a pen-holder can hand to a delegated sub-agent (RFC 032).

The chosen shape is **hybrid, docs-first**:

- **Phase 1** — each skill is a declarative markdown file (front-matter + body)
  plus a machine-readable `skills/index.json`. Pure stdlib-friendly context; no
  execution. This is the whole feature's value floor.
- **Phase 2 (optional, later)** — a skill may declare an **argv-only
  verification hook** run through the existing RFC 034 adapter runner (advisory,
  read-only, no network, no daemon), so "is this skill's done-criteria met?" can
  be machine-checked without a new runtime.

## Motivation

The relay already coordinates *who writes when*. It does not capture *how each
kind of work is done well*. That knowledge is re-derived every session and drifts
between agents. Consequences:

- Inconsistency — one agent runs an adversarial hunt before approving, another
  eyeballs a diff; one deletes merged branches on both remotes, another forgets.
- Onboarding cost — a new agent (or a delegated sub-agent under RFC 032) has no
  compact, loadable statement of the expected competency.
- Lost provenance — the *why* of a competency (e.g. "hold the hunt as authority")
  lives in habit, not in a referenceable artifact.

Writing each competency once, in a stable place, makes exchanges cheaper and the
work reproducible — the same reason M8Shift externalizes state into files.

## Positioning — three "skill-like" things, kept distinct

| Concept | Where | What it is |
|---------|-------|-----------|
| **Skill definition** (this RFC) | `skills/` | *How* to perform a recurring competency well — steps, checklist, done-criteria |
| **Routing skill / capability tag** ([RFC 039](039-rfc-model-task-routing.md)) | routing manifests | A *requirement* label used to pick an eligible model (min/optimum/downgradable) |
| **`agents-guide.md`** | `docs/en/` | The curated human entry point to collaboration + the quality bar |

Relationship: **`skills/` is the source of truth for competencies; `agents-guide.md`
becomes a curated index that links to them** (it stops duplicating the detail).
RFC 039 capability tags are orthogonal — a routing skill answers "which model,"
a skill definition answers "how to do the work"; they cross-reference, they do
not merge. Under RFC 032, a pen-holder delegating a sub-task can pass the
relevant skill id so the sub-agent inherits the competency.

## Skill definition format (Phase 1)

A skill is a markdown file `skills/<id>.md` with YAML front-matter:

```markdown
---
id: adversarial-verify
title: Adversarial verify-as-authority
applies_to: [any]            # agent ids or roles, or "any"
triggers:                    # when to load/apply this skill
  - "before APPROVE/merge of a security-sensitive change"
  - "verifying another agent's implementation handoff"
references:                  # RFCs / docs / memories that ground it
  - docs/en/agents-guide.md
tags: [review, security, verification]
verification:                # optional; Phase 2 (argv-only, advisory)
  adapter: null
---

## Purpose
One paragraph: what competency this encodes and why it matters.

## Steps
1. …
2. …

## Checklist
- [ ] …

## Done criteria
A short, checkable statement of "this skill was satisfied".

## Anti-patterns
What NOT to do (the failure modes this skill exists to prevent).
```

`skills/index.json` (`m8shift.skills.index.v1`) lists every skill for machine
discovery: `id`, `title`, `applies_to`, `tags`, `path`, and `has_verification`.

## Initial skill set (distilled from the recurring processes)

| id | Competency |
|----|-----------|
| `adversarial-verify` | Spawn an independent hunt to *refute* a change; hold it as authority before APPROVE; reproduce the vector before returning it |
| `rfc-review-and-place` | Ground an external/draft RFC against the charter + shipped code (multi-lens), re-architect, place, cross-reference, hand impl to another agent |
| `release-and-dogfood` | Merge-when-stable → tag → push forge-first then GitHub → **delete branch on both remotes** → **promote/dogfood the relay engine** → refresh docs + site |
| `forge-workflow` | issue (template) → branch → MR (`Closes #N`) → independent review → merge → delete-both-remotes → close (template) |
| `identity-hygiene-scrub` | Deny-list scan of every added line before commit; keep the public identity scrubbed; never persist secrets to a file |
| `relay-pen-discipline` | `claim → work → append`; `guard` before any write; keep `wait` armed until DONE; never bounce unread work |
| `token-economy` | Route scans through RTK when present; compress/reference bulk (RFC 037); never starve verification |
| `decision-and-issue-templates` | Use the decision template for choices, the create/close issue templates systematically; record provenance (Agent-Model + version) |
| `site-update-report` | On any site-touching close: list pages updated **and** pages that should have been updated, plus a synthesis |
| `multi-os-portability` | Install/scripts must run on Git Bash/Windows + Linux + macOS; list prerequisites in installer + site + docs |

## Phase 2 (optional, later) — argv-only verification hooks

A skill may set `verification.adapter` to an RFC 034 adapter manifest
(`doctor_check` type). The hook runs **argv-only, read-only, advisory** through
the existing `run_adapter_process` runner (no network, no daemon), returning a
pass/finding for the skill's done-criteria — e.g. `release-and-dogfood` can check
that the newest tag equals the promoted relay-engine `--version`. Verification is
never mandatory and never blocks the core relay.

## Charter constraints

stdlib-only · no daemon · no network · advisory. Phase-1 skills are declarative
context files. Phase-2 hooks reuse the RFC 034 argv-only, identity-pinned,
output-capped, fail-closed runner. Skills are EN-only (RFC 003 convention). The
core relay does not read `skills/`; agents do.

## Implementation phases

- **Phase A** — the format, `skills/` dir, `skills/index.json`, and the initial
  skill set above (docs only). Link from `agents-guide.md`; the guide becomes the
  curated index and stops duplicating the detail.
- **Phase B** — a tiny stdlib `skills` lister/validator (optional companion
  surface or a `scripts/` check) that validates front-matter + index consistency;
  read-only.
- **Phase C (optional)** — the Phase-2 argv verification hooks for skills whose
  done-criteria are machine-checkable.

## Acceptance criteria

1. `skills/` exists with the initial skill set and a valid `skills/index.json`.
2. Each skill has purpose · steps · checklist · done-criteria · anti-patterns.
3. `agents-guide.md` links skills as the source of truth (no duplication).
4. Relationship to RFC 039 (routing capability tags) and RFC 032 (delegation) is
   stated; skills are EN-only; charter-pure.
5. Any Phase-2 hook is argv-only, advisory, and reuses the RFC 034 runner.

## Open questions

- Skill body as markdown-only, or markdown + a machine `steps` array (for
  programmatic consumption)?
- Should `skills/index.json` be generated from the front-matter (single source)
  or hand-maintained with a validator?
- Do we ship per-agent skill *overrides* (like `AGENTS.override.md`), or keep
  skills global with `applies_to` filtering?

## Non-goals

Executable/invokable skill modules or a plugin runtime; a daemon or network
service; replacing `agents-guide.md` (it becomes the curated index); merging with
RFC 039 routing capability tags; per-model prompt engineering.
