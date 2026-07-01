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
| [issue-lifecycle.md](issue-lifecycle.md) | The mandatory open → decide → close ticket convention: the visual create template, the decision template, and the close template — for Forgejo, GitHub, and GitLab. |

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
| [context-pack-measurements.md](context-pack-measurements.md) | DoD evidence log: measured token reduction + output equivalence of the context companion (RFC 034), for Claude and Codex. |
| [rtk-shell-output-policy.md](rtk-shell-output-policy.md) | Usage policy for the optional RTK shell-output adapter: recommended modes, forbidden diff mode, self-declared RTK visibility, and `rtk discover` audit guidance. |

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
| [027-rfc-notifications.md](rfc/027-rfc-notifications.md) | Shipped tiered local notifications (stdout/file/bell/OS/hook) for handoffs and stale turns — advisory, no-daemon, no-network. |
| [028-rfc-headless-command-templates.md](rfc/028-rfc-headless-command-templates.md) | Shipped safe headless command templates: opt-in provider examples, platform argv arrays, strict run-plan validation. |
| [029-rfc-m8shift-board.md](rfc/029-rfc-m8shift-board.md) | Draft richer companion workboard concept outside the core task board. |
| [030-rfc-tamper-evidence.md](rfc/030-rfc-tamper-evidence.md) | Proposed stdlib hash-chain for tamper-evidence — detection + warning, not prevention/identity/encryption; git as the strong anchor. |
| [031-rfc-decision-traceability.md](rfc/031-rfc-decision-traceability.md) | Shipped tool-independent decision traceability — forge / GitHub / both / git or a markdown ADR fallback; structured contradictory-decision records (positions for/against + resolution). |
| [032-rfc-tiered-delegation.md](rfc/032-rfc-tiered-delegation.md) | Capability-tiered sub-agent delegation charter; Phase 1 advisory `route recommend` is shipped, while actual delegated launch remains future. |
| [033-rfc-context-economy.md](rfc/033-rfc-context-economy.md) | Draft context economy & handoff protocol — exchange compact Task Packets, not full context; three context layers; advisory budgets; economy never starves verification; companion + agents-guide discipline. |
| [034-rfc-companion-adapter-interface.md](rfc/034-rfc-companion-adapter-interface.md) | Native context companion plus Phase-2 shell-output adapter runner; RTK defaults on when present + identity-pinned, degrades to native otherwise, telemetry is disabled on setup, and runtime/context status surfaces RTK ON/OFF visibility. |
| [035-rfc-interactive-listener-gap.md](rfc/035-rfc-interactive-listener-gap.md) | Proposed runtime listener fix for the gap between `wait` readiness and interactive UI resumption. |
| [036-rfc-token-window-exhaustion.md](rfc/036-rfc-token-window-exhaustion.md) | Shipped runtime `headroom` guard for proxy context exhaustion detection, checkpointing, status/doctor surfacing, and explicit pause. |
| [037-rfc-agent-context-compression-backends.md](rfc/037-rfc-agent-context-compression-backends.md) | Context-compression policy + JSON file protocol — Phase D shipped in v3.39.0 with local `compress/retrieve`, builtin digesting, RTK backend dispatch for shell/tool outputs, optional `headroom_ext` dispatch for broad context records, redaction-before-store, bounded retrieval, and reference-only fail-safe. Backends are RFC 034 adapters (builtin/RTK/optional Headroom-compatible local command); mechanism under RFC 033 policy; estimates advisory, gains validated with real tokenizers; compression never starves verification. |
| [038-rfc-multi-session.md](rfc/038-rfc-multi-session.md) | Draft parallel multi-session model — named sessions namespace the relay per session (default preserves today's behavior); N independent degree-1 relays, file isolation via worktrees (RFC 008). |
| [039-rfc-model-task-routing.md](rfc/039-rfc-model-task-routing.md) | Shipped Phase 1 advisory `route recommend`: capability-first model/task routing over operator manifests; `route delegate` remains future and confirmation-gated. |
| [040-rfc-ai-session-usage-monitoring.md](rfc/040-rfc-ai-session-usage-monitoring.md) | Usage-monitoring companion RFC. Shipped Phase B: core `cooldown` parks IDLE/AWAITING relays as `PAUSED` and records `kind=usage_cooldown` session events. Remaining runtime phases cover normalized provider snapshots, cooperative interrupts for a WORKING holder, and quiet waits until reset. Generic multi-provider — Claude + Codex phase-1 adapters, Gemini/Copilot/Vibe later; adapter security reuses the RFC 034 hardened runner. |
