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
| [protocol.md](protocol.md) | Shared relay protocol — operational core (first read; states, rules, work loop). |
| [protocol-reference.md](protocol-reference.md) | On-demand reference: mental model, full command reference, project adoption. |
| [specification.md](specification.md) | Full functional and non-functional specification. |
| [agents-guide.md](agents-guide.md) | What is expected of AI agents: collaboration, branch/MR workflow, and the code-quality bar. |

## Explanation

| Document | Purpose |
|----------|---------|
| [architecture.md](architecture.md) | Architecture views, concurrency model, data stores, and operational boundaries. |
| [brand/color-palette.md](brand/color-palette.md) | Canonical M8Shift brand color palette and CSS tokens. |
| [philosophy.md](philosophy.md) | Why M8Shift exists and what collaboration model it supports. |
| [security-audit.md](security-audit.md) | Security audit of code, coordination, and prompt surfaces. |
| [owasp-agentic-top10-audit.md](owasp-agentic-top10-audit.md) | M8Shift mapped against the OWASP Top 10 for Agentic Applications (2026). |
| [security-research-and-frameworks.md](security-research-and-frameworks.md) | M8Shift against external security frameworks (arXiv, MITRE ATLAS, NIST/CISA/ANSSI, IBM AI Risk Atlas). |
| [stage2-rationale.md](stage2-rationale.md) | Design rationale behind the N-agent relay model. |

## Design decisions

| Document | Purpose |
|----------|---------|
| [decisions/vitepress-palette.md](decisions/vitepress-palette.md) | Accepted decision for adopting the brand palette in the VitePress documentation site. |

## RFCs

RFCs are authored and maintained in English only, under `docs/en/rfc/`.
Localized documentation should link to these canonical RFCs instead of duplicating them.

| Document | Purpose |
|----------|---------|
| [001-rfc-roster.md](rfc/001-rfc-roster.md) | Historical configurable roster RFC. |
| [002-rfc-n-agents.md](rfc/002-rfc-n-agents.md) | N-agent relay model with one shared pen. |
| [003-rfc-i18n-packs.md](rfc/003-rfc-i18n-packs.md) | Build-time language packs and localized single-file variants. |
| [004-rfc-memory.md](rfc/004-rfc-memory.md) | Shared append-only memory ledger. |
| [005-rfc-claim-check.md](rfc/005-rfc-claim-check.md) | Advisory pre-claim overlap checks. |
| [006-rfc-tasks.md](rfc/006-rfc-tasks.md) | Shared append-only task board. |
| [007-rfc-subturn.md](rfc/007-rfc-subturn.md) | Rejected `subturn` proposal. |
| [008-rfc-worktree-companion.md](rfc/008-rfc-worktree-companion.md) | Implemented v1 opt-in worktree companion for degree-2 parallel work and serialized integration. |
| [009-rfc-runtime-companion.md](rfc/009-rfc-runtime-companion.md) | Shipped local runtime companion for presence, operator inbox, progress, and diagnostics. |
| [010-rfc-runtime-patterns.md](rfc/010-rfc-runtime-patterns.md) | Accepted runtime/gateway pattern filter: retained, rejected, and deferred. |
| [011-rfc-session-history.md](rfc/011-rfc-session-history.md) | Session history ledger and `history` command. |
| [012-rfc-contracts-validation.md](rfc/012-rfc-contracts-validation.md) | Stage 4 contracts, review decisions, and shipped read-only validation. |
| [013-rfc-hosted-runtime-control-plane.md](rfc/013-rfc-hosted-runtime-control-plane.md) | Future optional hosted/runtime control plane. |
| [014-rfc-provider-management.md](rfc/014-rfc-provider-management.md) | Shipped local provider/adapter registry outside the core. |
| [015-rfc-shared-tree-degree-gt1.md](rfc/015-rfc-shared-tree-degree-gt1.md) | Research RFC for true degree > 1 writes in one shared working tree; rejected for the core. |
| [016-rfc-cooperative-turn-request.md](rfc/016-rfc-cooperative-turn-request.md) | Shipped cooperative baton request and operator steering for interactive UI deadlocks. |
| [017-rfc-stage6-integrations.md](rfc/017-rfc-stage6-integrations.md) | Stage 6 closure: local integration layer shipped; heavier integrations deferred to post-Stage-6 companions. |
| [018-rfc-agent-runtime-architecture.md](rfc/018-rfc-agent-runtime-architecture.md) | Shipped local runtime scaffold for roles, workflows, approvals, providers, and reports. |
| [019-rfc-input-neutral-patterns.md](rfc/019-rfc-input-neutral-patterns.md) | Neutral runtime pattern inventory curated for future companion RFCs. |
| [020-rfc-headless-runner-hardening.md](rfc/020-rfc-headless-runner-hardening.md) | Shipped reference runner hardening: validation, dry-run, timeout, and audit events. |
| [021-rfc-pause-resume.md](rfc/021-rfc-pause-resume.md) | Stable `PAUSED` state for open sessions with no active task. |
| [022-rfc-session-reports.md](rfc/022-rfc-session-reports.md) | Shipped session reports and decision ledger generated from existing turns. |
| [023-rfc-agent-token-footprint.md](rfc/023-rfc-agent-token-footprint.md) | Implemented Phase 1: cuts the mandatory protocol read by splitting an operational core from on-demand reference. |
| [024-rfc-doctor-split.md](rfc/024-rfc-doctor-split.md) | Baseline split between core doctor checks and runtime companion diagnostics. |
| [025-rfc-status-runtime.md](rfc/025-rfc-status-runtime.md) | Baseline runtime status composition over core status plus presence/progress/inbox/run sidecars. |
| [026-rfc-sidecar-retention.md](rfc/026-rfc-sidecar-retention.md) | Baseline fixed-count sidecar pruning is shipped; richer retention policy remains draft. |
| [027-rfc-notifications.md](rfc/027-rfc-notifications.md) | Proposed tiered local notifications (stdout/file/bell/OS/hook) for handoffs and stale turns — advisory, no-daemon, no-network. |
| [028-rfc-headless-command-templates.md](rfc/028-rfc-headless-command-templates.md) | Draft safe headless command templates for cooperative CLIs. |
| [029-rfc-m8shift-board.md](rfc/029-rfc-m8shift-board.md) | Draft richer companion workboard concept outside the core task board. |
| [030-rfc-tamper-evidence.md](rfc/030-rfc-tamper-evidence.md) | Proposed stdlib hash-chain for tamper-evidence — detection + warning, not prevention/identity/encryption; git as the strong anchor. |
| [031-rfc-decision-traceability.md](rfc/031-rfc-decision-traceability.md) | Proposed tool-independent decision traceability — forge / GitHub / both / git or a markdown ADR fallback; structured contradictory-decision records (positions for/against + resolution). |
| [032-rfc-tiered-delegation.md](rfc/032-rfc-tiered-delegation.md) | Proposed capability-tiered sub-agent delegation — a pen-holder routes simple sub-tasks to cheaper models as tools (worktree-parallel, verify-before-integrate); the degree-1 core is unchanged. |
| [033-rfc-context-economy.md](rfc/033-rfc-context-economy.md) | Draft context economy & handoff protocol — exchange compact Task Packets, not full context; three context layers; advisory budgets; economy never starves verification; companion + agents-guide discipline. |
