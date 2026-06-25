# M8Shift documentation index — English

This document is the entry point for the English documentation set. It lists every
Markdown document currently present in `docs/en/`, excluding this index.

M8Shift is **free and open source**, released under the
[Apache License 2.0](../../LICENSE).

## Start here

| Document | Purpose |
|----------|---------|
| [tutorial.md](tutorial.md) | Step-by-step first relay run. |
| [vscode-guide.md](vscode-guide.md) | Practical setup for agent UIs in VS Code-style workspaces. |
| [windows.md](windows.md) | Windows installation and execution notes. |

## Reference

| Document | Purpose |
|----------|---------|
| [protocol.md](protocol.md) | Shared relay protocol, states, rules, and command workflow. |
| [specification.md](specification.md) | Full functional and non-functional specification. |

## Explanation

| Document | Purpose |
|----------|---------|
| [architecture.md](architecture.md) | Architecture views, concurrency model, data stores, and operational boundaries. |
| [philosophy.md](philosophy.md) | Why M8Shift exists and what collaboration model it supports. |
| [security-audit.md](security-audit.md) | Security audit of code, coordination, and prompt surfaces. |
| [stage2-rationale.md](stage2-rationale.md) | Design rationale behind the N-agent relay model. |

## RFCs and design records

RFCs are authored and maintained in English only, under `docs/en/rfc-*.md`.
Localized documentation should link to these canonical RFCs instead of duplicating them.

| Document | Purpose |
|----------|---------|
| [rfc-agent-runtime-architecture.md](rfc-agent-runtime-architecture.md) | Future local agent runtime companion architecture around the passive core. |
| [rfc-claim-check.md](rfc-claim-check.md) | Advisory pre-claim overlap checks. |
| [rfc-cooperative-turn-request.md](rfc-cooperative-turn-request.md) | Proposed cooperative baton request and operator steering for interactive UI deadlocks. |
| [rfc-contracts-validation.md](rfc-contracts-validation.md) | Stage 4 contracts, review decisions, and shipped read-only validation. |
| [rfc-hosted-runtime-control-plane.md](rfc-hosted-runtime-control-plane.md) | Future optional hosted/runtime control plane. |
| [rfc-i18n-packs.md](rfc-i18n-packs.md) | Build-time language packs and localized single-file variants. |
| [rfc-input-neutral-patterns.md](rfc-input-neutral-patterns.md) | Neutral runtime pattern inventory curated for future companion RFCs. |
| [rfc-memory.md](rfc-memory.md) | Shared append-only memory ledger. |
| [rfc-n-agents.md](rfc-n-agents.md) | N-agent relay model with one shared pen. |
| [rfc-provider-management.md](rfc-provider-management.md) | Future provider/adapter registry outside the core. |
| [rfc-roster.md](rfc-roster.md) | Historical configurable roster RFC. |
| [rfc-runtime-companion.md](rfc-runtime-companion.md) | Optional runtime companion concepts around the passive core. |
| [rfc-runtime-patterns.md](rfc-runtime-patterns.md) | Runtime/gateway patterns retained, rejected, or deferred. |
| [rfc-session-history.md](rfc-session-history.md) | Session history ledger and `history` command. |
| [rfc-shared-tree-degree-gt1.md](rfc-shared-tree-degree-gt1.md) | Research RFC for true degree > 1 writes in one shared working tree; rejected for the core. |
| [rfc-stage6-integrations.md](rfc-stage6-integrations.md) | Stage 6 closure: local integration layer shipped; heavier integrations deferred to post-Stage-6 companions. |
| [rfc-subturn.md](rfc-subturn.md) | Rejected `subturn` proposal. |
| [rfc-tasks.md](rfc-tasks.md) | Shared append-only task board. |
| [rfc-worktree-companion.md](rfc-worktree-companion.md) | Opt-in worktree companion for degree-2 parallel work and serialized integration. |
