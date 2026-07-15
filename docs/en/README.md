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
| [macos-iterm2.md](macos-iterm2.md) | Recommended macOS/iTerm2 truecolour setup for the read-only dashboard. |
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
| [status-performance-investigation.md](status-performance-investigation.md) | Measured `status --json` scaling, interpreter/build comparison, and incremental turn-fold prototype evidence. |
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
| [037-rfc-agent-context-compression-backends.md](rfc/037-rfc-agent-context-compression-backends.md) | Context-compression policy + JSON file protocol — Phase D follow-up shipped in v3.40.0 with local `compress/retrieve`, builtin digesting, RTK backend dispatch for shell/tool outputs, explicit/manual opt-in `headroom_ext` for broad context records, redaction-before-store, bounded retrieval, and reference-only fail-safe. Backends are RFC 034 adapters (builtin/RTK/optional Headroom-compatible local command); mechanism under RFC 033 policy; estimates advisory, gains validated with real tokenizers; compression never starves verification. |
| [038-rfc-multi-session.md](rfc/038-rfc-multi-session.md) | Draft parallel multi-session model — named sessions namespace the relay per session (default preserves today's behavior); N independent degree-1 relays, file isolation via worktrees (RFC 008). |
| [039-rfc-model-task-routing.md](rfc/039-rfc-model-task-routing.md) | Shipped Phase 1 advisory `route recommend`: capability-first model/task routing over operator manifests; `route delegate` remains future and confirmation-gated. |
| [040-rfc-ai-session-usage-monitoring.md](rfc/040-rfc-ai-session-usage-monitoring.md) | Usage-monitoring companion RFC. Shipped Phase B: core `cooldown` parks IDLE/AWAITING relays as `PAUSED` and records `kind=usage_cooldown` session events. Remaining runtime phases cover normalized provider snapshots, cooperative interrupts for a WORKING holder, and quiet waits until reset. Generic multi-provider — Claude + Codex phase-1 adapters, Gemini/Copilot/Vibe later; adapter security reuses the RFC 034 hardened runner. |
| [041-rfc-agent-skills.md](rfc/041-rfc-agent-skills.md) | Draft agent-skills system — a `skills/` directory of declarative, reusable, multi-agent competency definitions (adversarial-verify, rfc-review, release+dogfood, forge-workflow, hygiene, relay-discipline, token-economy, templates, site-update-report, multi-OS). Hybrid docs-first: markdown + `index.json` any agent loads; optional Phase-2 argv-only verification hooks. `agents-guide.md` becomes the curated index; distinct from RFC 039 routing capability tags. |
| [042-rfc-compression-backend-routing.md](rfc/042-rfc-compression-backend-routing.md) | Phase B shipped in v3.41.0 — `compress` records `access_mode` / `whole_content` advisory routing signals while preserving v3.40 manual Headroom opt-in. Signal-driven auto-route-to-Headroom remains gated behind measured evidence (#84) + identity-pinning. |
| [043-rfc-routing-principle.md](rfc/043-rfc-routing-principle.md) | Draft routing **principle** (design-only, introduces no behavior) — extracts the shared decision skeleton that RFC 037/039/042/032 each re-derive into **one canonical pipeline**: normalized signals (`feasibility`/`capability`/`access-mode` = hard gates; `size`/`content-type` = soft — **size is a risk *amplifier*, not a determinant**) → six stages (feasibility → fitness determinant → cost tie-break → non-downgradable guard → evidence gate → fail-closed default). Each existing router is an *instance*; reuses the RFC 034 runner + RFC 033 §9 floor + RFC 014 manifest. Advisory, fail-closed, no new runtime; does not override the instance RFCs. |
| [044-rfc-complete-init-companion-install.md](rfc/044-rfc-complete-init-companion-install.md) | Draft complete initialization RFC — adds a version-locked, idempotent, no-silent-clobber companion-copy phase to `init` while preserving the existing `.gitignore` state-artifact handling. |
| [045-rfc-module-reference-examples.md](rfc/045-rfc-module-reference-examples.md) | Draft module-reference RFC — defines one English-only docs page per shipped script, with command surface, inputs/outputs, safe examples, colored diagrams, and generator-backed drift checks. |
| [046-rfc-interactive-headless-runner-install.md](rfc/046-rfc-interactive-headless-runner-install.md) | Draft interactive/headless execution-mode RFC — surfaces run mode in status/watch and generated anchors, adds a hard status-guard rule, installs the shipped headless runner/watch wrapper as a companion selector, and requires project name + cwd in status/watch headers. |
| [047-rfc-headless-liveness-runner-listener.md](rfc/047-rfc-headless-liveness-runner-listener.md) | Draft v3.46 liveness RFC — runner final-state enforcement plus listener lifecycle companion, with zero-model polling, PID/process-group lifecycle, OS backends, doctor checks, and a narrow #6 TTL-action cross-reference. |
| [048-rfc-adoption-discipline-pack-update-health.md](rfc/048-rfc-adoption-discipline-pack-update-health.md) | Draft adoption-surface RFC for #18/#19/#20: generated `M8SHIFT.agent-pack.md`, local no-network source-driven `update`, and adoption-health `doctor` checks. |
| [049-rfc-holder-liveness-stale-claim-hardening.md](rfc/049-rfc-holder-liveness-stale-claim-hardening.md) | Implemented holder-liveness contract plus Amendment A7: claim handed-off work on pickup, including read-only review; runtime doctor reports an unclaimed awaiting turn without changing routing. |
| [050-rfc-manual-multi-agent-specialists.md](rfc/050-rfc-manual-multi-agent-specialists.md) | Draft manual multi-agent specialist workflow: advisory read-only and mutating worktree lanes report back to the relay. |
| [051-rfc-usage-advisory-in-core-display.md](rfc/051-rfc-usage-advisory-in-core-display.md) | Implemented read-only core usage advisory; Amendment F distinguishes a structurally absent window (`n/a`) from an unavailable read. |
| [052-rfc-project-compartmentalization-data-hygiene.md](rfc/052-rfc-project-compartmentalization-data-hygiene.md) | Draft: projects compartmentalized by default + mechanical data-hygiene gates (`doctor --hygiene` raw path lint, agent-pack invariant, out-of-repo denylist, scrub-check, session binding). Post INC-2026-0708 (#101). |
| [053-rfc-shared-rules-governed-habits.md](rfc/053-rfc-shared-rules-governed-habits.md) | Draft governed, project-local normative rules lifecycle, separate from memory and skills. |
| [054-rfc-pre-exhaustion-session-rotation.md](rfc/054-rfc-pre-exhaustion-session-rotation.md) | Draft design: provider-aware pre-exhaustion thresholds, compact checkpoint + bounded resume packet, and explicit operator-confirmed fresh-session rotation before native compaction becomes impossible. Extends RFC 036; no UI automation or core authority change. Reviewed (F1/F5/F6/F7/F9 amendments applied). |
| [055-rfc-wait-operator-state.md](rfc/055-rfc-wait-operator-state.md) | Draft design (co-design): a `wait: operator` marker on `WORKING_<X>` for a holder that keeps the pen but is blocked on the human — TTL made non-authoritative for staleness while blocked (liveness governs, extends RFC 049), distinct "WAITING ON OPERATOR" display. Not PAUSED (keeps the pen). |
| [056-rfc-self-declared-agent-model-provenance.md](rfc/056-rfc-self-declared-agent-model-provenance.md) | Implemented optional, bounded, self-declared model provenance in current agent state and immutable turns; explicitly unverified and advisory. |
| [057-rfc-index-accurate-checksum-manifest.md](rfc/057-rfc-index-accurate-checksum-manifest.md) | Implemented pre-commit checksum refresh from staged Git-index blobs, after the configured-agent pen guard. |
| [058-rfc-go-forward-rfc-discipline.md](rfc/058-rfc-go-forward-rfc-discipline.md) | Same-PR RFC discipline for substantive changes plus advisory doctor/pre-commit checks for RFC index integrity. |
| [059-rfc-terminal-colour-capability-semantic-rendering.md](rfc/059-rfc-terminal-colour-capability-semantic-rendering.md) | Implemented capability-tiered semantic palette for the read-only dashboard, with textual/symbolic meaning independent of colour. |
| [060-rfc-adaptive-terminal-geometry.md](rfc/060-rfc-adaptive-terminal-geometry.md) | Implemented automatic real-terminal geometry, deterministic wide-track flex, exact-height activity fill, and self-pipe SIGWINCH redraws for the read-only dashboard. |
| [061-rfc-bounded-adaptive-activity.md](rfc/061-rfc-bounded-adaptive-activity.md) | Implemented parameterized bounded activity provision, a capped adaptive viewport, true turn-position labels, and explicit truncated-buffer edges. |
| [062-rfc-listening-ends-only-at-done.md](rfc/062-rfc-listening-ends-only-at-done.md) | Strengthened the listening invariant so any halt — including holding the pen, PAUSED, or a denied action — suspends acting but never listening; only DONE ends listening, for every agent. |
| [063-rfc-on-demand-expanded-activity-reader.md](rfc/063-rfc-on-demand-expanded-activity-reader.md) | Implemented an `e`-toggle expanded ACTIVITY reader with immutable-turn point fetches, full word-wrapped done-text, block navigation, and text paging without widening the status snapshot. |
| [064-rfc-effective-time-accounting.md](rfc/064-rfc-effective-time-accounting.md) | Accepted effective-work/non-work accounting: exact append-only state durations going forward, honest unclassified legacy spans, one primary work item per work window, and one permanent global dashboard TIME strip. |
| [065-rfc-ticketed-committed-pushed-delivery.md](rfc/065-rfc-ticketed-committed-pushed-delivery.md) | Accepted delivery discipline: one structured forge ticket and committed, pushed history for every intentional change, with advisory offline reminders and a named role-based gateway. |
| [066-rfc-asymmetric-solo-advance.md](rfc/066-rfc-asymmetric-solo-advance.md) | Accepted design for policy-authorized bounded solo progress and deferred reconciliation; implementation remains phased and explicitly deferred. |
| [067-rfc-detached-vendor-neutral-cli-orchestration.md](rfc/067-rfc-detached-vendor-neutral-cli-orchestration.md) | Accepted design for detached, vendor-neutral CLI agent orchestration: all 16 recommended decisions are resolved; implementation remains phased and explicitly deferred. |

## Security docs

| Document | Purpose |
|----------|---------|
| [security-threat-model.md](security-threat-model.md) | OWASP LLM Top 10 / MITRE ATLAS threat mapping and executable conformance controls. |
