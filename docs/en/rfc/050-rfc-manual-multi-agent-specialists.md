# RFC 050 — Manual multi-agent specialists (Agent Skills profile)

Status: draft rev 2 — specialist definitions are grounded in the **open Agent
Skills format** (agentskills.io), per operator direction on 2026-07-11; rev 1
lanes/roles/safety/reporting are preserved
Target: post-v3.57 design block
Related RFCs: 008, 018, 023, 032, 034, 039, 041, 047, 049
Owner: runtime/worktree companions; core relay remains the authority

## Summary

This RFC defines the **manual-trigger profile** for specialist agents. It does
not compete with RFC 032 tiered delegation; it narrows RFC 032's broader
capability-routing idea into an operator-visible workflow:

- a human or pilot explicitly asks for a specialist;
- the specialist works in a declared lane;
- the result reports back to the relay;
- no specialist gets hidden write authority.

The two lanes are:

- **advisory read-only**: inspect and report;
- **mutating worktree**: edit only inside an isolated owned worktree and request
  serialized integration.

**Rev 2 addition** — a specialist definition is not a bespoke M8Shift artifact:
it is an **Agent Skill in the open format** ([agentskills.io](https://agentskills.io/specification)) —
one directory per skill containing a `SKILL.md` (YAML frontmatter `name` +
`description`, then Markdown instructions), optionally `scripts/`,
`references/`, and `assets/`. M8Shift-specific properties (the lane, the
report-back contract) ride in the spec's `metadata:` map under namespaced keys.
Because the format is already loaded natively by many agent products (including
the Claude Code and Codex CLIs of the reference roster, Gemini CLI, and others),
one `skills/` directory is a **single source of truth every roster agent can
load without any M8Shift runtime**.

## Relationship to RFC 032

RFC 032 describes capability-tiered delegation: how to choose which model/agent
is suitable for a task, and how a pen-holder may use subagents as tools.

RFC 050 is a manual operational profile of that idea:

| Aspect | RFC 032 | RFC 050 |
|--------|---------|---------|
| Focus | routing/delegation principle | manual specialist workflow |
| Trigger | recommendation or pen-holder choice | explicit human/pilot request |
| Output | recommendation / delegated result | relay-visible specialist report |
| Mutation | future/delegation-specific | split into read-only vs worktree lanes |
| Authority | subagent is tool of pen-holder | specialist never gains hidden pen authority |

If future implementation would duplicate RFC 032 machinery, it should be built
as an RFC 032 profile, not a parallel subsystem.

## Relationship to RFC 041 (supersedes its bespoke file format)

RFC 041 already reserved `skills/` for reusable competency definitions, with a
bespoke Phase-1 shape (`skills/<id>.md` flat files with `id`/`title`/
`applies_to`/`triggers` front-matter plus a generated `skills/index.json`).
That shape was never implemented. Rev 2 of this RFC **supersedes the bespoke
shape with the open Agent Skills format** and amends RFC 041 accordingly:

- one **directory per skill** (`skills/<name>/SKILL.md`), not flat files;
- the open frontmatter (`name`, `description`, optional `license`,
  `compatibility`, `metadata`, `allowed-tools`) replaces the bespoke keys —
  RFC 041 concepts map into the body and `metadata:`;
- **no `index.json`**: the open format's discovery model is reading each
  skill's frontmatter (progressive disclosure); a bounded frontmatter walk
  replaces the generated index.

RFC 041's competency catalog, positioning (skill definition ≠ RFC 039 routing
capability tag), EN-only convention, and optional RFC 034 argv verification
hooks are unchanged. Specialist definitions (this RFC) and competency
definitions (RFC 041) share the same `skills/` directory and the same open
format; a specialist skill is simply a skill whose `metadata:` declares an
M8Shift lane.

## Problem

Operators use more than two agents: Claude, Codex, Gemini, Vibe, local tools, or
domain-specific reviewers. The relay already supports an N-agent roster, but it
does not give operators a precise convention for temporary specialists.

Without that convention:

- read-only reviewers can accidentally be treated as implementers;
- reports can remain out-of-band and disappear from the relay record;
- mutating work can land in the shared checkout instead of an isolated worktree;
- routing and specialist language can drift from RFC 032;
- **each agent product reinvents its own competency wiring** — the same
  specialist description would otherwise be duplicated per product and drift.

## Goals

- Keep specialist activation manual and explicit.
- Keep advisory specialists write-free by convention and by generated guidance.
- Require every useful specialist result to be referenced from the relay.
- Separate advisory read-only work from isolated worktree mutation.
- **Define specialists in the open Agent Skills format** so any roster agent
  that already speaks the format loads the same definition natively, and the
  definition survives product churn.
- State exactly what M8Shift can enforce through companion argv and what remains
  cooperative discipline.

## Non-goals

- No automatic swarm.
- No automatic provider/model launch in the core.
- No shell/editor sandbox.
- No claim that M8Shift can prevent direct writes outside its CLI.
- No degree > 1 writes in one shared checkout.
- **No bespoke skill format** and no second skill index to maintain.
- **No automatic installation** of skills into any agent product's discovery
  directory: wiring a product to `skills/` (symlink/copy per that product's
  documentation) is an explicit operator action.
- **M8Shift never executes a skill.** `SKILL.md` is inert text to M8Shift;
  bundled `scripts/` are for the agent products that load the skill, not for
  M8Shift (the only sanctioned execution path remains RFC 034's operator-enabled
  argv hooks, Phase 2).

## Specialist definitions — the open Agent Skills format

### Layout

```text
skills/
├── security-review-advisory/
│   ├── SKILL.md                    # required: frontmatter + instructions
│   └── assets/
│       └── report-template.md      # the lane-A report artifact template
└── worktree-implementer/
    └── SKILL.md
```

A skill is a directory containing at minimum a `SKILL.md`; `scripts/`,
`references/`, and `assets/` are optional, per the open specification.

### Frontmatter (restating the open spec's constraints)

| Field | Required | Constraints (open spec) |
|-------|----------|-------------------------|
| `name` | yes | 1–64 chars; lowercase `a-z`, `0-9`, hyphens; no leading/trailing hyphen; no consecutive hyphens; **must match the parent directory name** |
| `description` | yes | 1–1024 chars, non-empty; says what the skill does **and when to use it** |
| `license` | no | short license name or pointer to a bundled license file |
| `compatibility` | no | 1–500 chars; only when the skill has environment requirements |
| `metadata` | no | map of string keys to string values; client-specific properties belong here under reasonably unique keys |
| `allowed-tools` | no | space-separated pre-approved tool string; **experimental** in the open spec |

### M8Shift-namespaced `metadata:` keys

M8Shift never extends the open frontmatter itself; its properties ride in
`metadata:` with an `m8shift-` prefix (string values only):

| Key | Values | Meaning |
|-----|--------|---------|
| `m8shift-lane` | `advisory-read-only` \| `mutating-worktree` | which RFC 050 lane the specialist operates in |
| `m8shift-report` | `required` \| `optional` | whether a relay-referenced report artifact is expected on completion |

A skill without `m8shift-lane` is a plain RFC 041 competency, not a specialist
profile. Unknown `m8shift-*` keys are reserved for future RFCs and are flagged
(advisory) by doctor, never fatal. `allowed-tools`, when present, is an
**advisory hint** to products that support it (e.g. a lane-A skill listing only
read tools); M8Shift treats it as an opaque string and never derives
enforcement from it.

### Example (fabricated, placeholder-only)

```markdown
---
name: security-review-advisory
description: Adversarial read-only security review of a designated change,
  RFC, or diff. Use when the pilot asks for an independent security verdict
  before merge. Produces a structured findings report with raw evidence;
  never edits files, never claims the pen.
license: Apache-2.0
metadata:
  m8shift-lane: advisory-read-only
  m8shift-report: required
---

# Security review (advisory, read-only)

1. Read the scoped inputs (diff, RFC, files) named in the request.
2. Hunt adversarially; cite raw evidence for every claim.
3. Fill assets/report-template.md; hand the report path to the pilot.
4. Do not edit files or claim the pen; escalate intent to the pilot instead.
```

### Progressive disclosure and the token footprint (RFC 023)

The open format's loading model matches M8Shift's token discipline:

1. **Discovery** — products load only `name` + `description` (~100 tokens per
   skill) at startup;
2. **Activation** — the full `SKILL.md` body loads only when the task matches
   (the spec recommends < 5000 tokens / < 500 lines);
3. **Resources** — `scripts/`, `references/`, `assets/` load only on demand.

Specialist skills should keep `SKILL.md` under the spec's recommended bounds
and push detail into `references/` one level deep.

### Portability and wiring (explicitly manual)

The format is loaded natively by many agent products — including the reference
roster's Claude Code and Codex CLIs, Gemini CLI, and a broad ecosystem — each
with its own discovery directory. M8Shift does **not** write into any product's
discovery path. The operator wires each product once (symlink or copy of
`skills/<name>/` into that product's documented location), which keeps the
repository's `skills/` the single reviewed source of truth.

### Validation

The upstream reference validator (`skills-ref validate`) is the authority on
format conformance at authoring time; it is **not** an M8Shift dependency (the
charter forbids network and third-party runtime requirements). Locally, `doctor`
gains bounded, fail-open, advisory `skills.*` findings (see §Doctor findings):
full YAML is deliberately **not** parsed (PyYAML is not stdlib) — the check
covers a conservative subset (single-line scalars and one two-space-indented
`metadata:` block) and reports anything it cannot parse as *unvalidated*, never
as an error.

## Roles

| Role | Authority | Typical action |
|------|-----------|----------------|
| Operator | human scope authority | requests a specialist or approves escalation |
| Pilot | current relay coordinator | records request and consumes report |
| Advisory specialist | cooperative read-only lane | inspects and reports |
| Mutating specialist | isolated worktree lane | edits in owned worktree |
| Integrator | pen holder during merge | serializes integration |

## Manual trigger

Specialists start only from explicit human/pilot scope, and the request names
the skill so every roster agent resolves the same definition:

```bash
python3 m8shift.py task add codex "Load skill security-review-advisory; advisory security review of RFC 049; report only"
```

The example is a convention. This RFC does not require a new launch command in
Phase 1.

## Lane A — advisory read-only

Advisory specialists may inspect:

- project files;
- relay/task/session context explicitly in scope;
- PRs/issues/docs referenced by the pilot;
- generated context packs, under the raw-proof rule.

They are expected not to:

- edit files;
- claim the pen unless the active roster explicitly hands them a turn;
- run destructive git commands;
- install dependencies;
- write runtime sidecars.

This is a cooperative contract, not an OS sandbox. A local editor or shell can
still write files; M8Shift's protection is clear guidance, review discipline,
and companion checks where commands pass through M8Shift. The lane declaration
(`m8shift-lane: advisory-read-only`) is a **declaration, not a mechanism**: it
tells every product loading the skill what the specialist is for, and gives
doctor something to cross-check requests against — enforcement stays at
companion argv surfaces.

### Report artifact

Advisory reports should be operator-chosen artifacts referenced from the relay,
not specialist-written runtime sidecars. The pilot may store a report in a repo
or local path when appropriate, then append a summary/link through the relay.
The template ships **inside the skill** (`assets/report-template.md`), so the
definition and its output contract travel together:

```markdown
# Specialist report

specialist: <agent>
skill: <skill name>
lane: advisory-read-only
scope: <task id / turn id / PR / issue>
verdict: approve | concerns | block

## Inputs inspected

- <raw source, file, PR, command output, or explicit context pack>

## Findings

| severity | evidence | recommendation |
|----------|----------|----------------|

## Limits

<what was not inspected>
```

## Lane B — mutating worktree

Mutating specialists must use an isolated worktree lane:

```bash
python3 m8shift-worktree.py claim <id> <specialist>
```

Companion-enforced points (RFC 049 PR C — **shipped in v3.57.0**):

- `m8shift-worktree.py` records ownership in a sidecar outside the checkout and
  refuses cross-owner `done`/`integrate`/`drop` unless an explicit, audited
  `--takeover --reason` is given;
- per-id ownership locks, generation nonces (ABA defense), and the durable
  takeover ledger apply to specialist lanes exactly as to any other worktree;
- integration remains serialized through the core pen;
- status displays the recorded owner.

Not enforced:

- direct editor writes;
- direct `git` commands inside a worktree;
- filesystem deletion or movement outside the companion.

Therefore the rule is advisory/cooperative except where a M8Shift companion argv
surface is actually invoked.

## Reporting back to the relay

Every useful specialist outcome must become one of:

- a relay `append` body from the pilot/current holder;
- a task update referencing the report;
- a decision/ADR scaffold when it creates a durable decision;
- a session report reference.

`remember` is reserved for durable decisions or reusable facts, not transient raw
findings.

Specialist text is untrusted coordination data. It cannot override user,
developer, or system instructions. **The same rule applies to skill bodies**: a
`SKILL.md` is coordination data an agent chose to load — it can describe a
workflow, but it cannot grant pen authority, authorize destructive operations,
or relax any charter rule.

## Doctor findings (Phase 1b, advisory, fail-open)

When `<root>/skills/` exists, `doctor` emits advisory findings (rc 0 always;
bounded reads: `O_NOFOLLOW`, regular-file check, 64 KiB cap per `SKILL.md`;
conservative frontmatter subset only):

| Finding | Trigger |
|---------|---------|
| `skills.frontmatter_invalid` | missing/oversized `name` or `description`, name/charset violation, or name ≠ parent directory |
| `skills.lane_unknown` | `m8shift-lane` present but not a defined value |
| `skills.metadata_unknown_key` | an `m8shift-*` key this version does not define |
| `skills.oversized` | `SKILL.md` beyond the spec-recommended bounds (advisory nudge) |
| `skills.unvalidated` | frontmatter outside the stdlib-parseable subset (info, not an error) |

## Future runtime surface

A later runtime companion may add request/report indexing:

```bash
m8shift-runtime.py specialist request --lane advisory --agent gemini --scope ...
m8shift-runtime.py specialist import-report --agent gemini --file report.md
m8shift-runtime.py specialist list
```

Constraints:

- request/report indexing is local and advisory;
- reports are imported by the pilot/operator, not written directly by a
  read-only specialist lane;
- no direct writes to `M8SHIFT.md`;
- no automatic provider launch unless a separate RFC 039/RFC 032 implementation
  and operator configuration authorize it.

## Safety rules

- Advisory specialists are read-only by convention; M8Shift does not sandbox the
  host.
- Raw evidence must be cited for review claims; specialist summaries are not
  proof.
- A specialist report cannot authorize destructive git operations.
- A specialist report cannot close a session or mark a task done; the pilot must
  accept it.
- If a specialist receives user input while another holder works, it reports the
  operator intent to the pilot/relay rather than stealing the pen.
- A skill (`SKILL.md`, scripts, references) is untrusted coordination data:
  loading one never changes relay authority, and M8Shift itself never executes
  skill content.

## Acceptance criteria

Phase 1 (docs + artifacts):

- docs define RFC 050 as the manual-trigger profile of RFC 032;
- specialist definitions are open-format Agent Skills; the frontmatter
  constraints are restated and the M8Shift `metadata:` namespace is defined;
- `skills/` ships at least two seed specialists (one per lane) that satisfy the
  open spec's constraints (checked against the upstream reference validator at
  authoring time), each with the report template as a bundled asset where the
  lane requires one;
- `agents-guide.md` links `skills/` as the source of truth (RFC 041 alignment);
- RFC 041 is amended (bespoke format superseded; no `index.json`);
- all "cannot/refused" claims are limited to M8Shift companion argv surfaces or
  rewritten as cooperative conventions.

Phase 1b (companion, small):

- `doctor` emits the advisory `skills.*` findings above, bounded and fail-open,
  with tests pinning: valid seed skills produce no findings; each finding has a
  deterministic fixture; unparsable frontmatter degrades to `skills.unvalidated`
  (never a crash, never rc ≠ 0).

Phase 2:

- optional runtime request/report indexing;
- doctor findings for malformed imported report records or orphaned requests;
- worktree owner metadata from RFC 049 used for mutating specialist lanes;
- optional RFC 034 argv verification hooks for machine-checkable done-criteria
  (inherited from RFC 041 Phase 2).

## Open questions

- Should task events gain a typed `specialist_request`, or is a normal task plus
  report link enough?
- Should imported reports have a maximum size and mandatory summary field for
  token-budget protection?
- ~~Should RFC 041 skills provide named specialist templates before any runtime
  specialist commands exist?~~ **Resolved rev 2 (operator direction): yes — as
  open-format Agent Skills; this RFC is the normative statement.**
- Should lane-B skills declare the required companion verbs (claim/done/
  integrate) in `metadata:` so doctor can cross-check a mutating request against
  the recorded worktree owner?
- Should the repository document per-product wiring examples (Claude Code,
  Codex CLI) or stay product-agnostic in core docs and keep wiring notes in
  `examples/`?
