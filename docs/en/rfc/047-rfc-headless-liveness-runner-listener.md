# RFC 047 — Headless liveness: final-state enforcement and listener lifecycle

- Status: implemented
- Date: 2026-07-03
- Target version: v3.47.0 (Phase A shipped in v3.46.0; Phases B–E in v3.47.0)
- Tracks: GitHub #17, #21; cross-references #6 without closing it
- Builds on: [RFC 020 Headless runner hardening](020-rfc-headless-runner-hardening.md), [RFC 035 Interactive listener gap](035-rfc-interactive-listener-gap.md), [RFC 046 Interactive/headless modes and runner install](046-rfc-interactive-headless-runner-install.md)
- Related: [RFC 027 Notifications](027-rfc-notifications.md), [RFC 028 Headless command templates](028-rfc-headless-command-templates.md), [RFC 034 Companion adapter interface](034-rfc-companion-adapter-interface.md), [RFC 040 AI session usage monitoring](040-rfc-ai-session-usage-monitoring.md)

## Summary

RFC 046 made the interactive/headless distinction explicit. RFC 047 turns the
headless side into an operationally safe liveness layer.

It has two phases:

1. **Runner final-state enforcement** (#17): after a provider command exits, the
   runner re-reads relay state and the turn transcript. Success is based first on
   **authorship**: this agent must have authored a turn numbered greater than the
   pre-run turn, or the relay must be `DONE`. State-only diffs are not enough. If
   the relay is still open and the agent still owes the turn, the run is
   **non-completion**, not success.
2. **Listener lifecycle companion** (#21): ship a versioned companion command that
   supervises headless runners with zero model spend while it is not the agent's
   turn, then wakes exactly one bounded provider turn when the relay reaches
   `AWAITING_<agent>`. It provides start/stop/status/logs, PID/process-group
   management, stale-PID detection, bounded backoff, OS backend selection, and
   doctor diagnostics.

This RFC intentionally touches only the **TTL self-refresh action-half** of issue #6:
during a long headless turn, a runner may refresh its own valid `WORKING_<agent>`
lock before expiry through a new refresh-only core guard. It does **not** close #6's
broader holder-liveness model, force-claim policy, or worktree-ownership model.

### v3.64 compatibility amendment (#208/#216/#217/#219)

Before a real listener start creates pid/state sidecars or launches a provider,
it MUST probe the runner with `--handshake`. The response is one JSON line, no
larger than 4096 bytes, with this additive schema:

```json
{
  "schema": "m8shift.runner.handshake.v1",
  "version": "3.64.0",
  "capabilities": [
    "bounded-tty-tee-v1",
    "environment-write-probe-v1",
    "runner-exit-v2"
  ],
  "options": ["--agent-model", "--once", "--resume-working"]
}
```

The complete emitted `options` list is source-derived. Probing is read-only and
MUST NOT inspect relay state, write sidecars, or launch the provider. The
listener classifies runner evidence as `CURRENT`, `LEGACY`, `BROKEN`, or
`ABSENT`; only `CURRENT` proceeds. Dry-run does not execute the probe and reports
`not_probed`.

Provider stdout/stderr flows through a bounded TTY tee. Public/persisted evidence
contains only byte/line counts and allowlisted signature IDs. Text that merely
resembles a sandbox refusal is not authoritative: `environment-write-probe-v1`
must confirm the configured working directory is unwritable before the listener
classifies `environment_blocked` and halts.

## Problem

`examples/headless_runner.py` is currently a foreground loop. It can launch a
provider, refresh its own TTL, and validate coarse post-run progress, but two
dogfood failures remain:

- A provider can exit "successfully" while the relay remains open and the same
  agent still owes work. A zero-memory model can create a tracker item, emit a final
  answer, and exit while state remains `AWAITING_<agent>` or `WORKING_<agent>`.
  The runner must not classify that as success.
- Real unattended use requires a **listener lifecycle** around the runner:
  background start/stop/status/logs, stale PID handling, process-group termination,
  bounded backoff, provider command profiles, and platform-specific service handling.
  Projects have been forced to hand-build this layer.

The core invariant remains unchanged: `m8shift.py` is passive and stdlib-only. The
listener is a companion/runtime layer, not a new routing authority.

## Design principles

1. **Passive core preserved.** `m8shift.py` does not become a daemon and does not
   launch providers.
2. **Companion writes sidecars, not relay state.** The listener/runner may write
   `.m8shift/runtime/*` diagnostics and process files. It must not edit
   `M8SHIFT.md` directly and must never force-steal a pen.
3. **One turn per wake.** When state becomes `AWAITING_<agent>`, the listener launches
   exactly one provider turn through the runner. It then re-checks state before
   deciding whether to retry, sleep, or report non-completion.
4. **Zero model spend while waiting.** Polling LOCK state is cheap local file I/O.
   Provider commands are launched only on `AWAITING_<agent>` or designated `IDLE`
   start.
5. **Failure is explicit.** A provider exit code of zero is not enough. The relay
   state must also be acceptable.
6. **Platform backends are lifecycle adapters, not different semantics.** `local`,
   `launchd`, `systemd`, and Windows backends expose the same listener contract.
7. **One retry owner.** The listener owns consecutive failure counts and backoff.
   The runner is a one-shot classifier that returns status and sidecar events.
8. **Stdlib-only means Python stdlib-only.** OS service managers may be driven through
   explicit argv subprocess calls behind backend adapters; no Python third-party
   dependency, shell interpolation, daemon in core, or network service is introduced.

## Phase 1 — Runner final-state enforcement (#17)

### Current runner behavior to tighten

RFC 020 already introduced post-run validation. The rule must now explicitly cover
"provider final text without relay completion" cases.

Before launch, the runner records:

- `pre_state`
- `pre_holder`
- `pre_turn`
- expected agent
- whether the launch was from `AWAITING_<agent>`, `WORKING_<agent>`, or `IDLE`

After the child exits, the runner re-reads the LOCK and classifies the run.

### Classification authority

The primary authority is the turn transcript, not a state-only diff.

The runner parses closed turn markers:

```text
M8SHIFT:TURN <n> <agent> BEGIN
```

Let `pre_turn` be the integer turn number before launch. A run is successful when
either:

- the post-run relay is `DONE`; or
- the transcript contains at least one closed turn authored by **this agent** with
  `n > pre_turn`.

This rule handles the fast healthy ping-pong race: this agent can append turn `n+1`,
the peer can immediately append turn `n+2`, and the post-run state can already be
`AWAITING_<agent>` again. That is still success for this run because this agent
authored `n+1`.

State and turn relation then refine the classification.

### Total classification table

Definitions:

- `same`: post `turn == pre_turn`
- `advanced`: post `turn > pre_turn`
- `reset`: post `turn < pre_turn`, missing turn after a valid pre-turn, or a new
  session/reset event detected
- `authored_by_me`: transcript contains a turn by this agent with `n > pre_turn`
- `integrating`: LOCK has an active `integrating:` sentinel

| Post state | Turn relation / authorship | Runner status | Retry counter |
|------------|----------------------------|---------------|---------------|
| `DONE` | any | `completed` | reset |
| any valid state | `authored_by_me` | `advanced` | reset |
| invalid/missing LOCK after bounded OSError retry | any | `invalid_relay` | increment |
| any state | `reset` | `external_transition` | unchanged |
| `PAUSED` | any non-reset | `suspended` | unchanged |
| `IDLE` | `same` after starter launch | `non_completion` | increment |
| `IDLE` | `advanced` but not `authored_by_me` | `external_transition` | unchanged |
| `AWAITING_<agent>` | `same` | `non_completion` | increment |
| `AWAITING_<agent>` | `advanced` but not `authored_by_me` | `external_transition` | unchanged |
| `WORKING_<agent>` holder is this agent | `same`, no `integrating` | `stuck_working` | increment |
| `WORKING_<agent>` holder is this agent | `same`, `integrating` active | `external_transition` | unchanged |
| `AWAITING_<peer>` | `same` or advanced not authored by me | `external_transition` | unchanged |
| `WORKING_<peer>` | `same` or advanced not authored by me | `external_transition` | unchanged |
| other valid state | any | `external_transition` | unchanged |

`non_completion`, `stuck_working`, and `invalid_relay` are failures for the run even
when the provider process exits with rc 0. `suspended` is neutral: it must not burn
retries, because a usage cooldown or operator pause is not a provider failure.

For stable malformed content, classify immediately as `invalid_relay`. For transient
read errors such as Windows file-sharing errors during atomic replace, retry the read
briefly (for example up to 3 attempts over ~1 second) before classifying.

### Exit code and retry

For a one-shot run:

- `completed` / `advanced` => exit 0
- `non_completion` / `stuck_working` / `invalid_relay` => non-zero
- `external_transition` => dedicated non-zero code, not counted as provider failure by
  a supervising listener
- `suspended` => dedicated neutral code
- timeout => existing timeout non-zero behavior

The normative `runner-exit-v2` mapping is 0 success, 1 classified run failure,
2 argparse refusal, 3 external transition, 4 suspended, and 5 infrastructure
failure/timeout. The run ledger is the primary classification authority. A
listener may infer `runner_refused_argv` from exit 2 only when no authoritative
`run.ended` classification exists; it MUST NOT overwrite a recorded timeout or
non-completion.

For a continuous runner/listener:

- record a runtime event;
- listener increments the consecutive failure count only for `non_completion`,
  `stuck_working`, `invalid_relay`, and timeout;
- listener leaves the counter unchanged for `external_transition` / `suspended`;
- listener applies bounded backoff;
- keep the run eligible for retry until `--max-retries` is reached;
- after max retries, enter `halted` and leave the relay for operator recovery.

No automatic `claim --force` is introduced.

### Runtime ledger events

The runner should write sidecar events such as:

```json
{
  "schema": "m8shift.runtime.event.v1",
  "event": "run.non_completion",
  "run_id": "20260703T190000Z-codex-12345678",
  "agent": "codex",
  "pre": {"state": "AWAITING_CODEX", "holder": "codex", "turn": "99"},
  "post": {"state": "AWAITING_CODEX", "holder": "codex", "turn": "99"},
  "reason": "provider exited without claim/append/done"
}
```

Existing `run.ended` events should carry a `status` value that matches the new
classification.

### Tests for Phase 1

Minimum tests:

1. provider exits rc 0 without touching relay while state is `AWAITING_<agent>` =>
   runner returns non-zero and records `run.non_completion`;
2. provider claims but exits before append while state is `WORKING_<agent>` =>
   runner returns non-zero and records `stuck_working`;
3. provider appends to peer => runner returns zero and records `advanced`;
4. provider closes `DONE` => runner returns zero and records `completed`;
5. malformed/missing LOCK after child exit => non-zero `invalid_relay`;
6. no automatic force-claim occurs in any failure path.
7. fast peer ping-pong: this agent authors `n+1`, peer authors `n+2`, post state is
   `AWAITING_<agent>` => runner returns zero because `authored_by_me`;
8. operator reset / `init --force` during run => `external_transition`, not success;
9. `PAUSED` during run => `suspended`, no retry burn;
10. active `integrating:` sentinel prevents same-turn `WORKING_<agent>` from being
    classified as ordinary stuck work.

## Phase 2 — Listener lifecycle companion (#21)

### Surface

Add the listener under the existing runtime companion:

```bash
python3 m8shift-runtime.py listener start --agent codex --cmd-file .m8shift/providers/codex.json
python3 m8shift-runtime.py listener stop --agent codex
python3 m8shift-runtime.py listener status --agent codex
python3 m8shift-runtime.py listener logs --agent codex
python3 m8shift-runtime.py listener start --agent all
```

Do not create a new shipped script for v3.46. A separate `m8shift-listener.py` would
increase version-lock, checksum, installer, and kit-manifest surface without adding a
separate authority model.

### Listener loop

The listener is a cheap supervisor:

1. read LOCK;
2. if `DONE`, stop cleanly;
3. if `AWAITING_<agent>`, launch exactly one runner/provider turn;
4. if `IDLE` and this agent is the configured starter, launch exactly one turn;
5. if `WORKING_<agent>` and the previous provider process is dead, launch a retry
   only when the previous run was `stuck_working`, retry budget remains, and no
   force-claim is needed;
6. otherwise sleep;
7. after every runner return, re-read state and apply the Phase-1 classification;
8. back off on failures; reset backoff on progress.

No provider process is launched while state is `AWAITING_<peer>`, `WORKING_*`,
`PAUSED`, `IDLE` without starter permission, or `DONE`, except for the explicit
`WORKING_<agent>` stuck-work retry described above. Never launch on `WORKING_<peer>`.

### Backoff

Defaults:

```text
poll interval: 20s
failure backoff: 20s -> 40s -> 80s -> 160s -> 300s cap
max consecutive failed turns: inherited from runner default, configurable
```

Backoff is owned by the listener, per agent, and stored in sidecar state so `status`
can explain why a listener is alive but sleeping. The runner reports classification;
it does not own retry counters.

### Halted state

After max retries, the listener enters a persistent `halted` phase instead of silently
exiting and being restarted into the same failure loop.

Sidecar:

```json
{
  "schema": "m8shift.listener.state.v1",
  "agent": "codex",
  "phase": "halted",
  "reason": "max_retries_after_non_completion",
  "consecutive_failures": 3,
  "last_run_id": "20260703T190000Z-codex-12345678"
}
```

`listener status` must render `HALTED` distinctly from alive/stale/dead/sleeping.
`doctor` emits `listener.halted`. A restarted listener reloads this sidecar and honors
the halt until an explicit `listener start --restart` / `listener resume` clears it.
Recommended behavior: the supervisor process may stay resident in halted phase so
status/logs remain easy to inspect, but it must not launch providers.

### PID, process groups, and logs

Runtime files live under `.m8shift/runtime/`:

```text
.m8shift/runtime/listeners/<agent>.pid
.m8shift/runtime/listeners/<agent>.json
.m8shift/runtime/logs/<agent>-listener.log
.m8shift/runtime/logs/<agent>-runner.log
.m8shift/runtime/runs.jsonl
```

Rules:

- `start` refuses when a live PID already exists unless `--restart`;
- `status` detects alive/stale/dead PID;
- `stop` terminates the whole process group, waits, then kills after grace;
- stale PID files are removed only by explicit start/status repair or stop;
- logs are append-only with bounded rotation;
- default log rotation is writer-side, 5 MiB per log, keep 3 rotated files;
- `runs.jsonl` remains the runtime ledger and is governed by existing runtime
  retention, not listener log rotation.

On Windows, do not use `os.kill(pid, 0)` as an aliveness probe. It is not POSIX
semantics. Use a backend aliveness adapter such as `OpenProcess`/`GetExitCodeProcess`
via `ctypes` or `tasklist /FI`. Stop uses `taskkill /PID <pid> /T /F` after any
documented best-effort graceful step.

### Backend selection

Backend option:

```text
--backend auto|local|launchd|systemd|windows
```

Semantics:

| Backend | Purpose |
|---------|---------|
| `local` | detach a child process from the current shell/session using stdlib process primitives; portable fallback |
| `launchd` | macOS user LaunchAgent |
| `systemd` | Linux user service |
| `windows` | Windows scheduled task or documented PowerShell background process |
| `auto` | choose the safest available backend; fall back to `local` with a clear reason |

The backend must not change relay semantics.

Backend contracts:

- POSIX local backend may use `start_new_session=True` / process groups.
- Windows backend spawns with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
  CREATE_NO_WINDOW`, redirects stdout/stderr to logs, and stops with
  `taskkill /T /F` by PID. Do not rely on `CTRL_BREAK` reaching detached children.
- `launchd` generated plists must not resurrect a halted listener indefinitely:
  use `KeepAlive=false` or an equivalent condition that honors the persisted halted
  sidecar.
- `systemd` units must not erase the retry guarantee: use `Restart=no` or bounded
  `Restart=on-failure` with `StartLimit*`, and always reload the listener state file
  before launching providers.
- Service-manager commands (`launchctl`, `systemctl`, `schtasks`, `taskkill`) are local
  argv subprocess calls behind adapters. They do not violate the Python stdlib-only
  constraint, but they must be explicit argv arrays with bounded output.
- `auto` also falls back to `local` when no GUI/user service session is available
  (for example SSH without a graphical session).

### macOS protected-folder detection

On macOS, service managers may lack permission to access user-protected folders.
The listener should detect common symptoms:

- current project path under a protected user folder;
- backend is `launchd`;
- service bootstrap/log shows `Operation not permitted` or `getcwd` failure;
- script exists and is executable from the interactive shell but not from the service.

Required behavior:

- `doctor` warns with a generic message;
- `listener start --backend auto` falls back to `local` when launchd is likely to fail;
- docs explain the class of failure without embedding local paths.

### IDLE starter

Starting from `IDLE` remains an explicit exception to "wake only on
`AWAITING_<agent>`".

Profile field:

```json
{
  "start_on_idle": false
}
```

Rules:

- default is false;
- at most one agent in a roster may be configured as starter;
- `doctor` emits `listener.multiple_starters` when more than one starter is configured;
- `listener start` refuses or loudly warns when a second starter would be active.

### Provider command profiles

The listener should not bake provider-specific shell strings into code.

It may consume existing RFC 028 provider command templates or a local JSON profile:

```json
{
  "schema": "m8shift.listener.profile.v1",
  "agent": "codex",
  "argv": ["codex", "exec", "--skip-git-repo-check", "..."],
  "cwd": ".",
  "env_allowlist": ["HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER"],
  "start_on_idle": false
}
```

Rules:

- argv arrays only;
- no shell interpolation;
- dangerous provider flags may be present only in explicit operator-owned profiles or
  examples that are clearly marked as examples;
- generated defaults should be conservative.

### Doctor checks for Phase 2

Add advisory findings:

| Check | Severity | Condition | Fix |
|-------|----------|-----------|-----|
| `listener.not_installed` | warning | headless mode configured, no listener companion installed | install runtime/listener companion |
| `listener.dead` | warning | PID file exists but process is gone | `listener status --repair` or `listener start` |
| `listener.backend_failed` | warning | backend reports service failure | use suggested backend/fix |
| `listener.protected_folder` | info/warning | macOS protected-folder symptoms detected | use `--backend local` or grant service permission |
| `listener.version_skew` | warning | listener/runner version differs from core | update matching companions |
| `listener.repeated_non_completion` | warning | repeated Phase-1 failures | inspect provider prompt/profile and relay status |
| `listener.halted` | warning | listener reached max retries and persisted halted state | inspect logs; restart/resume explicitly |
| `listener.multiple_starters` | warning | more than one agent has `start_on_idle=true` | leave only one starter |
| `listener.log_too_large` | info | log exceeds rotation threshold | rotate/prune logs |

### Tests for Phase 2

Minimum tests:

1. `listener start --dry-run` writes no PID and prints a plan;
2. start refuses when a live PID exists;
3. stale PID is detected by status;
4. stop terminates a spawned child process group;
5. loop sleeps without launching provider while state is `AWAITING_<peer>`;
6. loop launches exactly one turn on `AWAITING_<agent>`;
7. failure backoff increases and caps;
8. backend `auto` selects local fallback when launchd is unavailable or unsuitable;
9. macOS protected-folder detector is unit-tested with synthetic paths/logs;
10. doctor emits listener findings as human output and JSON;
11. version skew between core and listener is detected;
12. logs rotate/prune without deleting active run ledger entries.
13. Windows aliveness probe never calls `os.kill(pid, 0)`; backend uses a Windows-safe
    probe seam;
14. `start_on_idle` uniqueness warning/refusal is tested;
15. `halted` survives process restart and is rendered by status/doctor;
16. backoff is a pure function tested without sleeping;
17. listener loop accepts fractional poll intervals and a `--max-ticks`/test seam so
    tests do not sleep for real backoff durations.

## Interaction with issue #6

Issue #6 remains broader than RFC 047. It covers:

- presence heartbeat decoupled from pen TTL;
- force-claim policy when a holder appears alive;
- worktree single-ownership.

RFC 047 only needs this subset:

- while a runner-launched provider is still running and the relay is
  `WORKING_<agent>` held by that same agent, the runner may run a refresh-only claim
  before expiry to refresh the lock;
- if heartbeat refresh fails, record a sidecar event and continue to post-run
  validation;
- never refresh another agent's lock;
- never use heartbeat as proof that force-claim is safe or unsafe.

Core prerequisite:

```bash
python3 m8shift.py claim <agent> --refresh
```

`--refresh` must refuse unless the current state is already `WORKING_<agent>` and
`holder == <agent>`. A plain `claim <agent>` must not be used as the runner TTL
self-refresh primitive, because a race between the runner's pre-check and the core
file lock could otherwise open a fresh `WORKING_<agent>` after the provider already
appended and the peer handed the turn back.

Closing #6 requires a later design for a separate presence sidecar and force-claim
policy. Do not mark #6 closed by implementing RFC 047.

## Protocol additions

Keep protocol-core changes budget-aware. Suggested compact addition:

```text
Headless runs are not complete just because the provider process exits. A runner must
re-read status and the turn markers after each turn; unless DONE or this agent authored
a newer turn, treat an open owed turn as non-completion and retry/back off.
```

Longer lifecycle details belong in `protocol-reference.md`, module docs, and the
listener/runner help output.

## Non-goals

- No daemon inside `m8shift.py`.
- No provider SDK.
- No network service.
- No automatic `claim --force`.
- No closure of issue #6's full liveness model.
- No guarantee that an interactive chat UI can be woken by M8Shift.
- No hidden approval of provider-specific dangerous flags.

## Implementation phases

### Phase A — final-state enforcement

- Add core `claim --refresh` before using runner TTL self-refresh.
- Tighten `examples/headless_runner.py` post-run classification.
- Parse transcript turn authorship for `authored_by_me`.
- Add runtime events and exit statuses.
- Add regression tests for provider exits without append.
- Update docs/help.

### Phase B — listener command skeleton

- Add `m8shift-runtime.py listener ...` subcommands.
- Add dry-run and profile validation.
- Add PID/log paths and status rendering.
- Add pure/testable backoff and backend-probe seams.

### Phase C — local backend + lifecycle

- Implement local detach backend.
- Implement start/stop/status/logs.
- Add process-group termination and stale PID detection.
- Add persistent `halted` sidecar and status/doctor rendering.

### Phase D — OS backend adapters

- Add launchd/systemd/Windows backend plans.
- Add auto-selection and protected-folder detection.
- Keep platform-specific behavior behind testable adapter functions.
- Add Windows-safe process aliveness and stop behavior.

### Phase E — doctor + docs + site

- Add doctor checks.
- Update protocol reference, module docs, README/site feature page.
- Document that headless liveness requires the companion; core remains passive.

## Definition of done

- A provider run that exits without completing the relay is visibly non-complete.
- A fast peer round-trip after this agent's successful append is classified as success,
  not false non-completion.
- A listener can be started/stopped/statused without hand-built project scripts.
- No model is called while the relay is waiting on another agent.
- Long headless turns refresh only their own valid working lock before expiry through
  `claim --refresh`.
- A halted listener is persistent and visible.
- Windows stop/status behavior is specified without POSIX-only probes.
- Doctor can explain missing/dead/skewed listener state.
- The implementation stays stdlib-only and keeps all relay mutations inside normal
  `m8shift.py claim/append/done` flows.

## Amendment — host-wake observability (#108 slice 2, design)

Slice 1 documents the distinction between a waiter and a listener. Slice 2 makes
that distinction machine-observable without changing relay authority.

### Listener capability fields

`listener status --agent AGENT` adds four additive fields to human and JSON
output: `backend_configured`, `can_invoke_agent`, `survives_parent_exit`, and
`last_successful_run`. The first reports a validated invocation profile; the
second means the resident listener can launch a bounded run now; the third
describes backend lifecycle ownership, never process residency; the last is a
timestamp or null. `ALIVE` keeps its existing meaning of process residency;
readiness is carried only by the additive `can_invoke_agent` field (consumers
that need both properties test `status == "ALIVE" && can_invoke_agent`). This
preserves CLI compatibility and avoids conflating residency with backend
readiness. Missing, malformed, stale, or unreadable sidecars degrade the
additive capability fields to false/null and remain read-only.

### Wait notice and stale-AWAITING advisory

When `wait` or `next` is attached to a TTY, it prints one concise notice that it
detects a turn but cannot invoke a completed chat/model run. Non-interactive
output and exit codes remain byte-identical.

Runtime `doctor` adds one fail-open `runtime.stale_state` info finding only when
the relay remains `AWAITING_<agent>` for more than 300 seconds, measured from
the LOCK block's `since` timestamp, and no live, invocation-capable listener is
provable. `doctor --stale-after SECONDS` overrides the 300-second default for
diagnostics and accepts a non-negative integer; age exactly equal to the
threshold is not stale, while age strictly greater is. It is advisory: no
claim, force, provider launch, or relay mutation follows. This is designed
jointly with RFC 051's stale-usage rule so both use explicit timestamps,
bounded reads, and honest last-known semantics.

Tests pin JSON types, human rendering, TTY-only notice behavior,
non-interactive byte identity, backend-vs-residency separation, threshold
boundaries, malformed sidecars, and suppression by a live capable listener.
Implementation starts only after relay-peer design review.
