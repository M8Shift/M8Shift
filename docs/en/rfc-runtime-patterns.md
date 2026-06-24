# RFC — Runtime/gateway patterns: retained, rejected, and why

**Status:** proposed design filter · **Target:** M8Shift core + optional companions ·
**Source review:** runtime/gateway designs, especially command queues, steering,
presence, run lifecycle, doctor/lint, loop detection, gateway protocols, workboards,
and agent supervisor modules.

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

### 2. Presence / heartbeat — KEEP

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

### 3. Per-agent queue / lane — KEEP

**Why keep it:** the core identifies agents by roster name, not by UI instance. Two Codex
sessions can both treat `claim codex` as a refresh. A lane owner prevents this.

**Where it belongs:** runtime companion only.

**Rule:** one active runtime owner per agent lane (`codex`, `claude`, …). Other processes
can read status but must queue or refuse managed actions.

**Boundary:** this is instance-level runtime safety. It must not change the core identity
model.

### 4. Operator inbox modes — KEEP

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

### 5. Run lifecycle ids — KEEP

**Why keep it:** humans need to distinguish "turn 11 in the relay" from "Codex UI session
that attempted to process turn 11". A `run_id` makes abandoned or retried sessions
auditable.

**Where it belongs:**

- sidecar `runs.jsonl` in the runtime companion;
- optional advisory `x_run_id` field in `append --field`, never interpreted by routing.

**Boundary:** the core `turn` remains the official relay sequence. `run_id` is runtime
telemetry.

### 6. Progress drafts / progress log — KEEP

**Why keep it:** long turns currently look identical to dead turns from outside the UI.

**Where it belongs:**

```text
.m8shift/runtime/progress.jsonl
```

**Semantics:** short append-only notes such as "running tests", "reading handoff",
"preparing append".

**Boundary:** progress does not replace `append --done`; it is not proof of completion.

### 7. Loop / no-progress detection — KEEP

**Why keep it:** the recurring operational failure is not just "someone forgot to wait";
it is "the same wait/resume/status cycle repeats without advancing the relay".

**Where it belongs:** runtime companion and `doctor`, not the core mutex.

**Detected patterns:**

- same `status` observed for too long with no heartbeat/progress change;
- repeated identical resume prompts;
- repeated `claim` refreshes with no files/tests/progress/append;
- runner process exits while the core remains `WORKING_<agent>`;
- UI expected to resume but no presence is alive.

**Boundary:** detection reports or blocks the companion's own loop. It does not auto-force
the core lock.

### 8. Idempotency keys — KEEP

**Why keep it:** UI retries and human double-clicks can duplicate companion-originated
actions: notifications, queued operator messages, headless run requests, or integration
finalization.

**Where it belongs:** companion actions only:

```text
.m8shift/runtime/idempotency.jsonl
```

**Boundary:** do not deduplicate or rewrite core turns. `M8SHIFT.md` remains append-only.

### 9. Canonical run plan for headless execution — KEEP

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

### 10. Bounded task/run ledgers — KEEP

**Why keep it:** sidecars can grow forever if the companion is long-running.

**Where it belongs:** runtime/worktree companions.

**Pattern:** cap retained events or provide `archive`/`prune` for runtime JSONL files.

**Boundary:** never prune `M8SHIFT.md` outside the existing core `archive` command.

### 11. Safe transcript / recap normalization — KEEP, NARROW

**Why keep it:** runtime tools may need to show recent UI/session context without dumping
huge or unsafe raw transcripts.

**Where it belongs:** companion diagnostics, possibly a future `recap --safe`.

**Pattern:** truncate long rows, strip control-token-looking scaffolding, redact obvious
token-like values, and report `truncated: true`.

**Boundary:** this is a display filter, not a rewriting pass over the source journal.

### 12. Action-sensitive memory guidance — KEEP, NARROW

**Why keep it:** some notes in `remember` affect future behavior only under a condition:
permission, expiry, handoff boundary, or "do not act yet".

**Where it belongs:** documentation and optional templates, not smart memory logic.

**Pattern:** encourage notes like:

```text
remember codex "Do not run publishing scripts unless the maintainer explicitly asks in the current session."
```

**Boundary:** no semantic memory, no automatic policy engine, no derived routing.

### 13. Workboard concepts — KEEP ONLY AS A COMPANION IDEA

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
