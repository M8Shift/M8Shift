# RFC 040 — AI Session Usage Monitoring and Usage-Limit Cooldowns

Status: draft (authored by Codex; Claude-reviewed and placed)  
Target stage: optional runtime companion  
Authors: M8Shift maintainers  
Date: 2026-06-30  
Renumbered: authored as "RFC 036" in the source packet; renumbered to **040** here because RFC 036 is already the shipped `headroom` / token-window RFC (see the relationship note below). RFC 039 is reserved for the routing RFC (#67).

## Summary

M8Shift should support an optional usage-monitoring companion that watches AI session usage for local coding agents such as Claude Code and Codex. When a monitored session reaches a configurable threshold, for example 90% of a five-hour or weekly usage window, the companion should pause the M8Shift shift until the relevant usage window resets, notify the other agents, and recommend a long, low-noise wait interval.

The core relay remains passive. The monitoring layer does not call models, does not proxy provider traffic, does not store provider credentials in `M8SHIFT.md`, and does not directly edit the relay file. Provider-specific usage readers are adapters around existing local tools and local provider state.

The main operational goal is simple:

```text
Do not let an active Claude/Codex shift blindly burn through a session limit.
Pause before the cliff, wait cheaply, then resume when tokens return.
```

Amazingly, “do nothing for a while” still needs an RFC. Here we are.

---

## Reviewer notes (Claude — placement + boundary review)

These subsections were added when placing the RFC in the repository. They record the review that
accompanied adoption; the design body below is Codex's draft, preserved.

### Relationship to shipped RFC 036 (`headroom`) — a different axis

M8Shift already ships [036-rfc-token-window-exhaustion.md](036-rfc-token-window-exhaustion.md) (the
runtime `headroom` guard). That RFC and this one guard **two different exhaustion axes and must not
be conflated**:

- **RFC 036 — context-window exhaustion.** The *per-turn* proxy/model **context window** filling up
  (e.g. ">150k of a 200k context"): a single turn getting too large. The signal is per-turn context
  size; the remedy is checkpoint and pause the turn.
- **RFC 040 — usage-window exhaustion.** The *rolling account* **usage / rate-limit window** (5-hour
  or weekly subscription budget) approaching its cap across many turns. The signal is a provider
  usage ratio; the remedy is a `cooldown` until the window **resets**, then resume.

They are complementary: a shift can be fine on context yet near its weekly limit, or vice versa.
Implementations should surface both without one masking the other.

### Generic-first: Claude + Codex are the phase-1 adapters, not the model

Per the multi-provider requirement, the design is **provider-neutral by construction**: the adapter
manifest (`name` / `agent` / `provider` / `kind` / `command`) and the normalized snapshot schema
carry no Claude/Codex-specific shape. Claude Code and Codex are simply the **phase-1 adapters**.
Additional providers — **Gemini CLI, GitHub Copilot CLI, Vibe, Goose, and the other coding agents
`ccusage` already reads** — are future adapters added under the *same* manifest and schema, with no
core change. The core `cooldown` command and the snapshot / hold sidecars never name a provider.

### Adapter security: reuse the RFC 034 hardened runner, do not reinvent

The usage adapters (`claude-monitor`, the Codex CLI RPC, `ccusage`) are **subprocess adapters** —
the same security class as the RFC 034 shell-output adapter runner shipped in `m8shift-context.py`.
The implementation MUST route through that hardened machinery rather than write a second subprocess
path: **argv arrays only** (no shell string), **resolved-path + hash identity pinning** with
**fail-closed** on mismatch, **size-capped stdout**, **stderr diagnostic-only**, a bounded
**timeout**, and **gitignored** sidecars. The security section below is consistent with this; the
point is to route through one audited runner. The implementing turn should carry an **adversarial
security review** of that subprocess path before merge — subprocess execution is a live security
surface.

---

## Motivation

Long Claude/Codex coding shifts can consume a rolling usage window before the task is complete. If the active agent reaches a hard limit mid-turn, the relay can stall in a worse state:

- the active agent may stop before appending a useful handoff;
- the peer agent may continue polling too frequently;
- the operator may lose context about why the shift stopped;
- headless runners may spend tokens merely discovering that nothing changed.

M8Shift already has a `PAUSED` state, `pause`, `resume`, `wait --interval`, runtime sidecars, operator inboxes, progress events, and `status-runtime`. RFC 040 defines how to use those surfaces, plus a small new command surface, to make usage-limit pauses explicit, auditable, and cheap.

---

## Current M8Shift capabilities this RFC builds on

M8Shift already has the primitives needed for most of the design.

### Core relay

The core protocol has a `PAUSED` state. Agents in `PAUSED` must not claim the pen and should wait for a human or explicit resume scope.

Existing relevant commands:

```bash
python3 m8shift.py status --json
python3 m8shift.py wait <agent> --interval N
python3 m8shift.py pause <holder> --reason "..."
python3 m8shift.py resume <agent> --reason "..."
python3 m8shift.py may-i-write <agent>
```

The current `wait` command already supports configurable polling intervals. The current `pause` command records a session pause event and sets the lock to `state=PAUSED`, `holder=none`, `expires=-`. The current `resume` command resumes a paused session for a specific agent by setting `state=AWAITING_<AGENT>`.

### Runtime companion

`m8shift-runtime.py` already owns optional local sidecars under `.m8shift/runtime/`, including:

```text
.m8shift/runtime/presence.json
.m8shift/runtime/runs.jsonl
.m8shift/runtime/progress.jsonl
.m8shift/runtime/approvals.jsonl
.m8shift/runtime/inbox/<agent>.jsonl
```

It also already has operator messages and progress events:

```bash
python3 m8shift-runtime.py operator <agent> --mode interrupt "..."
python3 m8shift-runtime.py operator <agent> --mode collect "..."
python3 m8shift-runtime.py progress <agent> --run <run-id> "..."
python3 m8shift-runtime.py status-runtime --json
python3 m8shift-runtime.py report <run-id> --json
```

RFC 040 keeps usage monitoring inside the runtime companion, not inside the core mutex.

---

## Available external usage sources

This RFC does not require M8Shift to implement provider-specific scraping first. It defines a normalized interface that can consume existing tools.

### Claude Code

Recommended primary source:

```bash
claude-monitor --once --output json
```

`claude-monitor` / Claude Code Usage Monitor is useful because it exposes a machine-readable protocol, state files, provenance labels, official Claude Code statusline `rate_limits` when available, local estimates when official data is stale, and automation exit codes:

```text
0  = ok
10 = near limit
11 = limit hit
20 = indeterminate / no active session
30 = no data or config error
```

Useful surfaces:

```bash
claude-monitor --once --output json
claude-monitor --write-state --state-file ~/.claude-monitor/state/latest.json
claude-monitor --statusline
claude-monitor --warehouse --view sessions --output csv
```

Implementation note: M8Shift should prefer official/fresh `rate_limits` provenance over estimates. If only estimates are available, the pause decision should record `confidence=local_estimate`.

### Codex

Recommended sources, in priority order:

1. Native Codex CLI RPC, following the CodexBar-documented approach:

   ```bash
   codex -s read-only -a untrusted app-server
   ```

   JSON-RPC methods documented by CodexBar:

   ```text
   initialize
   account/read
   account/rateLimits/read
   ```

   Expected useful data:

   ```text
   primary_window
   secondary_window
   reset timestamps
   credits snapshot
   account identity
   ```

2. CodexBar CLI, if installed and if it exposes a stable machine-readable usage command on the local platform.

3. Local Codex logs for historical/cost usage:

   ```text
   ~/.codex/sessions/YYYY/MM/DD/*.jsonl
   ~/.codex/archived_sessions/*.jsonl
   $CODEX_HOME/sessions/...
   $CODEX_HOME/archived_sessions/...
   ```

4. `codex-stats export`, for normalized historical usage snapshots:

   ```bash
   codex-stats export codex-stats-export.json --since 30d
   ```

`codex-stats` is not a live gating source by itself. It is useful for session history, cost estimates, model/project breakdowns, and reports.

### Multi-provider local usage

`ccusage` is a useful fallback and comparison layer. It supports many local coding-agent sources, including Claude Code, Codex, OpenCode, OpenClaw, Gemini CLI, GitHub Copilot CLI, Kilo, Kimi, Qwen, Goose, and others.

Useful examples:

```bash
npx ccusage@latest
npx ccusage@latest claude daily --json
npx ccusage@latest codex daily --json
npx ccusage@latest blocks --json
npx ccusage@latest daily --all --json
```

`ccusage` is better for reports and cross-source rollups than for provider-official “pause now” decisions. Use it as:

```text
- secondary evidence
- reporting source
- cost history source
- adapter baseline
```

### API-proxyed agents

If a future M8Shift runner sends calls through a proxy such as LiteLLM, usage enforcement can become stronger. LiteLLM supports budgets, rate limits, virtual keys, team/user/key budgets, budget reset durations, and agent-level budgets/rate limits.

This does not solve local Claude Code or Codex subscription limits unless those tools route through the proxy. It is a separate integration mode:

```text
provider CLI subscription mode → local usage adapters
API proxy mode                 → proxy budgets/rate limits
```

### Observability tools

Langfuse, Helicone, Braintrust, Phoenix, OpenLIT, and OpenTelemetry-style tracing are good for API-call observability, cost analysis, and traces. They are not primary local subscription-limit gates unless the agent traffic flows through an instrumented SDK or proxy.

---

## Non-goals

This RFC does not:

- proxy Claude Code or Codex traffic;
- infer private billing truth from guesses;
- store provider credentials in M8Shift files;
- read browser cookies or Keychain by default;
- add provider SDKs to `m8shift.py`;
- let the runtime companion steal a valid `WORKING_*` pen;
- automatically force-recover active locks;
- require network access;
- make M8Shift a billing dashboard.

That last one is apparently necessary to say out loud, because dashboards reproduce like mold.

---

## Design principles

### 1. Core remains passive

`m8shift.py` remains the authority for relay state. Usage monitoring lives in `m8shift-runtime.py` or a sibling companion such as `m8shift-usage.py`.

### 2. Provider readers are adapters

Usage sources are invoked through argv arrays or read from explicitly configured state files. No shell interpolation.

### 3. Provenance is mandatory

Every normalized usage value must include a provenance label:

```text
official
local_estimate
proxy_reported
historical_estimate
manual
unknown
```

A 90% official Claude statusline signal and a 90% reconstructed local estimate are not the same thing. Pretending otherwise is how software grows teeth.

### 4. Pause is cooperative when someone is working

If `state=WORKING_<agent>`, the runtime companion must not mutate the core relay behind the holder’s back. It should queue an interrupt asking the holder to pause at the next safe point.

If the relay is not actively working, the companion may start a usage cooldown using the new command proposed below.

### 5. Waiting should consume no model tokens

During cooldown, agents should wait in a shell/runtime loop, not by repeatedly prompting the model. For interactive chat agents, the correct behavior is to report the pause and stop. The orchestrator or human should wake the agent near the resume time.

---

## Proposed new command: `cooldown`

The existing `pause` command requires a current holder. That is correct for ordinary work pauses, but usage cooldowns also need to park an `IDLE` or `AWAITING_*` relay before the next agent starts burning tokens.

Add a core command:

```bash
python3 m8shift.py cooldown \
  --until 2026-06-30T22:15:00Z \
  --reason "claude primary window at 91%; wait for reset" \
  [--for claude] \
  [--source usage-monitor] \
  [--wait-interval 300]
```

### Semantics

`cooldown` sets:

```text
holder:  none
state:   PAUSED
expires: -
note:    cooldown until <ISO> for <agent|any>: <reason>
```

It appends a session event:

```json
{
  "event": "pause",
  "kind": "usage_cooldown",
  "until": "2026-06-30T22:15:00Z",
  "resume_for": "claude",
  "source": "usage-monitor",
  "recommended_wait_interval_seconds": 300,
  "reason": "claude primary window at 91%; wait for reset"
}
```

### Allowed states

`cooldown` is allowed from:

```text
IDLE
AWAITING_<AGENT>
PAUSED only with --replace and a later/clearer cooldown
```

`cooldown` is refused from:

```text
WORKING_<AGENT>
DONE
```

For `WORKING_<AGENT>`, the runtime companion must queue an interrupt to the active holder instead:

```bash
python3 m8shift-runtime.py operator <agent> \
  --mode interrupt \
  "Usage limit near threshold. Pause at the next safe point with: python3 m8shift.py pause <agent> --reason 'usage cooldown until ...'"
```

### Why not just extend `pause`?

Extending `pause` to allow non-holder pauses from `IDLE`/`AWAITING_*` would work, but `cooldown` makes the policy explicit. It separates “the holder paused work” from “the runtime parked the relay to avoid a provider limit.”

---

## Proposed runtime commands

Add a runtime usage group:

```bash
python3 m8shift-runtime.py usage init
python3 m8shift-runtime.py usage adapters list
python3 m8shift-runtime.py usage adapters check
python3 m8shift-runtime.py usage snapshot [--agent claude|codex] [--json]
python3 m8shift-runtime.py usage guard [--agent claude|codex] [--apply] [--json]
python3 m8shift-runtime.py usage watch [--apply] [--interval 60]
python3 m8shift-runtime.py usage status [--json]
python3 m8shift-runtime.py usage wait <agent> [--interval auto] [--max-block 900] [--quiet]
python3 m8shift-runtime.py usage resume [--agent claude|codex] [--apply]
```

### `usage snapshot`

Reads configured adapters and emits normalized snapshots.

### `usage guard`

Checks the current relay state and current usage snapshots. If usage is above the pause threshold, it either:

- calls `m8shift.py cooldown` if the relay is idle/awaiting;
- queues an interrupt if the relay is working;
- leaves `DONE` alone.

### `usage watch`

Runs the guard repeatedly with a low-cost local interval.

### `usage wait`

A cooldown-aware wait loop for headless runners. It sleeps outside the model loop and prints minimal output. It should return periodically before common tool/process timeouts.

Recommended behavior:

```text
if PAUSED with usage_cooldown:
  sleep in chunks using recommended interval
  print only start/end/heartbeat unless --verbose
  exit 75 if still paused after --max-block
  exit 0 if resumed or DONE
```

### `usage resume`

If a usage cooldown is active and its reset time has passed, resume the relay for the stored `resume_for` agent or an explicit `--agent`.

It must verify:

```text
state == PAUSED
cooldown sidecar exists
now >= resume_after + grace
provider snapshot no longer shows limit-hit, unless --force-with-reason
```

---

## Usage adapter manifest

File:

```text
.m8shift/usage/adapters.json
```

Example:

```json
{
  "schema": "m8shift.usage.adapters.v1",
  "adapters": [
    {
      "name": "claude-monitor",
      "agent": "claude",
      "provider": "anthropic-claude",
      "kind": "subprocess_json",
      "command": ["claude-monitor", "--once", "--output", "json"],
      "near_limit_exit_codes": [10],
      "limit_hit_exit_codes": [11],
      "timeout_seconds": 10,
      "failure_policy": "warn_open",
      "provenance_preference": ["official", "local_estimate"]
    },
    {
      "name": "codex-cli-rpc",
      "agent": "codex",
      "provider": "openai-codex",
      "kind": "codex_app_server_rpc",
      "command": ["codex", "-s", "read-only", "-a", "untrusted", "app-server"],
      "methods": ["initialize", "account/read", "account/rateLimits/read"],
      "timeout_seconds": 15,
      "failure_policy": "warn_open",
      "provenance_preference": ["official", "local_estimate"]
    },
    {
      "name": "ccusage-codex",
      "agent": "codex",
      "provider": "openai-codex",
      "kind": "subprocess_json",
      "command": ["npx", "ccusage@latest", "codex", "daily", "--json", "--offline"],
      "timeout_seconds": 15,
      "failure_policy": "warn_open",
      "role": "reporting"
    }
  ]
}
```

### Failure policy

Allowed values:

```text
warn_open       emit warning, do not pause
fail_closed     pause when usage cannot be determined
skip_adapter    ignore adapter
```

Default: `warn_open`.

`fail_closed` is only acceptable for explicit operator policy. Otherwise a broken monitor can freeze the relay, which is the kind of “safety” that makes systems unusable and then gets bypassed.

---

## Normalized snapshot schema

Each adapter output is normalized to:

```json
{
  "schema": "m8shift.usage.snapshot.v1",
  "ts": "2026-06-30T20:45:00Z",
  "agent": "claude",
  "provider": "anthropic-claude",
  "adapter": "claude-monitor",
  "status": "ok",
  "provenance": "official",
  "confidence": "high",
  "windows": [
    {
      "id": "primary",
      "kind": "rolling_session",
      "label": "5h",
      "used_ratio": 0.91,
      "remaining_ratio": 0.09,
      "used_tokens": 80080,
      "limit_tokens": 88000,
      "reset_at": "2026-06-30T22:15:00Z",
      "source": "claude statusline rate_limits"
    },
    {
      "id": "weekly",
      "kind": "weekly",
      "label": "weekly",
      "used_ratio": 0.52,
      "remaining_ratio": 0.48,
      "reset_at": "2026-07-02T00:00:00Z",
      "source": "claude statusline rate_limits"
    }
  ],
  "cost": {
    "used_usd": 35.42,
    "limit_usd": 50.0,
    "used_ratio": 0.708
  },
  "messages": {
    "used": 123,
    "limit": null,
    "used_ratio": null
  },
  "warnings": []
}
```

### Decision ratio

The pause decision uses the maximum actionable ratio across windows:

```text
decision_ratio = max(window.used_ratio for actionable windows)
```

A window is actionable only if it has:

```text
used_ratio != null
reset_at != null or status in {near_limit, limit_hit}
provenance != unknown unless fail_closed
```

---

## Sidecars

Runtime-generated files:

```text
.m8shift/runtime/usage.jsonl
.m8shift/runtime/usage-hold.json
.m8shift/runtime/usage-adapter-errors.jsonl
```

### `usage.jsonl`

Append-only event stream:

```json
{
  "schema": "m8shift.runtime.event.v1",
  "type": "usage.snapshot",
  "ts": "2026-06-30T20:45:00Z",
  "agent": "claude",
  "payload": {
    "snapshot": {
      "schema": "m8shift.usage.snapshot.v1",
      "agent": "claude",
      "provider": "anthropic-claude",
      "adapter": "claude-monitor",
      "status": "ok"
    }
  }
}
```

### `usage-hold.json`

Current active usage cooldown:

```json
{
  "schema": "m8shift.usage.hold.v1",
  "state": "active",
  "created_at": "2026-06-30T20:45:00Z",
  "resume_after": "2026-06-30T22:16:00Z",
  "resume_for": "claude",
  "reason": "claude primary window at 91%; wait for reset",
  "trigger": {
    "threshold": 0.9,
    "agent": "claude",
    "provider": "anthropic-claude",
    "adapter": "claude-monitor",
    "window": "primary",
    "used_ratio": 0.91,
    "reset_at": "2026-06-30T22:15:00Z",
    "provenance": "official"
  },
  "recommended_wait_interval_seconds": 300,
  "notified_agents": ["claude", "codex"]
}
```

---

## Threshold policy

Default policy:

```json
{
  "schema": "m8shift.usage.policy.v1",
  "pause_threshold": 0.90,
  "warn_threshold": 0.80,
  "resume_threshold": 0.75,
  "reset_grace_seconds": 60,
  "max_quiet_wait_seconds": 900,
  "default_wait_interval_seconds": 300,
  "min_wait_interval_seconds": 30,
  "max_wait_interval_seconds": 600,
  "failure_policy": "warn_open"
}
```

### Recommended wait interval

The wait interval should be large enough to avoid noisy polling but small enough to avoid tool timeouts and stale recovery delays.

Recommended default function:

```python
def recommended_wait_interval(seconds_remaining: int) -> int:
    if seconds_remaining > 1800:
        return 300
    if seconds_remaining > 600:
        return 180
    if seconds_remaining > 120:
        return 60
    return 30
```

Add jitter of ±10% when several agents are waiting, so Claude and Codex do not wake in lockstep like tiny distributed idiots.

---

## Notification behavior

When a cooldown starts, the runtime companion should notify all active agents through the existing operator inbox.

Example:

```bash
python3 m8shift-runtime.py operator claude --mode interrupt \
  "Usage cooldown active: Claude primary window is at 91%. Pause at the next safe point. Expected resume after 2026-06-30T22:16:00Z. Use a quiet wait interval around 300s."

python3 m8shift-runtime.py operator codex --mode collect \
  "M8Shift is paused for Claude usage cooldown until 2026-06-30T22:16:00Z. Do not claim or start new model work. Use m8shift-runtime.py usage wait codex --interval auto."
```

The relay `status` should also show `state=PAUSED` and a note that includes the cooldown reason. Agents that do not read runtime inboxes still see the core pause state.

---

## State transitions

### Idle or awaiting agent hits threshold

```text
AWAITING_CLAUDE
  usage guard sees claude at 91%
  → m8shift.py cooldown --for claude --until <reset+grace>
  → PAUSED
  → runtime notifies claude and codex
  → usage wait loops sleep locally
  → after reset, usage resume calls m8shift.py resume claude
  → AWAITING_CLAUDE
```

### Active holder hits threshold

```text
WORKING_CLAUDE
  usage guard sees claude at 91%
  → runtime queues interrupt to claude
  → claude reaches safe point
  → claude runs m8shift.py pause claude --reason "usage cooldown until ..."
  → PAUSED
  → runtime records active hold
  → after reset, usage resume resumes for claude or next planned agent
```

The runtime must not take the pen away from an active holder.

### Limit already hit

If the adapter reports limit-hit:

```text
used_ratio >= 1.0
or adapter exit code in limit_hit_exit_codes
or provider window status = limited
```

Then:

- if idle/awaiting: cooldown immediately;
- if working: interrupt immediately and request an emergency handoff/pause;
- if the holder can no longer produce a useful handoff, the operator may later use normal stale-lock recovery after expiry.

---

## Agent instructions during cooldown

Agents must treat `PAUSED` as no-work state.

For headless runners:

```bash
python3 m8shift-runtime.py usage wait <agent> --interval auto --max-block 900 --quiet
```

For plain core fallback:

```bash
python3 m8shift.py wait <agent> --interval 300
```

For interactive chat agents:

```text
Report: "M8Shift is paused for usage cooldown until <time>. I will not poll in chat."
Stop the turn.
Let the orchestrator or human resume/wake near reset.
```

Do not simulate waiting by repeatedly asking the model to check the time. That is not waiting. That is burning tokens to cosplay as a clock.

---

## Security and privacy

Usage adapters must follow these rules:

1. No provider credentials in `M8SHIFT.md`.
2. No raw OAuth tokens in sidecars.
3. No browser cookie reading by default.
4. No Keychain access by default.
5. Adapter command must be argv array, never shell string.
6. Adapter stdout must be size-capped.
7. Adapter stderr must be diagnostic, not prompt content.
8. Sidecars must be gitignored.
9. Official provider data wins over local estimates.
10. Unknown usage must not pause by default.
11. Runtime monitor must not force a valid `WORKING_*` lock.
12. Every pause/resume caused by usage monitoring must be auditable.

---

## Implementation plan

### Phase 1 — RFC and docs only

Add:

```text
docs/en/rfc/040-rfc-ai-session-usage-monitoring.md
docs/en/guides/usage-monitoring.md
```

### Phase 2 — read-only runtime usage snapshots

Add to `m8shift-runtime.py` or a sibling `m8shift-usage.py`:

```bash
usage init
usage adapters list
usage adapters check
usage snapshot --json
usage status --json
```

No core state changes yet.

### Phase 3 — guard and advisory notifications

Add:

```bash
usage guard --json
usage guard --apply
usage watch --apply
```

`--apply` may only write runtime sidecars and operator inbox messages.

### Phase 4 — core cooldown command

Add:

```bash
m8shift.py cooldown --until ISO --reason TEXT [--for AGENT] [--source SOURCE] [--wait-interval N]
```

Acceptance requirement: remove `.m8shift/runtime/` and M8Shift still works.

### Phase 5 — automatic resume

Add:

```bash
m8shift-runtime.py usage resume --apply
m8shift-runtime.py usage wait <agent>
```

### Phase 6 — native Codex adapter

Implement direct Codex CLI RPC adapter:

```text
codex -s read-only -a untrusted app-server
initialize
account/read
account/rateLimits/read
```

This avoids requiring CodexBar for live gating while preserving CodexBar as the implementation reference.

---

## Acceptance criteria

- `m8shift.py` remains dependency-free.
- Usage monitoring lives in runtime/companion code.
- `status --json` remains read-only and stable.
- `cooldown` refuses from `WORKING_*`.
- `cooldown` records a session pause event with `kind=usage_cooldown`.
- `resume` can resume from usage cooldown with a clear reason.
- Runtime usage snapshots include provenance.
- `claude-monitor` adapter supports `--once --output json` and exit codes 10/11.
- Codex adapter supports either Codex CLI RPC or a documented fallback.
- Unknown usage defaults to warning, not pause.
- Sidecars are valid JSON/JSONL and gitignored.
- `doctor` or runtime `doctor` reports invalid usage sidecars.
- Tests cover threshold crossing, unknown snapshots, working-holder interrupts, idle cooldown, awaiting cooldown, resume-after-reset, and malformed adapter output.
- No test needs real Claude/Codex credentials.

---

## Test matrix

### Core tests

```text
cooldown from IDLE → PAUSED
cooldown from AWAITING_CLAUDE → PAUSED
cooldown from WORKING_CLAUDE → refused
cooldown from DONE → refused
cooldown requires --reason and --until
cooldown rejects invalid ISO timestamps
cooldown rejects invalid --for agent
resume from PAUSED after cooldown works
status --json exposes PAUSED note
doctor accepts usage_cooldown session event
```

### Runtime tests

```text
usage snapshot normalizes claude-monitor JSON fixture
usage snapshot maps claude-monitor exit code 10 to near_limit
usage snapshot maps claude-monitor exit code 11 to limit_hit
usage guard above threshold writes usage-hold.json
usage guard above threshold from AWAITING calls cooldown when --apply
usage guard above threshold from WORKING queues interrupt only
usage guard below threshold does nothing
usage resume refuses before resume_after
usage resume applies after resume_after
usage wait exits 75 after --max-block while still paused
usage wait exits 0 after resume
```

### Adapter fixture tests

Store fake adapter outputs under:

```text
tests/fixtures/usage/claude-monitor-official.json
tests/fixtures/usage/claude-monitor-estimate.json
tests/fixtures/usage/codex-rpc-rate-limits.json
tests/fixtures/usage/ccusage-codex-daily.json
```

---

## Open questions

1. Should `cooldown` live in `m8shift.py`, or should `pause` be extended with `--until --kind usage_cooldown`?
2. Should runtime usage live inside `m8shift-runtime.py` or in a new `m8shift-usage.py` companion?
3. Should M8Shift support a committed `.m8shift/usage/policy.json`, or keep usage policy host-local only?
4. Should unknown usage be configurable as fail-closed per project?
5. Should `wait` gain `--quiet` and `--max-seconds`, or should that remain a runtime-only concern?

Recommendation:

```text
- Add `cooldown` to core because IDLE/AWAITING cooldown needs a core transition.
- Keep all provider integrations in runtime/usage companion.
- Keep policy host-local by default.
- Add `usage wait` in runtime first; only extend core `wait` later if needed.
```

---

## References

- Claude Code Usage Monitor / `claude-monitor`: https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor
- PyPI `claude-monitor`: https://pypi.org/project/claude-monitor/
- CodexBar: https://github.com/steipete/codexbar
- CodexBar Codex provider notes: https://github.com/steipete/codexbar/blob/main/docs/codex.md
- `codex-stats`: https://pypi.org/project/codex-stats/
- `ccusage`: https://github.com/ccusage/ccusage
- LiteLLM budgets/rate limits: https://docs.litellm.ai/docs/proxy/users
