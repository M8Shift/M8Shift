# RFC 058 — Go-forward RFC discipline and index integrity

- **Status:** implemented policy/tooling baseline (#56, 2026-07-14)
- **Scope:** repository contribution governance; advisory doctor and pre-commit checks.
- **Related:** [RFC 031](031-rfc-decision-traceability.md),
  [RFC 048](048-rfc-adoption-discipline-pack-update-health.md), and
  [RFC 053](053-rfc-shared-rules-governed-habits.md).

## Decision

Every substantive behavior, schema, workflow, security-boundary, or architecture change
ships its RFC (new document or explicit amendment to the governing RFC) in the same PR.
The RFC records the decision and compatibility/safety boundary before the change becomes
an undocumented norm. Bug fixes may amend an existing RFC when they clarify its shipped
contract; a genuinely new contract receives the next permanent number.

This is deliberately a new RFC rather than an RFC 053 amendment. RFC 053 governs
optional, project-local learned rules that require human promotion and never travel by
default. This policy governs the M8Shift source repository's own contribution and release
discipline, is committed with the product, and must not depend on the future rules
companion.

The implementations for #42, #43, #47, and #51 predate this policy; Amendments F/A7 and
RFCs 056/057 are the one-time retroactive catch-up. From this batch onward the same-PR
rule applies.

## Mechanical advisory

Core `doctor` performs a bounded, read-only repository check when `docs/en/rfc/` exists:

- canonical `NNN-rfc-*.md` filename prefixes are unique;
- both canonical indices — the root `README.md` table and `docs/en/README.md` — contain
  exactly one link to every RFC file and no link to a missing RFC file.

Drift produces stable `rfc.index_drift` warnings. These findings are always advisory,
including under `doctor --lint`, because the core cannot infer whether a local change is
substantive or whether an amendment belongs to a different PR.

The pre-commit hook adds a second advisory: if staged source/workflow files change but no
canonical RFC file is staged, it prints a same-PR reminder. It also reports index drift
against the staged tree. The warning never mutates the relay and never blocks a human or
agent commit; review/CI remains the policy authority.

## Substantive-change scope

The advisory treats core/companion Python, installers, hooks, executable examples,
workflow definitions, and skill definitions as substantive candidates. Documentation,
tests, generated checksums, release notes, assets, and the RFC/index files themselves do
not trigger the same-PR reminder. This classification is intentionally conservative and
may miss a novel category; reviewers apply the normative policy, not the heuristic.

## Acceptance criteria

1. The four retroactive changes are documented under their locked dispositions.
2. Root and English-doc RFC indices exactly match canonical RFC files.
3. Specification and architecture name the new shipped contracts and boundaries.
4. `doctor` reports missing, orphaned, or duplicate RFC index entries without
   changing state or gating `--lint`.
5. Pre-commit warns on a staged substantive change without a staged RFC and reports staged
   index drift, but exits successfully when all existing hard guards pass.
