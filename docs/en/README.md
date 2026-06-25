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

RFCs are authored and maintained in English only, under `docs/en/rfc/`.
Localized documentation should link to these canonical RFCs instead of duplicating them.

| Document | Purpose |
|----------|---------|
| [rfc-agent-runtime-architecture.md](rfc/rfc-agent-runtime-architecture.md) | Future local agent runtime companion architecture around the passive core. |
| [rfc-claim-check.md](rfc/rfc-claim-check.md) | Advisory pre-claim overlap checks. |
| [rfc-cooperative-turn-request.md](rfc/rfc-cooperative-turn-request.md) | Shipped cooperative baton request and operator steering for interactive UI deadlocks. |
| [rfc-contracts-validation.md](rfc/rfc-contracts-validation.md) | Stage 4 contracts, review decisions, and shipped read-only validation. |
| [rfc-hosted-runtime-control-plane.md](rfc/rfc-hosted-runtime-control-plane.md) | Future optional hosted/runtime control plane. |
| [rfc-i18n-packs.md](rfc/rfc-i18n-packs.md) | Build-time language packs and localized single-file variants. |
| [rfc-input-neutral-patterns.md](rfc/rfc-input-neutral-patterns.md) | Neutral runtime pattern inventory curated for future companion RFCs. |
| [rfc-memory.md](rfc/rfc-memory.md) | Shared append-only memory ledger. |
| [rfc-n-agents.md](rfc/rfc-n-agents.md) | N-agent relay model with one shared pen. |
| [rfc-provider-management.md](rfc/rfc-provider-management.md) | Future provider/adapter registry outside the core. |
| [rfc-roster.md](rfc/rfc-roster.md) | Historical configurable roster RFC. |
| [rfc-runtime-companion.md](rfc/rfc-runtime-companion.md) | Shipped local runtime companion for presence, operator inbox, progress, and diagnostics. |
| [rfc-runtime-patterns.md](rfc/rfc-runtime-patterns.md) | Runtime/gateway patterns retained, rejected, or deferred. |
| [rfc-session-history.md](rfc/rfc-session-history.md) | Session history ledger and `history` command. |
| [rfc-shared-tree-degree-gt1.md](rfc/rfc-shared-tree-degree-gt1.md) | Research RFC for true degree > 1 writes in one shared working tree; rejected for the core. |
| [rfc-stage6-integrations.md](rfc/rfc-stage6-integrations.md) | Stage 6 closure: local integration layer shipped; heavier integrations deferred to post-Stage-6 companions. |
| [rfc-subturn.md](rfc/rfc-subturn.md) | Rejected `subturn` proposal. |
| [rfc-tasks.md](rfc/rfc-tasks.md) | Shared append-only task board. |
| [rfc-worktree-companion.md](rfc/rfc-worktree-companion.md) | Opt-in worktree companion for degree-2 parallel work and serialized integration. |
