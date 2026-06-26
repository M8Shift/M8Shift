# RFC — Runtime/gateway patterns: retained, rejected, and why

**Status:** accepted design filter · **Target:** M8Shift core + optional companions ·
**Source review:** runtime/gateway designs, the M8Shift website comparison chapter,
and the official docs for OpenClaw, LangGraph, AutoGen, Microsoft Agent Framework,
CrewAI, OpenHands, OpenAI Agents SDK, Dify, and n8n AI workflows. The recurring
patterns are command queues, steering, presence, run lifecycle, doctor/lint, loop
detection, gateway protocols, workboards, and agent supervisor modules.

## Goal

Decide which runtime/gateway ideas are worth transposing into M8Shift, and which ones
must be rejected to preserve M8Shift's identity.

The core distinction:

| Project | Primary role |
|---------|--------------|
| Runtime/gateway platforms | own sessions, routing, tools, channels, presence, and supervision |
| M8Shift | a cooperative repo mutex: one pen, one turn journal, no runtime ownership |

So the question is not "should M8Shift become a gateway?". It should not. The useful
question is: which operational patterns can improve M8Shift without turning the
passive relay into a runtime?

## Ratification outcome

The filter below is accepted as the post-Stage-6 design boundary:

- **14 retained patterns are adopted as design seeds**, not as immediate implementation scope:
  doctor/lint checks; foreground status watch; presence/heartbeat; per-agent lane ownership;
  operator inbox modes; run lifecycle ids; progress log; loop/no-progress detection; idempotency keys;
  canonical run plans; bounded sidecar ledgers; safe transcript/recap normalization;
  action-sensitive memory guidance; and workboard concepts as a companion-only idea.
- **13 rejected patterns stay rejected** for the core: gateway daemon/WebSocket protocol; pairing,
  device tokens, scopes, and auth roles; multi-channel message connectors; provider/model routing;
  tool sandbox/execution approval framework; plugin architecture; SQLite/database-backed state;
  semantic/vector memory and autonomous summarization; autonomous workboard dispatcher; automatic UI
  wake guarantees; path-scoped shared-tree leases; durable queue as core authority; and automatic
  force recovery.
- **6 deferred topics are split into dedicated draft RFCs** so they can be designed independently:
  [024 doctor split](024-rfc-doctor-split.md), [025 status-runtime](025-rfc-status-runtime.md),
  [026 sidecar retention](026-rfc-sidecar-retention.md), [027 notifications](027-rfc-notifications.md),
  [028 headless command templates](028-rfc-headless-command-templates.md), and
  [029 m8shift-board](029-rfc-m8shift-board.md).
- **Implementation order is accepted as backlog order** for the retained runtime work:
  core-safe diagnostics → runtime sidecars → lane ownership → no-progress detection → headless plan →
  retention. This RFC does not implement those backlog items by itself.

## Decision rule

Keep a pattern only if all of this is true:

1. it solves a real M8Shift operational failure mode;
2. it can live in the core as read-only/reporting logic, or in an opt-in companion;
3. it does not create a second authority over the `LOCK`;
4. it does not require network access, accounts, provider APIs, or a resident service for
   normal M8Shift use;
5. it keeps `M8SHIFT.md` as the only coordination source of truth;
6. it remains understandable from plain files and shell commands.

Reject a pattern when it would make the core a runtime, an orchestrator, a policy
engine, or a database-backed platform.

## Comparison-derived feature map

Snapshot date: 2026-06-26. The M8Shift website comparison chapter frames most named
tools as adjacent runtimes or automation platforms, not direct replacements for a
repository-local mutex. This table records what can be transposed into M8Shift and what
must stay out.

| Tool | Feature signals reviewed | Recoverable / transposable | Not transposable | Why |
|------|--------------------------|----------------------------|------------------|-----|
| [OpenClaw](https://docs.openclaw.ai/) | Self-hosted gateway, chat channels, sessions, routing, memory, multi-agent routing, Web Control UI, mobile nodes. | Local adapter ideas: presence, exact resume prompts, operator inbox writes, channel allowlists as external adapter policy. | Channel connectors, gateway as session/routing source of truth, device actions, background daemon in core. | M8Shift can be called by a gateway, but the `LOCK` remains the only repo coordination authority. |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | Low-level orchestration runtime with durable execution, persistence, streaming, human-in-the-loop, memory, observability, deployment. | Sidecar run state, event logs, progress streaming, human intervention modes, resumable run reports. | Graph engine, model/tool runtime, persistent graph state deciding who writes next, deployment platform. | The useful part is operational traceability; routing must still be explicit handoff state. |
| [AutoGen](https://github.com/microsoft/autogen) | Multi-agent application framework, autonomous or human-assisted conversations, now maintenance-mode with Microsoft Agent Framework as successor. | Role/handoff vocabulary and transcript-to-report display patterns. | Conversation runtime, model clients, chat transcript as source of truth, new feature dependency. | It is historical input; new implementation choices should follow maintained patterns or M8Shift primitives. |
| [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) | Agents, workflows, state management, context providers, middleware, MCP clients, telemetry, graph workflows. | Simple workflow schemas, provider registry checks, policy/approval records, middleware-like diagnostics in `doctor`. | .NET/Python app framework, Azure/Foundry dependency, MCP execution, telemetry platform. | These belong to host applications; M8Shift can only record local contracts and diagnostics. |
| [CrewAI](https://docs.crewai.com/) | Agents, crews, flows, tools, memory, knowledge, guardrails, observability, automations, sequential/hierarchical/hybrid processes. | Role contracts, lightweight workflow steps, advisory process metadata, validation/guardrails as read-only checks. | Crew executor, knowledge/memory store, automation triggers, tool runtime in core. | M8Shift can clarify responsibilities but must not dispatch crews or run tools. |
| [OpenHands](https://www.openhands.dev/) | Autonomous coding-agent platform, isolated sandboxes, cloud/VM/local execution, parallel agents, GitHub/Slack/PagerDuty triggers, audit/RBAC/budget controls. | Isolated-worktree pattern, run evidence, artifacts, reports, external trigger receipts. | Sandbox platform, autonomous PR/Slack/PagerDuty actions, enterprise RBAC, cost guardrails. | This is the closest domain overlap, but M8Shift is the shared-repo coordination primitive underneath. |
| [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents) | `Agent` + `Runner` manage turns, tools, guardrails, handoffs, sessions, state, and observability; handoffs delegate to specialists. | Handoff metadata, role/contract fields, guardrail results as explicit evidence, provider argv templates. | SDK runner loop, model/tool execution, sessions as routing authority, guardrails that mutate the `LOCK`. | The SDK can run agents; M8Shift can record repo handoffs around file mutations. |
| [Dify](https://github.com/langgenius/dify) | Visual workflows, RAG pipelines, model/provider support, Prompt IDE, agent tools, logs, APIs. | Workflow-file shape ideas, external trigger provenance, report fields for logs and evidence. | Visual canvas, RAG/knowledge base, model management, API publishing. | These are product/app platform features, not repository mutex features. |
| [n8n AI workflows](https://docs.n8n.io/advanced-ai/) | Automation workflows, AI nodes, LangChain concepts, MCP server, workflow templates, chat trigger, human-in-the-loop for tool calls. | External-trigger adapter contract, idempotency keys, local operator messages, human fallback semantics. | Connector runtime, code-node execution, MCP server, full workflow engine. | n8n may start a job that calls M8Shift; M8Shift must not become n8n. |

## Codebase fit check

Several transposable patterns are already partially shipped. Future specs should build on
these surfaces instead of adding parallel mechanisms.

| Pattern family | Current code surface | Spec implication |
|----------------|----------------------|------------------|
| Read-only health and status | `m8shift.py doctor`, `status --json`, `watch`, `recap`, `peek`, `log` | New diagnostics should extend `doctor` or runtime doctor, never auto-repair by default. |
| Handoff contracts | `append --ask/--done/--files`, Stage-4 advisory fields, `contract validate` | Runtime/adapter evidence should serialize as advisory fields or reports, not change claimability. |
| Runtime presence and progress | `m8shift-runtime.py watch`, `progress`, `status-runtime`, `.m8shift/runtime/*.jsonl` | Competitor-style live state belongs in removable runtime sidecars. |
| Operator messages | `m8shift-runtime.py operator --mode status/followup/collect/interrupt` | Channel or automation adapters should write inbox rows, not arbitrary chat into `M8SHIFT.md`. |
| Provider mapping | `m8shift-runtime.py providers init/list/show/check/render` | Host launch commands stay argv arrays outside the core and outside secrets. |
| Roles and workflows | `m8shift-runtime.py init`, `roles`, `workflows` | Keep workflows linear/declarative until a separate RFC proves graph semantics are needed. |
| Approvals and reports | `m8shift-runtime.py approve`, `report`; core `session report` | Approval is evidence for humans and adapters, not an authorization system for the core. |
| Isolated parallel coding | `m8shift-worktree.py claim/done/status/integrate/drop` | Parallelism remains worktree-based with serialized integration. |

## Retained patterns

### 1. Doctor / lint checks — KEEP

**Why keep it:** M8Shift failures are often environmental: wrong cwd, stale frozen relay,
missing anchor reload, stale lock, several sessions under the same agent identity, or an
interactive UI that is no longer waiting.

**Where it belongs:**

- read-only checks may be in the core as `m8shift.py doctor` / `doctor --json`;
- runtime-specific checks belong in `m8shift-runtime doctor`.

**Useful checks:**

- `M8SHIFT.md` exists and has a valid `LOCK`;
- anchors exist and include the stanza near the top;
- `AGENTS.override.md` is synchronized when present;
- `M8SHIFT.protocol.md` exists and matches the active engine generation policy;
- `.m8shift.lock` is stale or malformed;
- `status --json` works from the expected project root;
- the frozen relay copy and the repo copy report divergent versions;
- runtime sidecars are gitignored;
- `AWAITING_<agent>` has live presence or a concrete resume prompt;
- worktree integration sentinel is not stranded without a warning.

**Boundary:** `doctor` reports by default. Any `--fix` mode must be explicit, narrow, and
must never auto-steal a non-stale pen.

### 2. Foreground status watch — KEEP, NARROW

**Why keep it:** operators need a terminal that evolves without repeatedly typing
`status`, especially during handoffs between interactive UIs.

**Where it belongs:** the core as `m8shift.py watch`, because it is just a repeated
read-only status render.

**Boundary:** `watch` is not presence, supervision, notification, or recovery. It does
not `claim`, hand off, repair, run tools, or wake an agent. Autonomous watchers and
push-notifiers still belong outside the core.

### 3. Presence / heartbeat — KEEP

**Why keep it:** `status` can say `AWAITING_CODEX` while no Codex UI or process is alive.
That is the exact class of failure that caused repeated human nudges.

**Where it belongs:** runtime companion sidecar:

```text
.m8shift/runtime/presence.json
```

Presence records `agent`, `session_id`, `run_id`, `state`, `pid`, `cwd`, `last_seen`, and
the last observed core `LOCK` state.

**Boundary:** stale presence never grants the pen. Core TTL remains the only stale-pen
recovery rule.

### 4. Per-agent queue / lane — KEEP

**Why keep it:** the core identifies agents by roster name, not by UI instance. Two Codex
sessions can both treat `claim codex` as a refresh. A lane owner prevents this.

**Where it belongs:** runtime companion only.

**Rule:** one active runtime owner per agent lane (`codex`, `claude`, …). Other processes
can read status but must queue or refuse managed actions. A different runtime may take
over only with an explicit stale-lane takeover after the current lane record is no
longer fresh.

**Boundary:** this is instance-level runtime safety. It must not change the core identity
model, grant the pen, or steal a fresh lane.

### 5. Operator inbox modes — KEEP

**Why keep it:** human intervention during a run needs explicit semantics. A raw UI message
does not tell the relay whether the human means "add this later", "interrupt", or "give me
status".

**Retained modes:**

| Mode | Meaning |
|------|---------|
| `status` | ask for progress only |
| `followup` | deliver after the current safe point |
| `collect` | merge several human notes before the next turn |
| `interrupt` | ask the active runtime to summarize and hand off safely |

**Where it belongs:** runtime companion sidecar:

```text
.m8shift/runtime/inbox/<agent>.jsonl
```

**Boundary:** `interrupt` is a request, not a force takeover. The core pen is not stolen.

### 6. Run lifecycle ids — KEEP

**Why keep it:** humans need to distinguish "turn 11 in the relay" from "Codex UI session
that attempted to process turn 11". A `run_id` makes abandoned or retried sessions
auditable.

**Where it belongs:**

- sidecar `runs.jsonl` in the runtime companion;
- optional advisory `x_run_id` field in `append --field`, never interpreted by routing.

**Boundary:** the core `turn` remains the official relay sequence. `run_id` is runtime
telemetry.

### 7. Progress drafts / progress log — KEEP

**Why keep it:** long turns currently look identical to dead turns from outside the UI.

**Where it belongs:**

```text
.m8shift/runtime/progress.jsonl
```

**Semantics:** short append-only notes such as "running tests", "reading handoff",
"preparing append".

**Boundary:** progress does not replace `append --done`; it is not proof of completion.

### 8. Loop / no-progress detection — KEEP

**Why keep it:** the recurring operational failure is not just "someone forgot to wait";
it is "the same wait/resume/status cycle repeats without advancing the relay".

**Where it belongs:** runtime companion and `doctor`, not the core mutex.

**Implemented v1 pattern:** `m8shift-runtime.py watch` can compare the current run's
latest `progress.jsonl` / `runs.jsonl` event with explicit
`--no-progress-warn-after` and `--no-progress-block-after` thresholds. Warning emits a
`runtime.no_progress` finding and hint. Blocking exits only the companion loop with
that finding.

**Detected patterns:**

- same `status` observed for too long with no heartbeat/progress change;
- repeated identical resume prompts;
- repeated `claim` refreshes with no files/tests/progress/append;
- runner process exits while the core remains `WORKING_<agent>`;
- UI expected to resume but no presence is alive.

**Boundary:** detection reports or blocks the companion's own loop. It does not auto-force
the core lock and never emits a force-recovery command.

### 9. Idempotency keys — KEEP

**Why keep it:** UI retries and human double-clicks can duplicate companion-originated
actions: notifications, queued operator messages, headless run requests, or integration
finalization.

**Where it belongs:** companion actions only:

```text
.m8shift/runtime/idempotency.jsonl
```

**Boundary:** do not deduplicate or rewrite core turns. `M8SHIFT.md` remains append-only.

### 10. Canonical run plan for headless execution — KEEP

**Why keep it:** headless mode can become dangerous if the command, cwd, prompt, or agent
identity changes between preparation and execution.

**Where it belongs:** runtime companion.

**Pattern:** prepare an immutable local plan:

```json
{
  "run_id": "...",
  "agent": "codex",
  "cwd": "/repo",
  "argv": ["codex", "exec", "..."],
  "prompt_sha256": "...",
  "created_at": "..."
}
```

Then execute exactly that plan and verify the core state afterward.

**Boundary:** this is local process hygiene. M8Shift does not become a shell approval
system.

### 11. Bounded task/run ledgers — KEEP

**Why keep it:** sidecars can grow forever if the companion is long-running.

**Where it belongs:** runtime/worktree companions.

**Pattern:** cap retained events or provide `archive`/`prune` for runtime JSONL files.

**Boundary:** never prune `M8SHIFT.md` outside the existing core `archive` command.

### 12. Safe transcript / recap normalization — KEEP, NARROW

**Why keep it:** runtime tools may need to show recent UI/session context without dumping
huge or unsafe raw transcripts.

**Where it belongs:** companion diagnostics, possibly a future `recap --safe`.

**Pattern:** truncate long rows, strip control-token-looking scaffolding, redact obvious
token-like values, and report `truncated: true`.

**Boundary:** this is a display filter, not a rewriting pass over the source journal.

### 13. Action-sensitive memory guidance — KEEP, NARROW

**Why keep it:** some notes in `remember` affect future behavior only under a condition:
permission, expiry, handoff boundary, or "do not act yet".

**Where it belongs:** documentation and optional templates, not smart memory logic.

**Pattern:** encourage notes like:

```text
remember codex "Do not run publishing scripts unless the maintainer explicitly asks in the current session."
```

**Boundary:** no semantic memory, no automatic policy engine, no derived routing.

### 14. Workboard concepts — KEEP ONLY AS A COMPANION IDEA

**Why keep it:** runtime workboards have useful operational concepts: claim TTL,
heartbeat, owner token, blocked reason, proof/artifacts.

**Where it belongs:** a future `m8shift-board.py` companion, if needed.

**Boundary:** the existing core `task` board stays dumb and advisory. No dependency solver
or automatic dispatch in the core.

## Rejected patterns

### 1. Gateway daemon / WebSocket protocol — REJECT

**Why reject it:** it makes M8Shift a resident platform. The current value proposition is
`cp m8shift.py`, local files, no server.

**Allowed substitute:** optional companion processes that can be stopped without breaking
the relay.

### 2. Pairing, device tokens, scopes, auth roles — REJECT

**Why reject it:** M8Shift does not expose a network control plane. There is nothing to
pair or authenticate at the M8Shift layer.

**Allowed substitute:** local file permissions and explicit shell commands.

### 3. Multi-channel message connectors — REJECT

**Why reject it:** Slack/Discord/LINE/Telegram-style ingress turns the tool into an
inbox/router. M8Shift coordinates agents already running in their own surfaces.

**Allowed substitute:** a companion may print or write a local resume prompt.

### 4. Provider/model routing — REJECT

**Why reject it:** M8Shift must not choose models, vendors, or auth profiles. The host
agent UI/CLI owns that.

**Allowed substitute:** documentation can show how to run a given host CLI, but the core
does not know providers.

### 5. Tool sandbox / execution approval framework — REJECT IN CORE

**Why reject it:** command approval is a host-agent responsibility. If M8Shift owns tool
policy, it becomes an execution runtime.

**Allowed substitute:** a headless companion can freeze a local run plan and ask the human
before executing it.

### 6. Plugin architecture — REJECT

**Why reject it:** plugins require discovery, manifests, loading policy, versions, and
security boundaries. That breaks the single-file charter.

**Allowed substitute:** separate companion scripts with clear names and no core loading.

### 7. SQLite / database-backed state — REJECT IN CORE

**Why reject it:** the core state must remain readable by eye and `grep`, versionable, and
copyable as a plain file.

**Allowed substitute:** companion sidecars may use JSONL/plain files first. Any database
would need a separate RFC and must not become required for the core relay.

### 8. Semantic/vector memory and autonomous summarization — REJECT

**Why reject it:** derived memory becomes a second knowledge base and policy surface.
M8Shift's `remember` ledger is intentionally human-curated and append-only.

**Allowed substitute:** documentation for better manual memory notes.

### 9. Autonomous workboard dispatcher in the core — REJECT

**Why reject it:** automatic task promotion/dispatch would route work based on derived
state. The core must route only on the `LOCK`.

**Allowed substitute:** future companion board; the core `task` command remains advisory.

### 10. Automatic UI wake guarantees — REJECT

**Why reject it:** VS Code/Desktop/Web chat UIs generally cannot be resumed from a plain
Python script without a supported API. Claiming otherwise creates false reliability.

**Allowed substitute:** presence, notification, and exact resume prompts.

### 11. Path-scoped leases in the shared tree — REJECT

**Why reject it:** concurrent writes in the same checkout violate the one-pen model and
make correctness depend on path prediction.

**Allowed substitute:** isolated git worktrees plus serialized integration through
`m8shift-worktree.py`.

### 12. Durable queue as core authority — REJECT

**Why reject it:** a core queue that decides who runs next would compete with the explicit
`append --to` baton.

**Allowed substitute:** companion queues for runtime prompts and operator notes. Core
handoff remains `AWAITING_<agent>`.

### 13. Automatic force recovery — REJECT

**Why reject it:** force-claiming is a human/recovery act. A companion that auto-forces
could steal valid work during slow tests or UI stalls.

**Allowed substitute:** detect stale locks and print the exact recovery command.

## Spec seeds from transposable patterns

These are starter specs, not implementation commitments. They define the narrow shape
that future companion RFCs should use if they consume ideas from the comparison set.

### A. Runtime event envelope v1

All companion-generated JSONL events SHOULD use one envelope:

```json
{
  "schema": "m8shift.runtime.event.v1",
  "type": "progress",
  "ts": "2026-06-26T12:00:00Z",
  "agent": "codex",
  "session_id": "codex-ui-1",
  "run_id": "20260626T120000Z-codex-a1b2c3",
  "relay": {
    "state": "WORKING_CODEX",
    "holder": "codex",
    "turn": 12
  },
  "source": {
    "tool": "m8shift-runtime.py",
    "version": "<runtime version>"
  },
  "idempotency_key": "",
  "payload": {}
}
```

Rules:

- `schema`, `type`, `ts`, and `source.tool` are REQUIRED.
- `agent` MUST be a roster identity when the event is agent-scoped.
- `run_id` MUST NOT become the relay sequence; `LOCK.turn` remains canonical.
- Invalid sidecar JSON/JSONL is a diagnostic finding, not a core parse failure.
- Deleting `.m8shift/runtime/` MUST NOT corrupt or reinterpret `M8SHIFT.md`.

### B. External runtime adapter contract

Any OpenClaw, n8n, Dify, OpenHands, LangGraph, CrewAI, Agent Framework, or Agents SDK
adapter that mutates repository files MUST follow this contract:

1. Read `status --json` or `status-runtime --json`.
2. Acquire the pen with `m8shift.py next <agent>` or `claim <agent>` before file writes.
3. Record long work with runtime `progress`; do not stream partial work into the relay
   journal.
4. Finish with `append <agent> --to <next-agent>` and concrete `--done`, `--files`,
   and evidence fields.
5. If the host process fails after claiming, report the stuck state and print a recovery
   command. Do not auto-force.

Adapters MAY use `m8shift-runtime.py providers render` to build argv arrays. They MUST
NOT shell-expand provider commands from untrusted strings.

### C. Workflow file v1

Workflow definitions SHOULD stay linear and local:

```json
{
  "schema": "m8shift.workflow.v1",
  "id": "default-code-review",
  "steps": [
    {"id": "plan", "role": "coordinator", "next": "implement"},
    {"id": "implement", "role": "implementer", "next": "review"},
    {"id": "review", "role": "reviewer", "next": "final"},
    {"id": "final", "role": "coordinator", "next": ""}
  ]
}
```

Rules:

- The workflow file MAY guide prompts, reports, or role selection.
- The workflow file MUST NOT make `claim` succeed or fail.
- Branching, concurrency, retries, timers, and triggers require a separate RFC.
- A workflow step describes responsibility, not a model/provider.

### D. Approval gate records v1

Approval records are local evidence:

```json
{
  "type": "approval",
  "run_id": "20260626T120000Z-codex-a1b2c3",
  "gate_id": "approve-push",
  "by": "human",
  "decision": "approved",
  "reason": "Maintainer approved pushing the release branch.",
  "ts": "2026-06-26T12:10:00Z"
}
```

Rules:

- Approval decisions MAY be summarized in run/session reports.
- Approval decisions MUST NOT execute the approved action.
- Approval decisions MUST NOT grant repository write ownership.
- `rejected` and `waived` are first-class decisions so reports can explain why work
  stopped or continued under human responsibility.

### E. Operator inbox delivery v1

Operator messages stay outside `M8SHIFT.md` until an agent chooses to act on them.

Modes:

| Mode | Required behavior |
|------|-------------------|
| `status` | Ask for progress only; no scope change. |
| `followup` | Deliver after the current safe point. |
| `collect` | Accumulate notes before the next turn or summary. |
| `interrupt` | Ask the active runtime to summarize and hand off safely. |

Rules:

- Adapters SHOULD attach an idempotency key for repeated external webhooks.
- `interrupt` MUST NOT steal a fresh `WORKING_*` pen.
- The receiving agent MAY cite inbox content in its next `append --ask/--done` or report,
  but the inbox row is not itself a relay turn.

### F. Run report minimum fields v1

Any generated run report SHOULD include:

- run id, agent, provider entry, start/end timestamps, and final status;
- relay state before and after execution;
- changed files as reported by the final handoff;
- progress notes and approval decisions;
- tests/checks run by the host agent, if reported;
- failures, timeouts, stale-presence findings, and recovery command hints.

Reports are evidence. They MUST NOT be parsed by the core to decide routing.

## Deferred / separate RFC

These are useful but need their own design before implementation:

1. `m8shift.py doctor` vs `m8shift-runtime doctor`: split of checks between core and companion.
2. `status-runtime`: whether to merge core status + presence/progress into one command.
3. Runtime sidecar retention policy: fixed cap, age-based pruning, or explicit archive.
4. Notification mechanism: stdout only, OS notification, or project-local prompt file.
5. Headless command templates: safe defaults for `codex exec`, `claude -p`, and other CLIs.
6. Future `m8shift-board.py`: whether a richer board is worth the extra companion.

## Implementation order

1. **Core-safe diagnostics:** add `doctor --lint --json` read-only checks.
2. **Runtime sidecars:** implement presence, run lifecycle, progress, and inbox files.
3. **Lane ownership:** prevent two managed runtimes for the same agent identity.
4. **No-progress detection:** warn/block the companion loop, never auto-force.
5. **Headless plan:** immutable local run plan + post-run core-state verification.
6. **Retention:** prune/archive runtime sidecars.

## Acceptance criteria

- The core still works if `.m8shift/runtime/` is deleted.
- No retained pattern changes the legal `LOCK` transitions.
- No retained pattern requires network access or an API key.
- `doctor --lint` can run in CI without prompts or writes.
- Runtime presence can explain "who is expected and whether anyone is actually waiting".
- Any future auto-runner verifies the core state after execution instead of trusting process
  exit status.
- Rejected patterns stay documented so they are not reintroduced under another name.
