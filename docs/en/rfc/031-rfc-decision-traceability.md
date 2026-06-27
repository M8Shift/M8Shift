# RFC — Decision traceability (forge, git, or a markdown fallback)

**Status:** proposed (design) · **Builds on:** [022-rfc-session-reports.md](022-rfc-session-reports.md) (decision ledger derived from turns), [agents-guide.md](../agents-guide.md) §6 (forge tracking) and its §2 *surface-disagreement-explicitly* rule · **Source:** maintainer request — guarantee a durable record of *why* decisions were made, including contradictory ones, **whatever tooling the project has or lacks**.

## Question

How does M8Shift guarantee that the **why** of a decision — and especially a **disagreement
between agents** (who was for, who was against, how it was reconciled) — is recorded durably,
**regardless of the project's tooling**? A project on a self-hosted forge, a project on
GitHub, a project on plain git with no issue tracker, and a project with no ticketing at all
must each end up with a usable decision record.

## Goal

Agents already debate in the append-only turn journal, and RFC 022 can derive a decision
ledger from it. This RFC makes that record **durable and tool-independent**:

1. **Establish the traceability target up front** — ask the operator (or read config) where
   decisions are logged, and never assume a forge exists.
2. **Always have a fallback** — if there is no issue tracker, a **markdown decision log** so
   traceability is *never lost*.
3. **Structure the contradictory-decision record** — positions for / against, the divergence,
   and the resolution, not just a flat "we decided X".

## Traceability targets

The agent establishes one target at setup; the order is preference, not requirement:

| Target | Where a decision lives | When |
|--------|------------------------|------|
| **Forge issues** (Forgejo / Gitea / GitLab) | issue / MR threads | the project has its own forge |
| **GitHub issues** | issue / PR threads | the project is on GitHub |
| **Both** (mirrored) | posted to both | the project mirrors forge ↔ GitHub (M8Shift itself does this) |
| **Plain git** | a `Decision:` / `Decided-by:` commit trailer **and** a tracked `docs/decisions/` log | git, but no issue tracker |
| **Markdown fallback** | `docs/decisions/NNNN-*.md` (ADR-style) or a single append-only `DECISIONS.md` | **no ticketing tool at all** |

> [!IMPORTANT]
> The fallback is the point: **a project without any tracker still gets a real, durable,
> reviewable decision record.** Agents must ask which target applies — or default to the
> markdown log — *before* they start producing decisions, so nothing is logged into a void.

## The contradictory-decision record

Whatever the target, a decision — especially a contested one — is recorded with the same
structure. This is what makes a disagreement auditable later:

```text
Decision:   <what was decided, one line>
Context:    <the problem / why it came up>
Options:    <A / B / C considered>
Positions:
  - claude: FOR <option> — <rationale>
  - codex:  AGAINST <option>, FOR <other> — <rationale>
Divergence: <the substantive disagreement, stated plainly>
Resolution: <consensus | maintainer arbitration | one position prevailed> — <why>
Trace:      <turns / commit / issue where this played out>
```

This operationalizes the §2 rule *surface disagreement explicitly*: a documented disagreement
with **named positions** is worth more than a frictionless "approved", and it is exactly what a
future reader (or auditor) needs to reconstruct *why* the code is the way it is.

## Markdown fallback — ADR-style

When there is no tracker, decisions live as **Architecture Decision Records**:

```text
docs/decisions/
  0001-relay-anchor-naming.md
  0002-english-only-docs.md
  ...
```

Each file is append-only and carries the structure above plus a status
(`proposed` / `accepted` / `superseded by NNNN`). M8Shift ships a **decision template**
(alongside the `.gitea` / `.github` issue templates from the issue-format work) so the shape
stays consistent. A single `DECISIONS.md` is the lighter variant for small projects.

## Low-friction: derive from the turns

Agents do not write the record twice. The contradictory positions are already in the turn
journal — each agent's turn states its stance. The decision record can be **derived /
scaffolded from the turns** via the RFC 022 `session decisions` mechanism, then written into
the chosen target — so the durable record is a *curated export of the immutable journal*, not
duplicate manual work.

## Charter constraints

1. **Advisory, not enforced.** M8Shift records the convention, provides the template and the
   fallback, and can scaffold an entry; it never blocks work for a missing decision record.
2. **The journal stays the source of truth.** The decision record is a curated summary; the
   append-only turns remain the immutable origin (and feed
   [030-rfc-tamper-evidence.md](030-rfc-tamper-evidence.md) for integrity).
3. **No project-management engine.** No boards, milestones, or workflow automation in the core
   — just a durable, structured record.
4. **Tool-independent.** Stdlib-only; the markdown fallback needs nothing but a filesystem.

## Command surface (proposed)

```bash
python3 m8shift.py session decisions current     # derive decisions from the turns (RFC 022)
python3 m8shift.py decisions scaffold --target md # write a decision entry from the template / turns
```

The target (`forge` / `github` / `both` / `git` / `md`) is read from config established at
setup; `md` is the default when nothing else is configured.

## Non-goals

- No bundled forge/GitHub API client beyond what the operator already uses — the agent records
  through the operator's existing CLI / credentials, not an M8Shift-managed token.
- No automatic decision-making; the **maintainer arbitrates** contested decisions.
- No replacement for an existing issue tracker — this complements it, and only *substitutes* a
  markdown log when there is none.

## Acceptance criteria

- A project with no issue tracker ends a session with a structured, append-only markdown
  decision record (positions, divergence, resolution) it did not have to hand-maintain.
- A contested decision is recorded with named for / against positions and the resolution, on
  whichever target is configured.
- The decision record is derivable from the turn journal (no duplicate manual logging).
- Removing the decision log loses only the curated summary, never the turn journal.
- Agents establish (ask / config) the target before producing decisions; absent any, they use
  the markdown fallback rather than logging nowhere.

## Open questions (designed solo — flagged for review)

1. **One file per decision vs a single `DECISIONS.md`.** ADR-per-file scales and supports
   `superseded-by`; a single log is simpler for small projects. Offer both, default by repo
   size?
2. **How the target is configured** — a relay/config field set at `init`, an explicit
   `decisions target` command, or inferred (forge remote present → forge; else git → md)?
3. **Auto-scaffold trigger.** Should `append --done` optionally offer to capture a decision
   when a turn resolved a disagreement, or stay fully manual?
4. **Inferring positions.** How much can `session decisions` infer for / against stances from
   turn text safely, vs requiring agents to tag their stance explicitly?
