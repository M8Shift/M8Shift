# RFC — Runtime companion: queues, presence, and UI-safe waiting

**Status:** implemented v1 in v3.15.0 · **Target:** separate companion tool · **Builds on:**
[specification.md](../specification.md) §8, [vscode-guide.md](../vscode-guide.md), and
[008-rfc-worktree-companion.md](008-rfc-worktree-companion.md) §8c · **Inspiration:**
runtime command queues, steering modes, presence, run lifecycle, and progress drafts.
The retained/rejected runtime pattern inventory is tracked separately in
[010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md).

## Goal

Stabilize M8Shift runs when agents live in interactive UIs or headless CLIs, without
changing the core mutex.

The shipped companion is `m8shift-runtime.py`. It answers a different question than
`m8shift.py`:

| Layer | Responsibility |
|-------|----------------|
| `m8shift.py` core | who owns the pen; whether `claim`/`append` are legal; the durable turn journal |
| runtime companion | whether an agent process/session is alive, waiting, working, stalled, or needs a human nudge |

The core remains the only authority for the pen. The companion is a host-side runtime
wrapper around existing commands (`status --json`, `wait`, `claim`, `peek`, `append`,
`recap`), plus advisory sidecar files under `.m8shift/runtime/`.

## Problem statement

The current core is correct but intentionally passive:

- `wait <agent>` blocks a process, but it cannot relaunch or wake a VS Code / desktop
  chat UI.
- Several UI sessions using the same agent identity are indistinguishable; a second
  `claim codex` is treated as a holder refresh.
- Human messages typed into an agent UI during a run are unstructured; the protocol
  cannot tell whether they are follow-up context, a status request, or an interruption.
- `status` shows the relay state, not runtime liveness. It can say `AWAITING_CODEX`
  while no Codex process is actually waiting.
- Long turns have no standard progress channel; humans infer activity from the UI.

These are runtime/session problems, not mutex problems.

## Charter constraints

The companion must preserve M8Shift's core qualities:

1. **No second pen authority.** Only `m8shift.py claim/append/release/done` changes the
   core `LOCK`.
2. **No direct edits to `M8SHIFT.md`.** The companion may read it through the core and
   may append sidecar telemetry, but it never rewrites the relay file itself.
3. **No daemon in the core.** A long-running process is allowed only as an opt-in
   companion, never as a requirement of the single-file tool.
4. **No network or provider coupling.** The companion can run local commands and emit
   local notifications; it must not require API keys, webhooks, or a hosted service.
5. **Sidecars are advisory.** Presence, inbox, progress, and idempotency files can help
   the operator, but they must never make a forbidden core transition legal.
6. **One active runtime per agent lane.** The companion serializes work for a given
   agent identity (`codex`, `claude`, …) so multiple UI/CLI sessions do not race under
   the same roster name.

## Implemented file layout

Runtime state is local, generated, and gitignored:

```text
.m8shift/
  runtime/
    presence.json          # latest heartbeat per agent/session
    runs.jsonl             # append-only run lifecycle events (shared with headless runner)
    progress.jsonl         # append-only progress notes
    inbox/
      codex.jsonl          # operator messages queued for codex
      claude.jsonl
    idempotency.jsonl      # best-effort duplicate suppression for companion actions
```

`M8SHIFT.md` remains the coordination source of truth. Runtime sidecars explain what
the host processes are doing around that source of truth.

## Presence model

`presence.json` is a compact, overwritten snapshot keyed by agent identity and optional
session id:

```json
{
  "codex": {
    "session_id": "codex-vscode-main",
    "run_id": "20260624T091530Z-codex-0007",
    "mode": "ui-watch",
    "state": "waiting",
    "relay_state": "AWAITING_CLAUDE",
    "last_seen": "2026-06-24T09:15:30Z",
    "cwd": "/path/to/project",
    "pid": 12345
  }
}
```

Allowed `state` values:

| State | Meaning |
|-------|---------|
| `waiting` | companion is alive and polling for this agent's turn |
| `claiming` | companion detected the agent's turn and is trying to acquire the pen |
| `working` | the core lock is `WORKING_<agent>` for this runtime |
| `handoff` | the agent is closing the turn / handing off |
| `blocked` | the runtime needs human action |
| `stale` | heartbeat expired or the process disappeared |

Presence is diagnostic only. A stale presence never grants another agent the pen; stale
pen recovery still goes through core TTL rules.

## Run lifecycle

Every companion-managed turn receives a `run_id`. The companion appends lifecycle
events to `runs.jsonl`:

```json
{"type":"run.started","run_id":"...","agent":"codex","turn":11,"ts":"..."}
{"type":"run.claimed","run_id":"...","agent":"codex","turn":11,"ts":"..."}
{"type":"run.appended","run_id":"...","agent":"codex","to":"claude","turn":12,"ts":"..."}
{"type":"run.ended","run_id":"...","agent":"codex","status":"ok","ts":"..."}
```

This makes a failed or abandoned UI session auditable without changing the turn format.
If a future core field is needed, it should be an advisory `x_run_id:` turn field
written through `append --field`, not a routing field.

## Operator inbox

Human intervention should be explicit instead of being mixed into free-form UI chat.
The companion owns an operator inbox with four modes:

| Mode | Semantics |
|------|-----------|
| `followup` | deliver this message on the next safe prompt for the agent |
| `collect` | coalesce with other operator notes before the next prompt |
| `interrupt` | request that the active runtime stop, summarize, and hand off safely |
| `status` | ask the runtime to report progress without changing the task |

Proposed companion command surface:

```bash
python3 m8shift-runtime.py operator codex --mode followup  "also check the README"
python3 m8shift-runtime.py operator codex --mode collect   "second note before the next turn"
python3 m8shift-runtime.py operator codex --mode interrupt "stop after current safe point"
python3 m8shift-runtime.py operator codex --mode status    "where are you?"
```

For a headless CLI integration, the companion may inject inbox content into the next
agent prompt. For an interactive UI, it may only prepare a clear prompt for the human
to paste. Same-turn steering is allowed only if the host runtime explicitly supports
it; otherwise `steer` degrades to `followup`.

## Queue / lane model

The companion serializes work per agent lane:

```text
lane: codex
  queue: operator messages + scheduled runs
  max concurrency: 1

lane: claude
  queue: operator messages + scheduled runs
  max concurrency: 1
```

This prevents two Codex sessions from both treating `claim codex` as their own refresh.
Only the lane owner may start a new managed run. Other sessions can still read status,
but a companion-managed action for the same agent must be queued or refused.

The core remains identity-based; instance-level ownership lives only in the companion.

## Progress channel

Long turns should emit small, append-only progress events:

```bash
python3 m8shift-runtime.py progress codex --run "$RUN_ID" "reading tests"
python3 m8shift-runtime.py progress codex --run "$RUN_ID" "running unit suite"
python3 m8shift-runtime.py progress codex --run "$RUN_ID" "preparing append"
```

Progress does not replace `append --done`. It gives humans a reliable answer to
"is Codex still working?" while the turn is open.

## Operating modes

### 1. `watch` mode for interactive UIs

The core already has `m8shift.py watch`: a foreground, read-only terminal view that
repeats `status`. The companion `watch` mode is deliberately broader, but still cannot
wake a VS Code chat by itself. It does what is actually possible:

1. poll `m8shift.py status --json`;
2. update `presence.json`;
3. detect "this agent is awaited but no UI is active";
4. print / notify / write the exact resume prompt;
5. queue operator notes for the next prompt.

Example:

```bash
python3 m8shift-runtime.py watch codex --session codex-vscode-main
```

The human still pastes or sends the prompt to the UI, but the companion removes the
ambiguity about who is expected and what should be resumed.

### 2. `headless` mode for CLIs

In `headless` mode the companion can drive a local command template:

```bash
python3 m8shift-runtime.py run codex \
  --exec 'codex exec --dangerously-bypass-approvals-and-sandbox "$M8SHIFT_PROMPT"'
```

The generated prompt must instruct the agent to:

1. read its anchor and `M8SHIFT.protocol.md`;
2. run `claim <agent>`;
3. handle the latest `peek`;
4. `append` or report a blocker;
5. return control to the companion.

The companion must not assume the command succeeded just because the process exited
zero; it verifies the core state after the run.

## Idempotency

Companion actions that cause side effects should accept an optional idempotency key:

```bash
python3 m8shift-runtime.py operator codex --idempotency-key ui-20260624-001 --mode followup "..."
```

The key suppresses duplicate queued messages, repeated notifications, and retried
handoff/finalize steps. It must not deduplicate core `append` by editing the journal;
the core turn log remains append-only.

## Health / doctor checks

A runtime companion should expose:

```bash
python3 m8shift-runtime.py doctor
```

Minimum checks:

- `m8shift.py status --json` works from the configured root;
- `M8SHIFT.md`, `M8SHIFT.protocol.md`, and agent anchors exist;
- no malformed `.m8shift/runtime/*.jsonl`;
- at most one active runtime per agent lane;
- a `WORKING_*` lock is not expired, or is clearly stale and recoverable;
- `AWAITING_<agent>` has either live presence or a concrete resume prompt;
- companion sidecars are gitignored;
- worktree companion state, if present, is not mid-integration without a matching
  operator warning.

`doctor` reports; it does not auto-force the pen.

## Failure handling

| Failure | Companion response |
|---------|--------------------|
| awaited agent has no live presence | mark `blocked`, emit resume prompt / notification |
| two runtimes claim same lane | allow one lane owner, queue or refuse the other |
| runtime dies during `WORKING_<agent>` | presence becomes `stale`; core TTL remains the recovery rule |
| human sends new instruction mid-turn | store as `followup` / `collect` / `interrupt`, never silently mutate the running task |
| command wrapper exits but no `append` happened | inspect `status --json`; keep presence `blocked` and surface the last known state |
| duplicate UI action | suppress by idempotency key where provided |

## Non-goals

- Waking a closed or suspended proprietary UI without that UI exposing a supported API.
- Moving `wait` semantics into the core.
- Adding a resident daemon as a requirement for basic M8Shift use.
- Interpreting tasks, memory, or turn fields as routing policy.
- Replacing the worktree companion; runtime supervision and degree-2 integration are
  separate companions that may share sidecar conventions.

## Minimal v1 status

Shipped incrementally:

1. **Read-only watch loop** (v3.15.0): `watch <agent>`, `presence.json`, lane ownership,
   exact resume prompt.
2. **Operator inbox** (v3.15.0): `operator <agent> --mode followup|collect|interrupt|status`.
3. **Progress log** (v3.15.0): `progress <agent> --run ID <note>` and `status-runtime`.
4. **Doctor** (v3.15.0): local health checks and one-runtime-per-agent warnings.
5. **Idempotency keys** (v3.15.0): duplicate suppression for companion-originated actions.
6. **Runtime scaffold** (v3.16.0): `init`, `roles`, `workflows`, `approve`, `report`.
7. **Provider registry** (v3.16.0): `providers init/list/show/check/render`.

Deferred:

- **Integrated headless `run` wrapper**: the repo ships the hardened
  `examples/headless_runner.py`; folding that lifecycle into `m8shift-runtime.py run`
  remains a future companion increment.

No v1 feature may require changing the core `LOCK` format.

## Acceptance criteria

- Starting two companion instances for the same agent produces one lane owner and one
  queued/refused runtime.
- If the UI stops after `wait`, `presence.json` exposes that no live runtime is waiting.
- When `status --json` is `AWAITING_CODEX`, `watch codex` emits a concrete resume
  prompt without claiming the pen.
- Headless `run` mode remains deferred; the existing `examples/headless_runner.py`
  performs post-run verification separately.
- Operator `interrupt` is recorded and presented to the agent, but the companion does
  not steal or rewrite the pen.
- Removing `.m8shift/runtime/` loses only telemetry/inbox state, never the relay log or
  mutex state.

## Open questions

1. Should `init` optionally add `.m8shift/` to the host project's `.gitignore`, or
   should each companion provide its own `install` command?
2. What is the safest cross-platform notification mechanism that keeps the stdlib-only
   constraint? If none is acceptable, v1 should print/write prompts only.
3. Should the deferred `run` mode live in `m8shift-runtime.py` or remain as a
   dedicated example runner?
