# Runtime companion (`m8shift-runtime.py`)

See the [module index](./README.md).

## Purpose

`m8shift-runtime.py` is the optional, host-side runtime companion for the core relay. It **owns** the local, advisory sidecar surface under `.m8shift/`: per-agent **presence** lanes (`watch`), the **operator inbox** (`operator`), **long-turn progress** notes (`progress`), **turn-ready/stale/blocked/done notifications** (`notify`, with `stdout`/`file`/`bell`/`os`/`hook` tiers), the **provider/agent registry** (`providers`), **advisory model/task routing** (`route recommend`), **local approval** records (`approve`), **run reports** (`report`), **bounded JSONL retention** (`retention`), **role/workflow contracts** (`roles`/`workflows`), the RFC 047 **headless listener lifecycle** (`listener start/stop/status/logs` — supervising `examples/headless_runner.py` lanes), and read-only **headroom** estimation and **doctor** diagnostics. It does **not** own the pen: it never edits `M8SHIFT.md` or the LOCK directly, never becomes an authority for whose turn it is, and never routes turns. The listener in particular is a **supervisor, not a routing authority**: it polls the LOCK read-only, launches at most one bounded runner turn per wake, and the runner *child* performs the normal relay workflow (`claim --refresh` TTL extension, `append`) through the core. Since RFC 049 PR B, an EXPLICITLY LAUNCHED listener additionally makes two bounded core argv calls while its child turn is alive — `claim <agent> --refresh` near TTL/2 (TTL extension + audit-only beat) and `heartbeat <agent> --source runtime-listener --cadence-seconds N` (the PROTECTIVE beat) — and still never plain-claims, force-claims, appends, releases or completes; all pen authority and binding checks stay in `m8shift.py`. It reads the relay state through `m8shift.py` (subprocess `status --json` / imported helpers) and delegates any pen action — a `headroom --checkpoint` session report or a `headroom --pause-on` pause — back to the core so the LOCK stays single-owner. It performs no network mutation; the only external calls are best-effort OS-notifier/hook subprocesses under the `os`/`hook` notify tiers, the runner/provider child a listener wake launches, and — for the `launchd`/`systemd`/`windows` listener backends — explicit bounded argv calls to the local service manager (`launchctl`/`systemctl`/`schtasks`/`taskkill`); all of these are host-local processes, never a network service.

## Ownership diagram

```mermaid
flowchart LR
    user["Operator / agent"]:::actor
    script["m8shift-runtime.py"]:::script
    core["m8shift.py (core relay)"]:::script
    presence[".m8shift/runtime/presence.json"]:::state
    ledgers[".m8shift/runtime/*.jsonl&#8203;<br/>inbox · progress · runs · approvals"]:::state
    notify[".m8shift/runtime/notify/*"]:::state
    registry[".m8shift/providers.json + routing/*.json"]:::state
    listeners[".m8shift/runtime/listeners/*&#8203;<br/>pid · state · backend · service defs&#8203;<br/>+ logs/&lt;agent&gt;-listener.log"]:::state
    runner["examples/headless_runner.py&#8203;<br/>(one bounded turn)"]:::script
    lock["M8SHIFT.md LOCK"]:::lock

    user --> script
    script -- "watch" --> presence
    script -- "operator / progress / approve" --> ledgers
    script -- "notify" --> notify
    script -- "providers / route (read)" --> registry
    script -- "listener start/stop/status/logs" --> listeners
    script -. "liveness while child alive: claim --refresh + heartbeat (core argv)" .-> core
    script -. "listener wakes ONE runner turn" .-> runner
    runner -. "claim --refresh / append via core" .-> core
    script -. "status / headroom read relay via core" .-> core
    core -- "sole owner" --> lock
    script -. "headroom --checkpoint / --pause-on delegate to core" .-> core

    classDef actor fill:#fef3c7,stroke:#b45309,color:#1f2937
    classDef script fill:#dbeafe,stroke:#2563eb,color:#111827
    classDef state fill:#dcfce7,stroke:#16a34a,color:#111827
    classDef lock fill:#fee2e2,stroke:#dc2626,color:#111827
```

Legend:

| Color | Meaning |
|-------|---------|
| Blue | executable module |
| Green | generated local state |
| Red | relay LOCK authority |
| Amber | human or agent actor |

The dashed edges are the boundary: the companion never directly **writes** the LOCK — it reads via core helpers/`status --json` (or, for the listener's wake/liveness decisions, its own bounded direct read-only parser) and delegates every mutation (headroom checkpoint/pause, the RFC 049 liveness calls) to `m8shift.py` argv. It never writes `M8SHIFT.md` itself. The runner child owns the normal relay workflow; the explicitly launched listener's own core surface is exactly two bounded liveness argv calls while its child is alive (`claim --refresh` near TTL/2 and the protective `heartbeat` verb, RFC 049 PR B) — it never plain-claims, appends, releases or completes, and it writes the LOCK only through those core verbs, never directly.

## Command surface

`Mutates` classifies FILE mutation only. `read-only` = no writes; `local-state` = writes under `M8SHIFT.*` or `.m8shift/`; no command performs `repository-code` or `external` (network) mutation. (`headroom --checkpoint` is the one exception that reaches project files — it delegates a session-report write to the core. The `listener` service backends additionally register/unregister the generated definition with the *user's* service manager via explicit bounded argv calls — host-local, never network.)

| Command | Mutates | Reads | Writes | Notes |
|---------|---------|-------|--------|-------|
| `init [--agents CSV] [--force] [--json]` | local-state | roster via core (falls back to `claude,codex`) | `.m8shift/README.md`, `roles/*.md`, `workflows/default-code-review.json`, `policies/approvals.md`, `providers.json`, `routing/{models,skills}.json`, `runtime/presence.json`, `runtime/notify.config.json`, `.gitignore` | Scaffolds the optional companion tree; only writes missing files unless `--force`. |
| `watch <agent> [--session S] [--run R] [--interval 5] [--stale-after 300] [--no-progress-warn-after 0] [--no-progress-block-after 0] [--once] [--takeover-stale] [--no-notify] [--json]` | local-state | `M8SHIFT.md` LOCK (via core), `runs.jsonl`/`progress.jsonl`, `notify.config.json` | `runtime/presence.json`, `notify/*` + `notify/log.jsonl` | Advisory one-lane-per-agent presence loop; refreshes presence, emits a resume prompt, and (unless `--json`/`--no-notify`) a notification. Owning a lane held by a *different, fresh* session is refused; `--takeover-stale` only overrides a stale lane. |
| `notify config [--enable stdout,file,bell,os,hook] [--os-preset ...] [--hook-argv ... \| --hook-json ...] [--dedup-window-seconds N] [--show] [--json]` | local-state (config) | `notify.config.json` | `notify.config.json` (only when a flag changes it) | `target=config` edits notification settings; `stdout` is always kept. |
| `notify <agent> --event turn-ready\|stale\|blocked\|done [--message M] [--prompt-file F] [--json]` | local-state | `notify.config.json`, LOCK (via core) | `notify/<agent>.prompt`, `notify/<agent>.event.json`, `notify/log.jsonl` | One-shot notification across configured tiers with dedup; `os`/`hook` tiers spawn a best-effort local subprocess (never `shell=True`), degrading to stdout/file on failure. |
| `operator <agent> --mode followup\|collect\|interrupt\|status [--idempotency-key K] <message>` | local-state | roster via core, `idempotency.jsonl` | `runtime/inbox/<agent>.jsonl`, `idempotency.jsonl` | Queues one operator message with a required-behavior hint; a repeated `--idempotency-key` is ignored. |
| `progress <agent> --run R <message>` | local-state | roster via core | `runtime/progress.jsonl` | Appends one long-turn progress event. |
| `status-runtime [<agent>] [--brief] [--json]` | read-only | core `status --json`, `presence.json`, `inbox/*`, `runs.jsonl`, `progress.jsonl`, headroom inputs, context RTK adapter status | none | Aggregate human/JSON view of relay + runtime sidecars + headroom + surfaced context-pack status. |
| `headroom [<agent>] [--json] [--checkpoint] [--pause-on warning\|high] [--reason R] [--window-status ...] [--window-reason ...] [threshold flags]` | read-only (default); local-state + delegated session-report write with `--checkpoint`/`--pause-on` | `M8SHIFT.md` turns (via core), `runs.jsonl` checkpoints | `runs.jsonl` (checkpoint record) and, via core subprocess, a session report + `pause` | Local proxy estimate of context-window pressure. `--pause-on` requires `<agent>` + `--reason` and delegates the actual pause to `m8shift.py`. |
| `doctor [--json] [--stale-after 300]` | read-only | core status, `presence.json`, all runtime JSONL, `notify.config.json`, `providers.json`, `routing/*`, gitignore, `runtime/listeners/*` + `runtime/logs/*-listener.log` sizes | none | Read-only diagnostics; exits `1` if any finding is `error` severity. Includes the nine advisory RFC 047 `listener.*` findings (see below); never queries a service manager (the backend-probe seam supplies host facts). |
| `providers init [--agents CSV] [--force]` | local-state | roster via core | `.m8shift/providers.json` | Writes the host-side registry (with opt-in `examples`). |
| `providers list [--json]` / `providers show <agent>` | read-only | `providers.json` | none | Inspect registry entries. |
| `providers check [<agent>] [--json]` | read-only | `providers.json`, `os.environ` for `requires_env` | none | Validates the registry (argv arrays, modes, env allowlists); exits `1` on any `error`. |
| `providers render <agent> [--prompt P] [--run R] [--json]` | read-only | `providers.json` | none | Renders the platform-selected argv with `$M8SHIFT_*` substituted. Does **not** launch anything; exits non-zero if the entry is missing/invalid/argv-less. |
| `route recommend --task-type T [--skill S] [--input-tokens 0] [--self MODEL] [--json]` | read-only | `routing/models.json`, `routing/skills.json` | none | Advisory: recommends the cheapest model clearing the floor/capabilities/context, or fail-safes to the pen holder. Never launches; exits `1` on manifest error. |
| `roles list [--json]` / `roles show <name>` | read-only | `.m8shift/roles/*.md` | none | Behavioral role contracts. |
| `workflows list [--json]` / `workflows show <name>` | read-only | `.m8shift/workflows/*.json` | none | Local workflow definitions. |
| `approve <run> <gate> --by X --decision approved\|rejected\|waived [--reason R]` | local-state | — | `runtime/approvals.jsonl` | Appends one local human/agent approval record. |
| `report <run> [--json] [--write]` | read-only (default); local-state with `--write` | `runs.jsonl`, `progress.jsonl`, `approvals.jsonl` | `.m8shift/runs/<run>/report.md` (only with `--write`) | Summarizes one run id. |
| `retention prune [--keep 1000] [--no-archive] [--json]` | local-state | all runtime JSONL ledgers | rewrites each ledger to the last N rows; appends pruned rows to `runtime/archive/` unless `--no-archive` | Fixed-row-cap prune. |
| `retention apply [--dry-run] [--no-archive] [--json]` | local-state (no-op unless policy present + enabled) | `runtime/retention.json`, ledgers | pruned ledgers + `runtime/archive/` | Applies the opt-in retention policy; exits `1` on policy error. |
| `retention policy show [--json]` | read-only | `runtime/retention.json` | none | Shows the effective policy (`absent`/`configured`/`malformed`); exits `1` on policy error. |
| `listener start --agent A (--cmd-file F \| --provider) [--backend auto\|local\|launchd\|systemd\|windows] [--dry-run] [--foreground] [--restart] [--poll-interval 20] [--max-ticks 0] [--max-retries 3] [--max-backoff 300] [--runner PATH] [--service-payload]` | local-state (`--dry-run` = read-only) | LOCK fields (direct read-only parse; mutated ONLY core-mediated via the RFC 049 liveness calls below), profile (`--cmd-file` `m8shift.listener.profile.v1` JSON or the agent's `providers.json` entry), listener sidecars, `runs.jsonl` | `runtime/listeners/<A>.pid` + `<A>.json` + (service backends) `<A>.backend.json` and the generated service definition, `runtime/logs/<A>-listener.log`; while a child turn is alive, INDIRECTLY (through `m8shift.py` argv): the LOCK TTL (`claim --refresh` near TTL/2) and `.m8shift/holder-heartbeats/<A>.json` (protective `heartbeat` verb) | RFC 047 supervisor: polls the relay with **zero model spend** and wakes **exactly one** bounded runner turn on `AWAITING_<A>` (or `IDLE` for the single permitted `start_on_idle` starter, or a `--resume-working` retry of A's own `stuck_working` lock while retry budget remains). Refuses a live listener unless `--restart` (which also clears a persisted halt), refuses a second IDLE starter, repairs a stale pid file before starting. `--dry-run` validates the profile and prints the full plan (backoff ladder, runner argv preview, rendered service definition + install/uninstall argv) and writes **nothing**. Service backends wrap the *same* `listener start --foreground` payload; `--service-payload` is internal (written into generated definitions). |
| `listener stop --agent A [--grace 10]` | local-state | `<A>.pid`, `<A>.backend.json` | removes `<A>.pid` (only after confirmed death) + the generated service definition and backend record | TERM the **whole process group**, wait `--grace` seconds, then KILL (Windows: `taskkill /PID <pid> /T /F`, never POSIX signals). Also runs the recorded service-manager uninstall argv steps and deletes the generated definition (path-contained to `runtime/listeners/`), even when no process was left to kill. Exits `1` if the pid survives TERM/KILL (pid file kept for inspection). |
| `listener status --agent A [--json] [--repair]` | read-only (`--repair` may remove a stale pid file) | `<A>.pid`/`<A>.json`/`<A>.backend.json`; read-only service-manager query when the recorded backend matches the host | `<A>.pid` removal only with `--repair` on a **stale** pid | Renders `ALIVE`/`STALE`/`DEAD`/`HALTED` — halted is persisted sidecar state, shown even when the process is gone — plus phase, consecutive failures, last run/classification, and the installed backend with its `loaded`/`not-loaded`/`unknown` service state and last service error. `--repair` never touches a live listener. |
| `listener logs --agent A [--tail 50]` | read-only | `runtime/logs/<A>-listener.log` | none | Prints the last N log lines; exits non-zero when no log exists for the agent. |

## Inputs and outputs

**Files read**

- `M8SHIFT.md` — the LOCK/roster: most companion reads go through `m8shift.py` (`status --json` subprocess or imported `load_or_die`/`get_lock`/`active_agents`); the listener's wake/liveness decisions use its own bounded direct read-only parser. Neither path grants authority.
- `.m8shift/runtime/*` — `presence.json`, `runs.jsonl`, `progress.jsonl`, `approvals.jsonl`, `idempotency.jsonl`, `inbox/<agent>.jsonl`, `notify.config.json`, `notify/log.jsonl`, `retention.json`.
- `.m8shift/providers.json` and `.m8shift/routing/{models,skills}.json` — registry and advisory routing manifests.
- `.m8shift/providers/*.json` — operator-owned `m8shift.listener.profile.v1` listener profiles (argv array, `cwd`, `env_allowlist`, `start_on_idle`); scanned for the at-most-one-starter guard and `doctor`.
- `.m8shift/runtime/listeners/<agent>.pid` / `<agent>.json` / `<agent>.backend.json` and `.m8shift/runtime/logs/<agent>-listener.log` — listener process, state, backend-record, and log sidecars (`listener status/logs`, `doctor`).
- For the listener loop only: the `M8SHIFT.md` LOCK fields, parsed **read-only** to decide sleep vs wake — a missing or invalid relay is neutral (the loop waits; it never repairs and never launches).
- `.m8shift/roles/*.md`, `.m8shift/workflows/*.json`, `.m8shift/policies/*.md` — contracts scaffolded by `init`.
- `.m8shift/context/adapters/rtk-shell-output.json` and `.m8shift/context/metrics.jsonl` — surfaced read-only by `status-runtime`/`doctor` (owned by the context companion, see the honesty note below).

**Files written** (all under `M8SHIFT.*` / `.m8shift/`, atomically via `os.replace`; JSONL appends use `O_APPEND|O_NOFOLLOW` with symlink rejection and mode `0600`)

- `runtime/presence.json` (`watch`), `runtime/inbox/<agent>.jsonl` (`operator`), `runtime/progress.jsonl` (`progress`), `runtime/approvals.jsonl` (`approve`), `runtime/idempotency.jsonl`, `runtime/runs.jsonl` (`headroom --checkpoint`).
- `runtime/notify.config.json`, `runtime/notify/<agent>.prompt`, `runtime/notify/<agent>.event.json`, `runtime/notify/log.jsonl` (`notify`).
- `runtime/archive/*` (retention archival), `.m8shift/runs/<run>/report.md` (`report --write`).
- INDIRECT, core-mediated only (RFC 049 PR B, while a listener's child turn is alive): the LOCK `expires` field (`claim --refresh` near TTL/2) and `.m8shift/holder-heartbeats/<agent>.json` (the protective `heartbeat` verb) — both through bounded `m8shift.py` argv calls, never written by this companion directly.
- `runtime/listeners/<agent>.pid`, `runtime/listeners/<agent>.json` (`m8shift.listener.state.v1`: phase `polling`/`backoff`/`halted`, consecutive failures, last run id/classification, `start_on_idle`, runtime version), `runtime/listeners/<agent>.backend.json` (`m8shift.listener.backend.v1`: installed backend, label, service file, uninstall argv steps, last error), and — for `launchd`/`systemd`/`windows` backends — the generated service definition (`<label>.plist` / `<label>.service` / `<label>.task.json`) in the same directory (`listener start/stop`).
- `runtime/logs/<agent>-listener.log` — the listener's loop log, rotated **writer-side at 5 MiB, keeping 3 generations** (`<log>.1`…`<log>.3`, oldest dropped). `runs.jsonl` is explicitly exempt from this rotation: it is the runtime ledger and only the `retention` commands may prune it.
- The `init`/`providers init` scaffold set listed in the command table, plus a `.m8shift/.gitignore` marking `runtime/`, `runs/`, `cache/`, `tmp/` as ignored generated state.

**Environment variables honored**

- `M8SHIFT_RTK` — self-declared `on`/`off` (accepts `1/true/yes/on/enabled/rtk` and `0/false/no/off/disabled/native`), recorded into the presence row's `rtk` field. Any other value warns and is treated as `off`.
- `CI` — forces headless behavior: the `bell`, `os`, and `hook` notification tiers are skipped (also skipped when stdout is not a TTY).
- Provider entries may declare `requires_env`; `providers check` verifies those names exist in `os.environ`.
- `M8SHIFT_LISTENER_BACKEND_PROBE` — JSON object overriding the backend-probe facts (`platform`, `launchctl`, `systemctl`, `schtasks`, `gui_session`, `user_session`, `protected_folder`); a test/debug seam so backend selection never has to touch a real service manager. An invalid value exits on `listener start` and becomes a `listener.backend_probe` warning in `doctor`.
- `M8SHIFT_LISTENER_LOG_MAX_BYTES` — overrides the 5 MiB listener-log rotation threshold (invalid/non-positive values fall back to the default).
- `M8SHIFT_LISTENER_DETACHED` — internal marker set on the detached child so the loop knows it owns its log/pid files; not for operator use.

**Exit behavior**

- Precondition/validation failures call `sys.exit("m8shift-runtime: <message>")` → message to stderr, non-zero exit (e.g. bad `--interval`, unknown notify tier, unsafe session/run id, a lane owned by a fresh different session without `--takeover-stale`, `--pause-on` without `<agent>`/`--reason`).
- `watch` returns `2` when the `--no-progress-block-after` threshold trips (companion loop blocked); `0` on `--once`; otherwise it loops.
- `doctor`, `providers check`, `route recommend`, `retention apply`, `retention policy show` return `1` when an `error`-severity finding is present, else `0`.
- `providers render` exits non-zero if the entry is missing, invalid, or has no argv.
- `listener start` exits non-zero on an invalid agent/flags/profile, a live listener without `--restart`, a second IDLE starter, a missing runner script, or a failed **required** service-manager install step (the error is persisted in `<agent>.backend.json` for `doctor`). The supervising loop itself returns `0` when the relay reaches `DONE` or `--max-ticks` is hit. `listener stop` returns `1` when the pid survives TERM/KILL; `listener logs` exits non-zero when the log is missing. All other commands return `0` on success.

## Safe examples

```bash
# mutates-local-state — scaffold the optional companion tree under .m8shift/
python3 m8shift-runtime.py init
```

```bash
# safe — read-only aggregate view of relay + runtime sidecars + headroom (JSON)
python3 m8shift-runtime.py status-runtime --json
```

```bash
# mutates-local-state — append a long-turn progress note for one run
python3 m8shift-runtime.py progress claude --run demo-run "compiled; running tests"
```

```bash
# illustrative — advisory model pick; needs populated .m8shift/routing/*.json,
# prints a recommendation only (never launches a model)
python3 m8shift-runtime.py route recommend --task-type adversarial-verify --input-tokens 8000
```

```bash
# safe — validate the listener profile and print the full launch plan (backoff
# ladder, runner argv preview, rendered service definition); writes NOTHING
python3 m8shift-runtime.py listener start --agent codex \
  --cmd-file .m8shift/providers/codex.json --dry-run
```

```bash
# mutates-local-state — supervise one headless lane (detached local backend),
# inspect it, then stop it (process group + any installed service definition)
python3 m8shift-runtime.py listener start --agent codex --cmd-file .m8shift/providers/codex.json
python3 m8shift-runtime.py listener status --agent codex --json
python3 m8shift-runtime.py listener logs --agent codex --tail 20
python3 m8shift-runtime.py listener stop --agent codex
```

## Failure modes

- **`lane '<agent>' is already owned by session '<x>'; rerun with --takeover-stale only after it is stale`** (`watch`) — a second managed runtime is claiming a live lane. Use a distinct `--session`, or wait; only pass `--takeover-stale` once the other lane is genuinely stale (`--takeover-stale` on a still-fresh lane is also refused).
- **`watch` exits `2`** — the `--no-progress-block-after` window elapsed with no new progress/run event. This is advisory: record progress, inspect `status-runtime`/`doctor`, or ask the operator for a handoff. No automatic force recovery is ever performed.
- **`notify` warnings `runtime.notify_os` / `runtime.notify_hook` … "not found; degraded to stdout/file"** — the configured OS notifier or hook argv[0] is not on `PATH` (or the hook looks like a shell string / has a non-literal placeholder). Notifications still land via `stdout`/`file`; fix the argv or `--os-preset`.
- **`notify suppressed: dedup`** — an identical `agent`+`event` fired inside the dedup window; expected, not an error. Lower `--dedup-window-seconds` if you need it sooner.
- **`unknown agent <a>` / `--by must be an agent/operator name`** — the name is not in the `M8SHIFT.md` roster (or fails the `[a-z][a-z0-9_-]*` shape). Register it through the core first.
- **`unsafe run id` / `unsafe --session value`** — the id contains `/`, `\`, `:`, `.`/`..`, or illegal characters. Use a plain slug.
- **`refusing to append through symlink …`** — a path under `.m8shift/runtime/` is (or traverses) a symlink. The companion refuses to follow it; remove the symlink.
- **`doctor` / `providers check` findings** — `error` severity means a broken registry/manifest/ledger (bad schema, argv-as-string, missing `requires_env`, malformed JSONL) and a non-zero exit; `warning`/`info` (stale presence, missing anchor, no-progress) are advisory. Malformed JSONL/JSON sidecars are reported as diagnostics, never as core relay failures.
- **`route recommend` → "fail-safe to pen-holder"** — the task-type is unknown or no model clears the floor/capabilities/context; routing is advisory and defers to whoever holds the pen rather than guessing.
- **`headroom --pause-on` errors** — missing `<agent>` or `--reason`, or the target is not the holder / not in a pausable state; the pause is delegated to `m8shift.py` and fails loudly rather than touching the LOCK here.
- **`retention apply` prints "no-op"** — `retention.json` is absent or `enabled:false`. Populate and enable the policy, or use `retention prune --keep N` for a one-shot fixed cap.
- **`listener for '<agent>' is already running (pid N); stop it first or rerun with --restart`** — one listener per agent lane. `--restart` replaces the live process *and* clears a persisted halted phase; a stale pid file (process dead) is repaired automatically before start and reported.
- **`listener status` shows `STALE`** — the pid file exists but the process is gone (crash, reboot). Repair with `listener status --repair`, `listener stop`, or a fresh `listener start`; `doctor` reports it as `listener.dead`.
- **`listener status` shows `HALTED`** — the loop hit `--max-retries` consecutive failed turns (`non_completion`/`stuck_working`/`invalid_relay`/infrastructure classes; `external_transition` and `suspended` are neutral and never burn the budget). The halt is **persisted** in `<agent>.json`: it survives process restarts and is honored by OS service managers too (generated definitions use launchd `KeepAlive=false` / systemd `Restart=no`, so nothing resurrects a halted lane). A halted loop stays resident for `status`/`logs` but launches nothing; inspect the logs and the relay, then clear it explicitly with `listener start --restart`. No force-claim is ever attempted — the relay is left for operator recovery.
- **`backend <requested> → local: <reason>`** — the requested/auto backend cannot be hosted and the start visibly degrades to the portable local detach. Printed reasons include: `launchctl`/`systemctl`/`schtasks` not available on this host, no GUI session for a launchd LaunchAgent (SSH), no systemd user session (`XDG_RUNTIME_DIR` missing), and — under `auto` only — a project under a macOS protected folder. Semantics never change with the backend; only the lifecycle wrapper does.
- **`listener.protected_folder`** (`doctor`) — the project sits under a macOS TCC-protected user folder (`~/Documents`, `~/Desktop`, `~/Downloads`, iCloud Drive), where a launchd LaunchAgent is often denied access (`Operation not permitted`). `--backend auto` already falls back to `local` there; an **explicit** `--backend launchd` still proceeds as the operator's choice. Use `--backend local` or grant the service access.
- **`listener.backend_failed`** (`doctor` / `listener status` service error) — a required service-manager install step failed; the one-line error is persisted in `<agent>.backend.json` so you can see *why* the service is absent. Fix the reported cause or fall back to `--backend local`.

`doctor` emits nine advisory `listener.*` findings (RFC 047 Phase E; all read-only, never repairing):

| Finding | Severity | Meaning |
|---------|----------|---------|
| `listener.not_installed` | warning | an agent is configured for headless use (`providers.json` `mode=headless/hybrid` or a listener profile) but no listener was ever started |
| `listener.dead` | warning | pid file exists but the process is gone |
| `listener.backend_failed` | warning | the installed service backend recorded a failure |
| `listener.protected_folder` | warning | macOS protected-folder project; launchd likely to fail |
| `listener.version_skew` | warning | listener state / core / runner version differs from this companion |
| `listener.repeated_non_completion` | warning | ≥ 2 consecutive failed turns in the state sidecar or a trailing `non_completion` streak in `runs.jsonl` |
| `listener.halted` | warning | a persisted halted phase awaits an explicit `listener start --restart` |
| `listener.multiple_starters` | warning | more than one agent has `start_on_idle=true` |
| `listener.log_too_large` | info | a listener log reached the rotation threshold; the owning listener rotates it at its next write |

**Honesty note on the surfaced RTK / compression line.** `status-runtime` and `doctor` display a context-adapter status such as `RTK: ON (pinned, compressing packs)` plus a `last pack` `compression_ratio`. These are **read-only surfaces of the context companion's state**, not runtime work: RTK here is the identity-pinned (`sha256`) `rtk-shell-output` adapter, a **mode-specific lossy semantic filter** for shell output (e.g. `rtk err`/`test`/`git-log`) — it is **not** a compressor and has no standalone compression percentage. The `compression_ratio` shown comes from `.m8shift/context/metrics.jsonl`, which the context companion writes for its own prose-compression backend (Kompress/Headroom), and is unrelated to RTK. This module neither compresses nor filters; it only reports what the context companion recorded.

## Related RFCs and tests

- Owning design: [RFC 009 — Runtime companion](../rfc/009-rfc-runtime-companion.md) and [RFC 010 — Runtime patterns](../rfc/010-rfc-runtime-patterns.md).
- Command families: [RFC 014 — Provider management](../rfc/014-rfc-provider-management.md), [RFC 024 — Doctor split](../rfc/024-rfc-doctor-split.md), [RFC 025 — Status-runtime](../rfc/025-rfc-status-runtime.md), [RFC 026 — Sidecar retention](../rfc/026-rfc-sidecar-retention.md), [RFC 027 — Notifications](../rfc/027-rfc-notifications.md), [RFC 039 — Model/task routing](../rfc/039-rfc-model-task-routing.md) and [RFC 043 — Routing principle](../rfc/043-rfc-routing-principle.md), [RFC 040 — AI session usage monitoring](../rfc/040-rfc-ai-session-usage-monitoring.md) and [RFC 036 — Token-window exhaustion](../rfc/036-rfc-token-window-exhaustion.md) (headroom), [RFC 047 — Headless liveness: runner final-state and listener lifecycle](../rfc/047-rfc-headless-liveness-runner-listener.md) (the `listener` family; builds on [RFC 020 — Headless runner hardening](../rfc/020-rfc-headless-runner-hardening.md), [RFC 028 — Headless command templates](../rfc/028-rfc-headless-command-templates.md), and [RFC 046 — Interactive/headless modes](../rfc/046-rfc-interactive-headless-runner-install.md)).
- Module reference: [RFC 045 — Module reference and executable examples](../rfc/045-rfc-module-reference-examples.md).
- Related: [RFC 034 — Companion adapter interface](../rfc/034-rfc-companion-adapter-interface.md), [RFC 037 — Agent context compression backends](../rfc/037-rfc-agent-context-compression-backends.md), [RFC 042 — Compression backend routing](../rfc/042-rfc-compression-backend-routing.md), [RFC 044 — Complete initialization and companion install](../rfc/044-rfc-complete-init-companion-install.md), [RFC 023 — Agent token footprint](../rfc/023-rfc-agent-token-footprint.md).
- Tests: [`tests/test_m8shift_headroom.py`](../../../tests/test_m8shift_headroom.py) (headroom estimation and checkpoint records); [`tests/test_m8shift.py`](../../../tests/test_m8shift.py) `TestRFC047ListenerPR1` / `TestRFC047ListenerPR2` (listener lifecycle, backoff, halted persistence, backend selection/fallback, rotation, doctor findings) and `TestRFC047PhaseA` (runner classification and `claim --refresh`).
