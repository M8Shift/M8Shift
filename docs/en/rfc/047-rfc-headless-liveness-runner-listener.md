# RFC 047 — Headless liveness: final-state enforcement and listener lifecycle

- Status: draft
- Date: 2026-07-03
- Target version: v3.46.0
- Tracks: GitHub #17, #21; cross-references #6 without closing it
- Builds on: [RFC 020 Headless runner hardening](020-rfc-headless-runner-hardening.md), [RFC 035 Interactive listener gap](035-rfc-interactive-listener-gap.md), [RFC 046 Interactive/headless modes and runner install](046-rfc-interactive-headless-runner-install.md)
- Related: [RFC 027 Notifications](027-rfc-notifications.md), [RFC 028 Headless command templates](028-rfc-headless-command-templates.md), [RFC 034 Companion adapter interface](034-rfc-companion-adapter-interface.md), [RFC 040 AI session usage monitoring](040-rfc-ai-session-usage-monitoring.md)

## Summary

RFC 046 made the interactive/headless distinction explicit. RFC 047 turns the
headless side into an operationally safe liveness layer.

It has two phases:

1. **Runner final-state enforcement** (#17): after a provider command exits, the
   runner re-reads relay state. If the relay is still open and the agent still owes
   the turn, the run is **non-completion**, not success. The runner records that
   state and keeps the work eligible for retry/backoff instead of pretending the
   model's final text finished the relay task.
2. **Listener lifecycle companion** (#21): ship a versioned companion command that
   supervises headless runners with zero model spend while it is not the agent's
   turn, then wakes exactly one bounded provider turn when the relay reaches
   `AWAITING_<agent>`. It provides start/stop/status/logs, PID/process-group
   management, stale-PID detection, bounded backoff, OS backend selection, and
   doctor diagnostics.

This RFC intentionally touches only the **TTL action-half** of issue #6: during a
long headless turn, a runner may refresh its own valid `WORKING_<agent>` lock before
expiry. It does **not** close #6's broader holder-liveness model, force-claim policy,
or worktree-ownership model.

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

### Classification

| Post-run state | Meaning | Runner status |
|----------------|---------|---------------|
| `DONE` | session closed | `completed` |
| turn advanced and state handed to another agent | agent appended a turn | `advanced` |
| state no longer requires this agent and turn changed | progress occurred | `advanced` |
| `AWAITING_<agent>` with same turn as before | provider did not claim/append; still owed | `non_completion` |
| `WORKING_<agent>` held by same agent | provider claimed then exited before append/done | `stuck_working` |
| `WORKING_<peer>` or another holder with same turn | ambiguous external takeover | `external_transition` |
| malformed/missing LOCK | cannot prove completion | `invalid_relay` |

`non_completion`, `stuck_working`, and `invalid_relay` are failures for the run even
when the provider process exits with rc 0.

### Exit code and retry

For a one-shot run:

- `completed` / `advanced` => exit 0
- `non_completion` / `stuck_working` / `invalid_relay` => non-zero
- timeout => existing timeout non-zero behavior

For a continuous runner/listener:

- record a runtime event;
- increment the consecutive failure count;
- apply bounded backoff;
- keep the run eligible for retry until `--max-retries` is reached;
- after max retries, stop launching provider commands and leave the relay for operator
  recovery.

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

## Phase 2 — Listener lifecycle companion (#21)

### Surface

Add a versioned companion surface. The exact file can be either:

- `m8shift-runtime.py listener ...`, if the runtime companion owns process lifecycle; or
- a dedicated `m8shift-listener.py`, if keeping lifecycle separate is clearer.

The RFC requires one stable command family regardless of file placement:

```bash
python3 m8shift-runtime.py listener start --agent codex --cmd-file .m8shift/providers/codex.json
python3 m8shift-runtime.py listener stop --agent codex
python3 m8shift-runtime.py listener status --agent codex
python3 m8shift-runtime.py listener logs --agent codex
python3 m8shift-runtime.py listener start --agent all
```

If implemented as `m8shift-listener.py`, the command names stay equivalent.

### Listener loop

The listener is a cheap supervisor:

1. read LOCK;
2. if `DONE`, stop cleanly;
3. if `AWAITING_<agent>`, launch exactly one runner/provider turn;
4. if `IDLE` and this agent is the configured starter, launch exactly one turn;
5. otherwise sleep;
6. after every runner return, re-read state and apply the Phase-1 classification;
7. back off on failures; reset backoff on progress.

No provider process is launched while state is `AWAITING_<peer>`, `WORKING_*`,
`PAUSED`, `IDLE` without starter permission, or `DONE`.

### Backoff

Defaults:

```text
poll interval: 20s
failure backoff: 20s -> 40s -> 80s -> 160s -> 300s cap
max consecutive failed turns: inherited from runner default, configurable
```

Backoff is per agent and stored in sidecar state so `status` can explain why a
listener is alive but sleeping.

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
- logs are append-only with bounded rotation.

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

### Provider command profiles

The listener should not bake provider-specific shell strings into code.

It may consume existing RFC 028 provider command templates or a local JSON profile:

```json
{
  "schema": "m8shift.listener.profile.v1",
  "agent": "codex",
  "argv": ["codex", "exec", "--skip-git-repo-check", "..."],
  "cwd": ".",
  "env_allowlist": ["HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER"]
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

## Interaction with issue #6

Issue #6 remains broader than RFC 047. It covers:

- presence heartbeat decoupled from pen TTL;
- force-claim policy when a holder appears alive;
- worktree single-ownership.

RFC 047 only needs this subset:

- while a runner-launched provider is still running and the relay is
  `WORKING_<agent>` held by that same agent, the runner may run `claim <agent>` before
  expiry to refresh the lock;
- if heartbeat refresh fails, record a sidecar event and continue to post-run
  validation;
- never refresh another agent's lock;
- never use heartbeat as proof that force-claim is safe or unsafe.

Closing #6 requires a later design for a separate presence sidecar and force-claim
policy. Do not mark #6 closed by implementing RFC 047.

## Protocol additions

Keep protocol-core changes budget-aware. Suggested compact addition:

```text
Headless runs are not complete just because the provider process exits. A runner must
re-read status after each turn; if the relay is still open and this agent still owes the
turn, treat it as non-completion and retry/back off.
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

- Tighten `examples/headless_runner.py` post-run classification.
- Add runtime events and exit statuses.
- Add regression tests for provider exits without append.
- Update docs/help.

### Phase B — listener command skeleton

- Add the listener command family.
- Add dry-run and profile validation.
- Add PID/log paths and status rendering.

### Phase C — local backend + lifecycle

- Implement local detach backend.
- Implement start/stop/status/logs.
- Add process-group termination and stale PID detection.

### Phase D — OS backend adapters

- Add launchd/systemd/Windows backend plans.
- Add auto-selection and protected-folder detection.
- Keep platform-specific behavior behind testable adapter functions.

### Phase E — doctor + docs + site

- Add doctor checks.
- Update protocol reference, module docs, README/site feature page.
- Document that headless liveness requires the companion; core remains passive.

## Definition of done

- A provider run that exits without completing the relay is visibly non-complete.
- A listener can be started/stopped/statused without hand-built project scripts.
- No model is called while the relay is waiting on another agent.
- Long headless turns refresh only their own valid working lock before expiry.
- Doctor can explain missing/dead/skewed listener state.
- The implementation stays stdlib-only and keeps all relay mutations inside normal
  `m8shift.py claim/append/done` flows.
