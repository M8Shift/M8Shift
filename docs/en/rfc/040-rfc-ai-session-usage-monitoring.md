# RFC 040 — AI Session Usage Monitoring and Usage-Limit Cooldowns

Status: Phase 2/3 and Phase 4 implemented; Phase 4 provider adapters live-verified and hardened through #105 (2026-07-10)
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

1. Native Codex CLI app-server RPC:

   ```bash
   codex app-server --stdio
   ```

   Verified JSON-RPC sequence:

   ```text
   initialize
   account/rateLimits/read
   ```

   Expected useful data:

   ```text
   primary usedPercent + reset timestamp
   secondary usedPercent + reset timestamp
   ```

   The adapter must send `initialize` before `account/rateLimits/read`; calling
   the rate-limit method first returns `Not initialized`. The transport is
   newline-delimited JSON-RPC on stdio, not LSP Content-Length framing.
   The read relies on the app-server experimental API surface, so the response
   shape may drift; the adapter must fail open if that happens.

   Privacy rule: the adapter emits only normalized aggregate ratios and reset
   instants. It must not emit account identity, plan type, credits, limit names,
   provider bucket names, raw response bodies, or app-server stderr.

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
  [--wait-interval 300] \
  [--replace]
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
      "kind": "cli_json",
      "command": ["python3", "examples/usage-adapters/codex-ratelimits.py"],
      "methods": ["initialize", "account/rateLimits/read"],
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
.m8shift/runtime/usage-holds/<agent>.json
.m8shift/runtime/usage-adapter-errors.jsonl
```

The singleton examples below describe the pre-#88 design. The normative
implementation contract later in this RFC supersedes them with independently
addressable v2 target holds; `usage-hold.json` v1 is legacy recovery input only.

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

## Phase 2/3 implementation contract (2026-07 refinement)

This section makes Phase 2 (read-only snapshots) and Phase 3 (guard/advisory)
implementable. If it conflicts with earlier high-level prose, this section is the
more precise contract.

### PR A scope (reviewer-pinned read-only slice)

PR A is the first shipped slice of Phase 2. Where this subsection is narrower or
differs from the rest of the contract, **this subsection wins for the PR A
commands**; the general contract continues to govern the PR B guard family.

#### PR A command surface

PR A ships ONLY the read-only surface, in `m8shift-runtime.py`:

```bash
python3 m8shift-runtime.py usage init [--json]
python3 m8shift-runtime.py usage adapters list [--agent AGENT] [--json]
python3 m8shift-runtime.py usage adapters check [--agent AGENT] [--json]
python3 m8shift-runtime.py usage snapshot [--agent AGENT] [--json] [--raw-excerpt]
python3 m8shift-runtime.py usage status [--agent AGENT] [--json]
```

Threshold and freshness knobs are CLI flags in PR A (the host-local policy file
lands with PR B): `--warn-threshold` (default `0.80`), `--limit-threshold`
(default `1.0`) on `snapshot`/`status`, and `--stale-after-minutes` (default
`30`) on `status`. In PR A, `snapshot` **always** appends to the
`.m8shift/runtime/usage.jsonl` ledger (there is no separate `--write` mode yet);
`status` reads that ledger and writes nothing.

`usage init` scaffolds `.m8shift/usage/adapters.json`
(schema `m8shift.usage.adapters.v1`) with **disabled** example entries for the
four Phase-4 sources: `claude-jsonl-scan`, `claude-quota-keychain`,
`codex-jsonl-scan`, and `codex-ratelimits`. The JSONL scans are local
aggregate-only spent sources; the quota/rate-limit entries are disabled
`cli_json` placeholders that must be edited by the operator before use.
`usage init` also writes `.m8shift/usage/budget.example.json`; it does not write
orphan fixture files. It is idempotent and never clobbers existing files. PR A
adapter entries carry exactly: `name`, `agent`, optional `provider`, `kind`
(`cli_json` | `fixture` | `jsonl_scan`), `command` (argv array of strings — a
shell string is a config **error**), `fixture_path` (fixture kind), `scan_roots`
(`jsonl_scan` kind), `timeout_s` (number, bounded `1..60`, default `10`),
`enabled` (bool, default `false`), optional `sha256` (identity pin for
`command[0]`; mismatch fails closed), and optional `//` comments. Unknown keys
are **warnings**.
`adapters check` probes only **enabled** adapters, with a bounded argv-only
subprocess run (never a shell string, never network access by M8Shift itself);
adapter failures are appended to `.m8shift/runtime/usage-adapter-errors.jsonl`,
which is bounded to the **last 200 lines**.

#### PR A snapshot schema bytes

Adapter output is normalized to `m8shift.usage.snapshot.v1` with exactly these
fields (compact, sorted keys in the JSONL ledger):

```json
{
  "schema": "m8shift.usage.snapshot.v1",
  "agent": "claude",
  "source": {"adapter": "claude-usage-cli", "kind": "cli_json", "provenance": "official"},
  "captured_at": "2026-01-01T00:00:00Z",
  "used_tokens": 42000,
  "limit_tokens": 100000,
  "decision_ratio": 0.42,
  "windows": [
    {"kind": "session_5h", "resets_at": "2026-01-01T05:00:00Z", "used": 42000, "limit": 100000},
    {"kind": "weekly", "resets_at": "2026-01-08T00:00:00Z", "used": 130000, "limit": 500000}
  ],
  "raw_excerpt_redacted": "optional; present only with --raw-excerpt"
}
```

- `source` is an object with exactly `adapter`, `kind`, and `provenance`
  (provenance vocabulary from the design principles; anything else is recorded
  as `"unknown"` with a warning).
- `used_tokens` / `limit_tokens` and each window's `used` / `limit` are
  non-negative integers or `null`.
- `decision_ratio = round(max(used/limit across windows with used and a
  positive limit), 4)`, falling back to `used_tokens/limit_tokens`, else
  `null`.
- `windows[]` entries carry exactly `kind`, `resets_at` (UTC ISO 8601 or
  `null`), `used`, `limit`.
- `raw_excerpt_redacted` is optional, size-capped, and **never** verbatim
  provider output: secrets/token-like runs are redacted before storage, and it
  is emitted only when the operator passes `--raw-excerpt`.

The ledger event wraps that snapshot in the standard
`m8shift.runtime.event.v1` envelope with `type: "usage.snapshot"` and is
append-only: new snapshots never rewrite prior lines. Grouping events by
`agent` over time remains the advisory per-agent token timeline.

PR A readers consume one documented input shape, `m8shift.usage.fixture.v1` —
the JSON that a `claude usage`-style CLI prints on stdout (`kind: cli_json`) or
that a local status file contains (`kind: fixture`):

```json
{
  "schema": "m8shift.usage.fixture.v1",
  "agent": "claude",
  "provenance": "official",
  "captured_at": "2026-01-01T00:00:00Z",
  "used_tokens": 42000,
  "limit_tokens": 100000,
  "windows": [
    {"kind": "session_5h", "resets_at": "2026-01-01T05:00:00Z", "used": 42000, "limit": 100000},
    {"kind": "weekly", "resets_at": "2026-01-08T00:00:00Z", "used": 130000, "limit": 500000}
  ]
}
```

A synthetic sample ships in the repository under
`examples/usage-fixtures/claude.json`. The Claude normalization is first-class;
the Codex adapter is a fixture/stub path normalized to the **same** snapshot
schema.

#### PR A exit codes (read-only commands only)

For the five PR A commands, this mapping is the contract and supersedes the
general exit-code table below (which continues to apply to the PR B
guard/watch/wait/resume surface):

| Code | Meaning (PR A read-only surface) |
|-----:|----------------------------------|
| `0` | ok — including **unknown** usage (fail-open) |
| `12` | adapter or config error (invalid manifest, shell-string argv, bad timeout, identity mismatch, probe/parse failure with no usable snapshot) |
| `30` | `near_limit` **advisory** on `snapshot`/`status` when `decision_ratio >= warn threshold` |
| `40` | `limit_hit` **advisory** when `decision_ratio >= limit threshold` |

Precedence when several apply: `40` > `30` > `12` > `0`. All non-zero codes are
**advisory automation hints only** — no PR A command ever mutates the relay,
pauses anything, or blocks a shift.

#### PR A non-goals

PR A ships **no `usage guard`, no `--apply`, no watch/wait/resume, no
cooldown/pause/resume calls, no relay mutation, no provider launch, no
cooperative `WORKING_*` interrupt** (all PR B after review).

#### Unknown usage

Unknown usage (no enabled adapter, no data, or no computable ratio) yields
status `"unknown"`, exit `0`, and a warning finding — fail-open, never pause.
A snapshot older than `--stale-after-minutes` degrades to `"unknown"` for
exit-code purposes and emits a warning finding.

### PR B scope (guard / watch / wait / resume — completes the usage block)

PR B is the second shipped slice: the Phase 3 guard family plus the explicit
resume helper. Where this subsection is narrower or differs from the general
contract, **this subsection wins for the PR B commands** (`usage guard`,
`usage watch`, `usage wait`, `usage resume`); the PR A subsection keeps
governing the five read-only commands, and the general exit-code table below
remains the vocabulary this subsection pins against.

#### PR B command surface

```bash
python3 m8shift-runtime.py usage guard  [--agent AGENT] [--apply] [--json] \
    [--warn-threshold R] [--limit-threshold R] [--stale-after-minutes M]
python3 m8shift-runtime.py usage watch  [--agent AGENT] [--interval SECONDS] [--max-ticks N] [--apply] [--json] \
    [--warn-threshold R] [--limit-threshold R] [--stale-after-minutes M]
python3 m8shift-runtime.py usage wait   [--agent AGENT] [--until-ok] [--interval SECONDS] [--max-ticks N] [--json] \
    [--warn-threshold R] [--limit-threshold R] [--stale-after-minutes M]
python3 m8shift-runtime.py usage resume [--agent AGENT] [--json] \
    [--warn-threshold R] [--limit-threshold R] [--stale-after-minutes M]
```

All four share the PR A threshold/staleness knobs and the PR A verdict
vocabulary — `ok` / `near_limit` / `limit_hit` / `unknown`, computed from the
**freshest ledger snapshot per agent** in `.m8shift/runtime/usage.jsonl`; a
snapshot older than `--stale-after-minutes` degrades to `unknown` (fail-open),
exactly like `usage status`. New per-agent holds do not perform a core state
transition. The one retained core interaction is the bounded argv recovery
path for a legacy singleton hold plus an already-global usage cooldown; the
companion **never** reimplements or inlines that transition.

**`usage guard`** — advisory verdict. Without `--apply` it is fully read-only
(writes nothing anywhere, not even the ledger); the exit code is the pure
verdict mapping in the table below, and the current relay state plus any
active hold are reported in the JSON without changing the code.

**`usage guard --apply` — #88 per-agent throttle amendment.** It acts on
**`limit_hit` only** and requires `--agent` (`64` otherwise). A valid apply:

- takes its deadline exclusively from the normalized
  `snapshot.decision_window = {kind, resets_at}` that produced
  `decision_ratio`; the binding must map back to the same at-limit window and
  name a future reset. Missing, malformed, past, or mismatched attribution is
  `usage.no_binding_reset`, exit `30`, with no hold or relay mutation. There is
  no earliest-window fallback.
- atomically places or extends only
  `.m8shift/runtime/usage-holds/<agent>.json`; it never calls core `cooldown`,
  never changes `M8SHIFT.md`/LOCK, and never creates or replaces global
  `PAUSED`. This holds in `IDLE`, `AWAITING_*`, `WORKING_*`, `PAUSED`, and
  `DONE`. A peer already working is unaffected and the limited agent's record
  is still written.
- when the target already owns `WORKING_<agent>`, records an advisory hold and
  exits `12`; the current holder may checkpoint and append, but its next claim
  and any listener launch are gated. Other states apply the target hold with
  exit `11`.
- gates `wait`/`next`/`claim`/`claim --check` and the managed listener only for
  the target agent. Malformed target data fails closed for that lane only;
  peer claim/listener paths remain unaffected. Multiple target records coexist.
- does **not** reroute `AWAITING_<held-agent>` to a peer. That needs the separate
  RFC 066 governed solo-open mechanism and its debt/reconciliation contract;
  the guard emits `usage.solo_open_required` and leaves routing unchanged.

`near_limit` never applies (exit `10`), `unknown` never applies (exit `20`),
and `ok` applies nothing (exit `0`).

**`usage watch`** — poll loop: each tick re-snapshots the enabled adapters
(the PR A snapshot path, which appends to the ledger as always), evaluates
the guard verdict from the refreshed ledger, and with `--apply` follows
exactly the guard `--apply` rules above. `--max-ticks N` bounds the loop
(0 = unbounded) and fractional `--interval` (default 60) is the test seam,
mirroring the listener loop. The exit code is the final tick's guard code.
A watch tick that observes an `ok` verdict **never** resumes anything.

**`usage wait`** — token-free local blocker for cooled-down runners: each
tick re-reads the ledger verdict only. It releases with exit `0` when the
verdict is `ok` **or** `unknown` (fail-open: unknown usage must not block
forever), or only on a genuine `ok` when `--until-ok` is passed; it exits
`75` when `--max-ticks` is exhausted while still held. Fractional
`--interval` (default 30). It writes nothing and calls nothing.

**`usage resume`** — the **only** road back: explicit, never automatic. It
resolves the target as `--agent`, else a single unambiguous hold, else a legacy
cooldown note's `resume_for` (`64` when ambiguous). The verdict gate uses the
hold's agent: the limited agent must have a fresh `ok` snapshot.

- verdict not `ok` → refuse everything: relay untouched, hold untouched;
  exit `11` when still `limit_hit`, exit `10` when `near_limit` or `unknown`.
- verdict `ok` + a v2 per-agent hold and no matching legacy global cooldown →
  delete only that target record and append `usage.hold_cleared`; relay
  byte-identical, no core call, exit `0`.
- verdict `ok` + a hold and relay `PAUSED` with the legacy core cooldown note for
  that agent (`resume_for` is the agent or `any`) → call core
  `resume <agent> --reason …`, delete that agent's v2 record or v1 singleton,
  append `usage.hold_cleared`; exit `0`. This compatibility path creates no new
  global cooldowns.
- verdict `ok` + relay `PAUSED` with a cooldown note for a **different**
  agent → refuse, exit `30` (never steal another lane's cooldown).
- verdict `ok` + relay not usage-cooldown-`PAUSED` (running, `IDLE`,
  operator-`PAUSED`, `DONE`) + a hold exists → clear the stale hold only
  (delete + `usage.hold_cleared` event), **no core call** (an operator pause
  is never resumed by the usage monitor); exit `0`.
- verdict `ok` + no hold + relay not usage-cooldown-`PAUSED` → nothing to do,
  exit `0`.
- a core `resume` argv failure surfaces as exit `30` with the captured
  diagnostics; the hold is kept.

#### PR B per-agent hold bytes (#88 amendment)

Each active hold is a pretty-printed JSON object (sorted keys) at
`.m8shift/runtime/usage-holds/<agent>.json`, schema
`m8shift.usage.hold.v2`, with exactly these eight keys:

```json
{
  "schema": "m8shift.usage.hold.v2",
  "agent": "claude",
  "placed_at": "2026-07-03T09:00:00Z",
  "resets_at": "2026-07-03T11:15:00Z",
  "reason": "claude usage limit_hit (decision_ratio 1.0 >= limit threshold 1.0)",
  "source": "usage-monitor",
  "snapshot_ref": ".m8shift/runtime/usage.jsonl#2026-07-03T09:00:00Z/claude/claude-usage-cli",
  "binding_window": {"kind": "weekly", "resets_at": "2026-07-03T11:15:00Z"}
}
```

- `agent` is the limited agent; `placed_at` is the write time; `resets_at` is
  exactly the binding window's provider reset; `binding_window` proves the
  `kind`/reset attribution that triggered the hold; `source` is always
  `usage-monitor` for holds this companion writes; `snapshot_ref` points at
  the triggering ledger snapshot as
  `.m8shift/runtime/usage.jsonl#<captured_at>/<agent>/<adapter>`.
- Placement is idempotent: an existing hold for the same agent whose
  `resets_at` is at or after the candidate is kept **byte-identical**
  (`placed_at` preserved); the file is atomically rewritten only when
  `resets_at` moves strictly later (which is also the only case that
  affects no peer record.
- Clearing means deleting only the target file; the audit trail lives in
  `usage.jsonl`.
- Any PR B command that reads a hold file which does not parse or does not
  match this schema exits `40` for that target lane. A valid legacy singleton
  `usage-hold.json` v1 remains readable/clearable only for upgrade recovery.

#### PR B exit codes (guard family)

The PR A table does **not** apply here; PR B uses the general table with this
pinned per-command mapping (precedence within one run:
`40` > `64` > `30` > `70` > `12` > `11` > `10` > `20` > `0`):

| Code | `guard` / `watch` (final tick) | `wait` | `resume` |
|-----:|-------------------------------|--------|----------|
| `0` | verdict `ok` (nothing applied) | released: verdict `ok` (or `unknown` without `--until-ok`) | target hold cleared, legacy cooldown resumed, or nothing to do |
| `10` | verdict `near_limit` — advisory only, **never** applies | — | refused: verdict still `near_limit` / `unknown` |
| `11` | verdict `limit_hit`: hold recommended (no `--apply`) or target hold placed/already active (`--apply`) | — | refused: verdict still `limit_hit` |
| `12` | `--apply` while the target owns `WORKING_<target>`: advisory target hold posted; current work may finish | — | — |
| `20` | verdict `unknown` (no snapshot, stale, or no ratio) — fail-open, never applies | — | — |
| `30` | adapter/config/policy error: missing/invalid/past/mismatched binding reset; legacy recovery core failure | — | same |
| `40` | malformed target hold / incompatible hold schema | same | same |
| `64` | command-line usage error (`--apply` without `--agent`, invalid agent, non-positive `--interval`, negative `--max-ticks`) | same | same (no resolvable agent) |
| `70` | apply-time local sidecar I/O failure | — | same |
| `75` | — | `--max-ticks` exhausted while still held | — |

All non-zero codes stay advisory automation hints; JSON output carries the
full reason.

#### PR B audit events

Only `--apply`/`resume` **actions** must be recorded in
`.m8shift/runtime/usage.jsonl` (guard verdicts alone are not recorded; watch
ticks record their snapshots through the PR A snapshot path). Action events
use the standard `m8shift.runtime.event.v1` envelope with types
`usage.hold_placed`, `usage.hold_advisory`, and `usage.hold_cleared`, and a
payload carrying pre/post refs: `relay_state_before`, `relay_state_after`
(re-read after the core call), the hold bytes as written (or `null` on
clear), `snapshot_ref`, and the core argv result when a core command was
called.

#### PR B non-goals

- **No automatic resume.** Nothing in this slice resumes the relay except an
  explicit `usage resume` invocation (a watch/guard tick seeing `ok` never
  resumes; expiry of `resets_at` never resumes).
- No force-claim, no stealing or expiring `WORKING_*` locks, and no
  operator-inbox writes in this slice (the cooperative interrupt message of
  the general design is deferred).
- New applies perform no relay write. The core `resume` argv is retained only
  for recovery of a legacy singleton plus an existing global usage cooldown.
- No provider launch, no network access, no new subprocess surface beyond
  the PR A bounded runner and the core argv calls.

### Command surface

All commands live under `m8shift-runtime.py usage` for Phase 2/3. They never edit
`M8SHIFT.md`; only Phase 4 core `cooldown` may transition the relay into `PAUSED`.

```bash
python3 m8shift-runtime.py usage init [--policy PATH] [--json]
python3 m8shift-runtime.py usage adapters list [--agent AGENT] [--json]
python3 m8shift-runtime.py usage adapters check [--agent AGENT] [--json]
python3 m8shift-runtime.py usage snapshot [--agent AGENT] [--adapter NAME] [--write] [--json]
python3 m8shift-runtime.py usage guard [--agent AGENT] [--apply] [--json]
python3 m8shift-runtime.py usage watch [--agent AGENT] [--apply] [--interval SECONDS] [--once] [--json]
python3 m8shift-runtime.py usage wait AGENT [--interval auto|SECONDS] [--max-block SECONDS] [--quiet]
python3 m8shift-runtime.py usage resume [--agent AGENT] [--apply] [--json] [--force-with-reason TEXT]
```

Phase 2 ships `init`, `adapters list`, `adapters check`, `snapshot`, and `status`
if status is needed for operator display. Phase 3 ships `guard`, `watch`, and
advisory operator-inbox writes. `wait` and `resume` may be implemented in Phase 3
as local-runtime helpers, but automatic core resume remains Phase 5.

### Exit codes

The runtime companion uses exit codes as automation hints. JSON output carries the
full reason; scripts should not parse human text.

| Code | Meaning |
|-----:|---------|
| `0` | command completed; no usage hold required, or wait/resume completed successfully |
| `10` | warning threshold reached; no hold applied |
| `11` | pause threshold or limit hit; hold recommended, written, or cooldown applied |
| `12` | active holder is working; advisory interrupt queued instead of core mutation |
| `20` | no usable usage data under `warn_open`; no hold applied |
| `30` | adapter/config/policy error |
| `40` | malformed usage sidecar or incompatible schema |
| `64` | command-line usage error |
| `70` | apply-time local I/O failure |
| `75` | `usage wait` reached `--max-block` while still paused/held |

Command-specific mapping:

| Command | `0` | `10` | `11` / `12` | `20+` |
|---------|-----|------|-------------|-------|
| `snapshot` | at least one usable snapshot emitted | not used | not used | no data / config / sidecar error |
| `guard` | below warning threshold | warn-only decision | hold/cooldown recommended or applied; `12` for working-holder interrupt | unknown or adapter errors |
| `watch` | exits cleanly with no hold when `--once`, or on signal | propagated from guard | propagated from guard | propagated from guard |
| `wait` | relay resumed, DONE, or no active usage hold | not used | not used | `75` if still paused after max block |
| `resume` | resumed or nothing to do | reset not reached yet | usage still limit-hit | sidecar/config errors |

### JSONL and JSON sidecar bytes

Sidecars are UTF-8. JSONL files contain exactly one compact JSON object per line,
followed by `\n`, using deterministic key order where practical. Pretty printing is
allowed only for the single active hold file.

Runtime-generated files:

```text
.m8shift/runtime/usage.jsonl
.m8shift/runtime/usage-holds/<agent>.json
.m8shift/runtime/usage-adapter-errors.jsonl
```

#### `usage.jsonl` event

Every `usage snapshot --write`, `usage guard --apply`, and `usage watch --apply`
appends an event:

```json
{"schema":"m8shift.runtime.event.v1","type":"usage.snapshot","ts":"2026-07-03T09:00:00Z","agent":"claude","source":{"tool":"m8shift-runtime.py","version":"3.43.0"},"payload":{"snapshot":{"schema":"m8shift.usage.snapshot.v1","ts":"2026-07-03T09:00:00Z","agent":"claude","provider":"anthropic-claude","adapter":"claude-code-statusline","status":"near_limit","provenance":"official","confidence":"high","decision_ratio":0.91,"decision_window":"primary","windows":[{"id":"primary","kind":"rolling_session","label":"5h","used_ratio":0.91,"remaining_ratio":0.09,"used_tokens":80080,"limit_tokens":88000,"reset_at":"2026-07-03T11:15:00Z","source":"claude statusline rate_limits"}],"cost":null,"messages":null,"warnings":[]}}}
```

`decision_ratio` and `decision_window` are normalized convenience fields. They
duplicate information from `windows[]` so guards do not need to re-derive the
selected window after reading historical events.

The event also gives a per-agent token-consumption timeline: downstream reports can
group `usage.jsonl` by `agent`, `provider`, `adapter`, `window.id`, and time bucket,
then compare `used_tokens` deltas across snapshots. That is advisory accounting, not
billing truth; provenance and confidence must be preserved in every rollup.

#### Historical singleton hold sketch

The richer singleton below is preserved as design history only. The shipped
shape is the normative v2 per-agent record above; v1 singleton reads exist only
for upgrade recovery.

The active hold file is a single object. It is overwritten atomically when the active
hold changes and deleted or marked `state=cleared` when the cooldown is resolved.

```json
{
  "schema": "m8shift.usage.hold.v1",
  "state": "active",
  "created_at": "2026-07-03T09:00:00Z",
  "updated_at": "2026-07-03T09:00:00Z",
  "resume_after": "2026-07-03T11:16:00Z",
  "resume_for": "claude",
  "reason": "claude primary window at 91%; wait for reset",
  "decision": {
    "action": "cooldown_recommended",
    "relay_state": "AWAITING_CLAUDE",
    "apply": false,
    "exit_code": 11
  },
  "trigger": {
    "threshold": 0.9,
    "agent": "claude",
    "provider": "anthropic-claude",
    "adapter": "claude-code-statusline",
    "window": "primary",
    "used_ratio": 0.91,
    "used_tokens": 80080,
    "limit_tokens": 88000,
    "reset_at": "2026-07-03T11:15:00Z",
    "provenance": "official",
    "confidence": "high"
  },
  "recommended_wait_interval_seconds": 300,
  "notified_agents": ["claude", "codex"],
  "snapshot_ref": ".m8shift/runtime/usage.jsonl#2026-07-03T09:00:00Z/claude/claude-code-statusline"
}
```

#### `usage-adapter-errors.jsonl`

Adapter failures are recorded separately so failed probes do not look like usage
snapshots:

```json
{"schema":"m8shift.runtime.event.v1","type":"usage.adapter_error","ts":"2026-07-03T09:00:00Z","agent":"codex","source":{"tool":"m8shift-runtime.py","version":"3.43.0"},"payload":{"adapter":"codex-cli-rpc","provider":"openai-codex","exit_code":30,"message":"adapter identity mismatch","stderr_ref":null}}
```

### Adapter I/O contract

Usage adapters reuse the RFC 034 hardened runner. The runtime companion must not add
a second subprocess path.

Adapter manifest records include:

```json
{
  "name": "claude-code-statusline",
  "agent": "claude",
  "provider": "anthropic-claude",
  "kind": "subprocess_json",
  "argv": ["claude", "statusline", "--json"],
  "resolved_path": "/usr/local/bin/claude",
  "sha256": "…",
  "timeout_seconds": 10,
  "max_stdout_bytes": 262144,
  "max_stderr_bytes": 16384,
  "env_allowlist": ["HOME", "PATH", "CLAUDE_CONFIG_DIR", "CODEX_HOME"],
  "failure_policy": "warn_open",
  "provenance_preference": ["official", "local_estimate"]
}
```

Runner rules:

- resolve `argv[0]` to a realpath and compare SHA-256 before every run;
- pass an argv array, never a shell string;
- send no stdin unless a specific adapter kind requires JSON-RPC messages;
- cap stdout/stderr before storing or parsing;
- parse stdout as JSON for `subprocess_json`;
- treat stderr as diagnostics only;
- map adapter-specific exit codes to normalized `status`;
- fail closed for adapter identity mismatch, malformed manifest, timeout, or output
  over cap, but apply `failure_policy` when deciding whether to pause.

Adapter output is normalized to `m8shift.usage.snapshot.v1`. Raw provider output may
be kept only as a bounded local reference under `.m8shift/runtime/usage-raw/`; it is
never copied into `M8SHIFT.md`.

### Phase-2 readers

#### Claude Code reader

Preferred Phase-2 source is the official Claude Code statusline `rate_limits` payload
when available, read through a pinned local command or an adapter-provided state
file. The normalizer maps:

| Source field | Snapshot field |
|--------------|----------------|
| provider/account identity | `provider`, `adapter_account` if present |
| primary / five-hour window used or remaining ratio | `windows[].id="primary"` |
| weekly window used or remaining ratio | `windows[].id="weekly"` |
| reset timestamp | `windows[].reset_at` |
| official statusline provenance | `provenance="official"`, `confidence="high"` |

If only `claude-monitor` estimates are available, use `provenance="local_estimate"`
and `confidence="medium"` or `"low"` depending on freshness. Official fresh
`rate_limits` always wins over estimates.

#### Codex reader

Phase 2 may ship a conservative reader with two modes:

1. **Historical/accounting mode** from local Codex session logs or `codex-stats`
   exports. This produces `historical_estimate` snapshots for per-agent token and
   cost reports but does not gate usage cooldowns unless an operator explicitly opts
   into `fail_closed` or threshold use.
2. **Live gating mode** through the Codex CLI local app-server RPC
   (`initialize`, `account/rateLimits/read`) when that surface is
   available and identity-pinned. This may produce `official` or `local_estimate`
   windows suitable for `guard`.

Phase 4 Slice 3 ships a disabled reference adapter for the verified
`codex app-server --stdio` shape. Codex historical snapshots remain useful for
the operator's token-consumption study but should not overclaim live rate-limit
truth.

### Resolved open questions for Phase 2/3

| Question | Recommendation |
|----------|----------------|
| `cooldown` vs extending `pause` | Keep `cooldown` in core. It already shipped and expresses IDLE/AWAITING usage cooldown without weakening holder-only `pause`. |
| `m8shift-runtime.py` vs `m8shift-usage.py` | Implement Phase 2/3 inside `m8shift-runtime.py usage`. Split later only if the file becomes unmaintainable. |
| Committed policy or host-local | Host-local by default under `.m8shift/runtime/usage-policy.json`; allow checked-in examples under docs, not active policy. |
| Unknown usage fail-open or fail-closed | Default `warn_open`; allow explicit per-adapter/per-agent `fail_closed` only with operator policy. |
| Core `wait --quiet` | Keep quiet cooldown waits in runtime first (`usage wait`). Extend core `wait` only after runtime proves the need. |
| Per-agent token tracking | Use `usage.jsonl` snapshots as an advisory per-agent timeline; never label estimates as provider billing truth. |

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
usage init [--policy PATH] [--json]
usage adapters list [--agent AGENT] [--json]
usage adapters check [--agent AGENT] [--json]
usage snapshot [--agent AGENT] [--adapter NAME] [--write] [--json]
usage status [--json]
```

No core state changes yet. Implement the exact exit-code, sidecar, adapter-runner,
Claude reader, and Codex historical/live-reader contracts above.

### Phase 3 — guard and advisory notifications

Add:

```bash
usage guard [--agent AGENT] [--apply] [--json]
usage watch [--agent AGENT] [--apply] [--interval SECONDS] [--once] [--json]
usage wait AGENT [--interval auto|SECONDS] [--max-block SECONDS] [--quiet]
```

`--apply` writes only the guarded agent's runtime hold plus its audit event. It
does not call `cooldown`, mutate LOCK, queue an operator message, or reroute an
awaited target. The target's existing `WORKING_*` window remains valid until it
checkpoints/appends; admission is blocked at the next claim/listener boundary.

### Phase 4 — core cooldown command

Status: shipped in core. The command is dependency-free and records only passive
session events; provider adapters and automatic resume remain runtime companion work.

Add:

```bash
m8shift.py cooldown --until ISO --reason TEXT [--for agent] [--source SOURCE] [--wait-interval N] [--replace]
```

Acceptance requirement: remove `.m8shift/runtime/` and M8Shift still works.

### Phase 5 — automatic resume

Add:

```bash
m8shift-runtime.py usage resume --apply
m8shift-runtime.py usage wait <agent>
```

### Phase 6 — native Codex adapter

Status: implemented as a disabled reference adapter in Phase 4 Slice 3.

Verified direct Codex CLI RPC adapter:

```text
codex app-server --stdio
initialize
account/rateLimits/read
```

Mapping:

- read `result.rateLimitsByLimitId.codex` when present, else `result.rateLimits`;
- map `primary.windowDurationMins=300` to `session_5h`;
- map `secondary.windowDurationMins=10080` to `weekly`;
- map provider `usedPercent` to M8Shift `used_ratio` (`usedPercent / 100`);
- convert Unix-second `resetsAt` to UTC ISO;
- skip unknown durations or malformed windows;
- fail open to an empty official fixture on every app-server/auth/schema error.

This avoids requiring CodexBar for live gating while preserving CodexBar as the
original implementation reference.

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
- Tests cover threshold crossing, exact binding-window resets, unknown snapshots,
  target/peer working isolation, IDLE/AWAITING admission gates, explicit target
  clear, legacy global-cooldown recovery, and malformed adapter/target-hold data.
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
usage guard above threshold writes usage-holds/<agent>.json
weekly/ratio-native decision_window selects that exact reset
usage guard above threshold from AWAITING leaves LOCK unchanged
usage guard above threshold from WORKING_target posts an advisory target hold
usage guard above threshold from WORKING_peer records the target hold; peer continues
target hold blocks target claim/next/listener while peer admission is unaffected
two target holds coexist and clear independently
AWAITING_held_target never implicitly reroutes (RFC 066 dependency)
usage guard below threshold does nothing
usage resume refuses until a fresh target verdict is ok
usage resume clears only the recovered target hold
legacy singleton + global cooldown resumes through the compatibility path
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

## Phase 3 — real provider adapters (implementation scope)

PR A and PR B (both shipped in `v3.48.0`) delivered the whole **framework**: the
`usage snapshot/status/guard/watch/wait/resume` surface, the core `cooldown`
transition, the `m8shift.usage.snapshot.v1` / `m8shift.usage.fixture.v1`
schemas, the adapter manifest, the sidecar ledger, the exit-code contract, and
fail-open unknown handling. What still ships as a **fixture/stub** is the data
itself: the bundled `claude-usage-cli` adapter is disabled and the Codex adapter
is a fixture path. **Phase 3 is the real, opt-in adapters that emit
`m8shift.usage.fixture.v1` from live local sources** — nothing in the core or
the command surface changes.

### The load-bearing distinction: spent vs quota

Two adapter classes normalize to the same schema but behave differently at the
gate:

- **Quota adapters** yield a real `decision_ratio` per window — either from
  absolute `used` + `limit` tokens, or, for sources that report a percent/ratio
  rather than tokens, from a `used_ratio` (see the ratio-native schema extension
  below). They are **gating-capable**: `guard`/`cooldown` can act on them.
  Sources: the Claude usage endpoint (ratio-native), a `claude-monitor` rollup,
  the Codex `account/rateLimits/read` RPC.
- **Consumption (spent) adapters** return `used` only, with `limit_tokens: null`
  and each `windows[].limit: null`. By construction `decision_ratio` is `null`,
  the status is `unknown`, and the fail-open rule means **a spent-only source
  never pauses anything**. It is a reporting/timeline source, not a gate.
  Sources: a local JSONL scan, `ccusage`, `codex-stats`, a `token-meter` export.

This is the honest core of Phase 3: **you cannot gate on consumption alone.**
Gating requires either a source that returns the limit, or an operator-declared
budget (below) that supplies one. Presenting a spent-only estimate as if it were
a remaining-quota gate would violate design principle 3 (provenance is
mandatory) and rule 9 (official data wins over estimates).

### Phase-1 real adapters (grounded in on-disk shapes)

- **`claude-jsonl-scan`** (spent; reporting). **Shipped in Slice 2 as the built-in
  `jsonl_scan` adapter kind** (`provider: "claude"`). Scans the operator-configured
  `scan_roots` (e.g. `~/.claude/projects`, verified against real transcripts
  2026-07-05) and sums each assistant row's `message.usage.{input_tokens,
  output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` into two
  rolling windows keyed by the row `timestamp`: `session_5h` (last 5h) and `weekly`
  (last 7d). `used_tokens` is the widest (weekly) sum. **Aggregate integers only:**
  the parser reads *only* those four token integers and the row timestamp — never
  `message.content`, `message.model`, or `sessionId` — which structurally
  guarantees no prompt/response text can reach the snapshot (privacy rule 14).
  Emits a fixture with `used_tokens` set, each window's `limit`/top-level
  `limit_tokens: null`, `provenance: local_estimate` — so `decision_ratio` is
  `null`, status is `unknown`, and it **never gates** (fail-open; consumption alone
  cannot gate). **Opt-in / default-off** (rule 13): ships disabled with no implicit
  root. Bounded (`USAGE_SCAN_MAX_FILES` = 2000 files opened, `USAGE_SCAN_MAX_CANDIDATES`
  = 50000 files enumerated before any `lstat`, `USAGE_SCAN_MAX_FILE_BYTES` =
  64 MiB/file, `USAGE_SCAN_HORIZON_DAYS` = 8-day mtime cutoff so stale files are
  never opened, and a wall-clock deadline from the adapter's `timeout_s` — each of
  the last four stops with a lower-bound `usage.scan` warning) and version-tolerant:
  unknown fields ignored, unparseable lines
  skipped and counted, an abnormal skip ratio (>50% of a usage-bearing file)
  raising a `usage.scan` schema-drift finding (vendor JSONL is undocumented
  internals and will drift). Pure filesystem read: no network, no subprocess,
  never follows symlinks, never writes.
- **`claude-quota-keychain`** (implemented; disabled by default; **ratio-native**).
  A disabled argv-only reference script reuses the Claude Code OAuth access token
  from the macOS Keychain service `Claude Code-credentials` to call the client's
  own usage endpoint (`GET https://api.anthropic.com/api/oauth/usage`). The
  live-verified response exposes top-level `five_hour` / `seven_day` objects with
  **`utilization` as used percent** and an offset-bearing `resets_at`; the adapter
  maps these without inversion to `windows[].used_ratio` and normalizes aware
  reset timestamps to strict UTC `Z` (a timezone-naive reset degrades to `null`).
  For compatibility it also accepts the earlier normalized `windows[]` form with
  `remainingPercent` / `resetsAt`, where `used_ratio = 1 - remainingPercent/100`.
  Both paths leave `used`/`limit` **`null`** — token counts are genuinely unknown,
  and a percent must never be written into a token-named field (see "Schema
  extension for ratio-native quota" below). `provenance: official`.
  **M8Shift never opens the socket** — the operator's script performs the
  request; M8Shift runs the argv through the RFC 034 hardened runner and ingests
  stdout, exactly like every other adapter. A worked reference lives at
  `examples/usage-adapters/claude-oauth-usage.py` (fail-open: any error prints an
  empty official fixture → `unknown`, never a pause), and `usage init` scaffolds a
  **disabled** `claude-quota-keychain` adapter pointing at it. The example is
  reference material, deliberately not in `checksums.sha256`; review before
  enabling.
  Equivalent turnkey source: `claude-monitor --once --output json` (already
  catalogued above), preferred when the operator does not want to maintain a
  script — and when it exposes absolute `rate_limits` tokens, the token fields may
  be filled instead.
- **`codex-ratelimits`** (implemented; disabled by default; gating-capable). The
  live-verified local Codex app-server sequence (`initialize`, then
  `account/rateLimits/read`) maps `primary_window` / `secondary_window` and reset
  timestamps to `windows[]`, `provenance: official`. The reference adapter keeps
  stdin open while a daemon reader thread waits under a monotonic deadline, then
  fails open to an empty official fixture on any CLI/auth/schema/timeout error.
- **`codex-jsonl-scan`** (spent; reporting). The Claude scan's twin (same built-in
  `jsonl_scan` kind, `provider: "codex"`) over operator `scan_roots` such as
  `~/.codex/sessions` and `~/.codex/archived_sessions`. The Codex per-row shape is
  **not pinned here**, so its parser is **best-effort / version-tolerant**: it
  finds a usage-like object near the top of the row (bounded search depth), sums
  the recognized integer token fields — preferring an explicit `total_tokens` when
  present to avoid double-counting components — and reads only those integers plus
  a top-level timestamp. Same bounds, fail-open, and aggregate-only guarantees as
  the Claude scan; lines it cannot parse are skipped and counted.

### Two graft topologies (how independence is realized)

The measurement is an **independent module M8Shift grafts onto**, never code in
the core:

- **(A) Graft onto an external monitor.** `claude-monitor`, `ccusage`,
  `codex-stats`, a `token-meter` CSV/JSON export, or a `token-monitor` normalized
  feed run independently; a `cli_json` or `fixture` adapter reads their output.
  This is also the only charter-compatible way to get **continuous** monitoring:
  an external daemon polls, M8Shift reads its result on demand and stays passive.
- **(B) Minimal built-in scan adapter.** The `*-jsonl-scan` adapters above, for
  operators who run no external monitor. **On-demand only** — M8Shift never runs
  a loop.

The shipped adapter manifest (`name` / `agent` / `provider` / `kind` /
`command`) is the seam. Token-only adapters (`*-jsonl-scan`, absolute-token
quota sources) produce the **unchanged** shipped `m8shift.usage.fixture.v1`;
ratio-native official sources use one additive optional field (below) — this is
the one place Phase 3 touches the schema.

### Schema extension for ratio-native quota (additive)

The blocker this resolves: the Claude OAuth usage endpoint (and any provider
that reports a **percent/ratio** rather than absolute token counts) cannot be
mapped into the shipped fixture's integer `used`/`limit` token fields without
encoding a percent in a token-named field — a schema/provenance-honesty
violation. Fix: **one additive, optional per-window field**.

- Add `used_ratio` to a `windows[]` entry: a float in `[0, 1]`, the fraction of
  that window's limit already consumed. Present **only** for sources that report
  a ratio; `used` and `limit` for such a window stay `null` (tokens genuinely
  unknown).
- `decision_ratio` is redefined as the `max` over: (a) windows with `used` and a
  positive `limit` → `used/limit`; **(b) windows with `used_ratio` → `used_ratio`
  directly** (no token arithmetic); falling back to top-level
  `used_tokens/limit_tokens`, else `null`.
- Token-only snapshots are **byte-identical** to today — `used_ratio` is absent,
  nothing changes. Only ratio-native adapters emit it.
- **Honesty rule (hard):** a percent/ratio is **never** written into `used`,
  `limit`, `used_tokens`, or `limit_tokens`. Unit confusion is a schema error the
  normalizer must reject, not coerce.

This is an additive extension of `m8shift.usage.snapshot.v1` (and its fixture):
existing readers ignore an unknown optional field; the normalizer gains one
ratio path. The PR no longer claims *all* adapters emit the unchanged fixture —
only the token-only ones do.

### Operator-declared budget (optional bridge) — shipped Slice 4

To let a spent-only source gate, an operator may declare a
**`m8shift.usage.budget.v1`** file at `.m8shift/usage/budget.json` with per-agent
per-window caps:

```json
{
  "schema": "m8shift.usage.budget.v1",
  "budgets": [
    {"agent": "claude", "windows": {"session_5h": 100000, "weekly": 500000}}
  ]
}
```

When present, a declared cap supplies the **missing `limit`** for a window that
has `used` but no limit (typical of a `jsonl_scan`), so `decision_ratio` computes
and the source can gate. Guarantees:

- **Opt-in / absent by default.** `usage init` scaffolds an INACTIVE
  `budget.example.json`; only `budget.json` is loaded. Nothing changes until the
  operator creates it.
- **Estimate only, never official.** A budget cap is applied **only to
  non-official snapshots** and **never overrides** a limit already present
  (official data wins, rule 9). A budget-filled limit is `provenance:
  local_estimate` and emits a `usage.normalize` warning naming the budget.
- **Fail-safe.** A malformed or unreadable budget is ignored with a
  `usage.budget` warning — a bad budget never invents a limit. Only positive
  integer caps survive.

### Privacy and credential hardening (extends "Security and privacy")

Phase 3 adds, on top of the existing 12 rules:

13. **JSONL scan is opt-in and default-off.** A scan of `~/.claude/projects`
    reads metadata across **all** of an operator's projects, not just the
    relay's. Scan roots are operator-configurable; a disabled adapter never
    scans.
14. **Aggregate token counts only — never message content.** The scanner reads
    only the integer `usage` fields and the row `timestamp`; it never reads
    `model`, `sessionId`, or any prompt/response text, and the version-tolerant
    parser never descends into content-bearing keys (a usage-like object nested
    in message content must not contribute a content-derived number).
15. **Credential reuse stays in the operator's adapter, not in M8Shift.**
    M8Shift never reads OAuth material itself and never stores an OAuth or
    refresh token (reinforces rule 2). The shipped Claude reference adapter uses
    the macOS Keychain by default after opt-in, with no plaintext-file default;
    an explicit credential file remains only an operator/test override. If
    account identity ever surfaces, it is hashed (`sha256:…`) and raw tokens /
    response bodies are never logged (pattern borrowed from `token-monitor`).

### Provenance binding

Each Phase-1 adapter declares `official` (endpoint / RPC / fresh statusline
`rate_limits`) or `local_estimate` (scan / budget / stale data). Official wins
(rule 9); a gating pause on an estimate carries `confidence=local_estimate`
(design principle 3, and the `claude-monitor` implementation note above).

### Acceptance criteria (Phase 3)

- Each real adapter emits a valid `m8shift.usage.fixture.v1` that normalizes to
  `m8shift.usage.snapshot.v1` and round-trips the append-only ledger.
- A spent-only adapter yields `decision_ratio: null` → status `unknown` → never
  pauses (fail-open regression test).
- A token-only quota adapter (absolute `used`/`limit`) with fresh official data
  yields a positive `decision_ratio` and drives `cooldown` at the threshold.
- A **ratio-native** quota adapter emitting `used_ratio` (e.g. `0.58`) yields
  `decision_ratio = 0.58` from the ratio directly and drives `cooldown` at the
  threshold, with `used`/`limit` recorded as `null` for that window.
- **Never percent-as-tokens** (regression): the normalizer rejects, and never
  coerces, a window that carries both `used_ratio` and a non-null `used`/`limit`;
  no adapter ever writes a percent into a token-named field.
- Token-only snapshots remain **byte-identical** to the shipped v1 output when no
  adapter emits `used_ratio`.
- The JSONL scan is bounded and fail-open on malformed input: unknown fields
  ignored, unparseable lines skipped and counted, abnormal skip ratio → `info`
  finding (negative tests required).
- Opt-in default-off proven: a disabled adapter performs no scan; a privacy test
  asserts the scanner reads only integer usage fields, never message content.
- No socket is opened by M8Shift itself — the operator's OAuth script is the only
  network actor (adapter argv-only, RFC 034 runner).
- `official` vs `local_estimate` provenance is recorded on every snapshot; a
  pause on an estimate carries `confidence=local_estimate`.

### Non-goals (Phase 3)

- No bundled vendor scraper maintained inside M8Shift — adapters stay thin and
  operator-authorized; prefer grafting onto `claude-monitor` / `ccusage` over
  reimplementing them.
- No credential storage, no `.credentials.json` reads by the core or companions.
- No continuous daemon in M8Shift — continuous monitoring is topology (A), an
  external producer M8Shift reads on demand.
- No auto-resume and no automatic provider launch (unchanged from PR B).

---

## Phase 4 — first-class Claude + Codex usage adapters (#100, implemented)

Status: **implemented and live-verified**. This is an amendment to RFC 040, not a new RFC:
the normalized snapshot schema, runtime sidecars, adapter manifest, hardened
runner, and cooldown semantics already exist here. Phase 4 changes the shipped
adapter catalog and credential policy; it does **not** add provider/network
behavior to core `m8shift.py`.

### Goal

Most operators run at least Claude and Codex in the same shift. Usage monitoring
therefore needs usable, reusable adapters for both agents out of the box:

- `m8shift-runtime.py usage init` scaffolds disabled entries for Claude **and**
  Codex by default;
- `examples/usage-adapters/` ships reference adapters for Claude's official
  OAuth/subscription quota endpoint and the verified local Codex app-server
  rate-limit RPC; both official adapters remain disabled until operator opt-in;
- local JSONL scans remain reporting/estimate sources, never authoritative
  quota gates unless paired with an explicit operator budget.

All scaffolds stay **disabled by default**. Enabling any provider adapter is an
explicit operator action.

### Amendment vs. new RFC decision

This belongs in RFC 040 Phase 4 because it does not change the relay model. It
only fills the provider-specific adapter seam that Phase 2/3 deliberately left
as disabled scaffolds and examples. A separate RFC would be warranted only if we
added a credential manager, a hosted control plane, a daemon owned by M8Shift, or
core relay mutations beyond the existing `cooldown`/runtime contract.

### Phase 4 adapter catalog

`usage init` should scaffold these disabled entries:

```json
{
  "schema": "m8shift.usage.adapters.v1",
  "adapters": [
    {
      "name": "claude-jsonl-scan",
      "agent": "claude",
      "provider": "anthropic-claude",
      "kind": "jsonl_scan",
      "enabled": false,
      "scan_roots": ["~/.claude/projects"],
      "timeout_s": 10,
      "provenance": "local_estimate",
      "role": "reporting"
    },
    {
      "name": "claude-quota-keychain",
      "agent": "claude",
      "provider": "anthropic-claude",
      "kind": "cli_json",
      "enabled": false,
      "command": ["python3", "examples/usage-adapters/claude-oauth-usage.py"],
      "timeout_s": 10,
      "failure_policy": "warn_open",
      "provenance_preference": ["official"]
    },
    {
      "name": "codex-jsonl-scan",
      "agent": "codex",
      "provider": "openai-codex",
      "kind": "jsonl_scan",
      "enabled": false,
      "scan_roots": ["~/.codex/sessions", "~/.codex/archived_sessions"],
      "timeout_s": 10,
      "provenance": "local_estimate",
      "role": "reporting"
    },
    {
      "name": "codex-ratelimits",
      "agent": "codex",
      "provider": "openai-codex",
      "kind": "cli_json",
      "enabled": false,
      "//": "Disabled by default: verified local Codex app-server rate-limit adapter; enable only after operator review",
      "command": ["python3", "examples/usage-adapters/codex-ratelimits.py"],
      "timeout_s": 15,
      "failure_policy": "warn_open",
      "provenance_preference": ["official"]
    }
  ]
}
```

The exact manifest may include additional fields already supported by the
runtime companion, but these entries define the expected default catalog:
disabled, explicit, provider-neutral, and fail-open.

### Claude quota adapter — macOS Keychain, not plaintext credentials

The Phase 3 text assumed a plaintext credentials file. On macOS, Claude Code's
OAuth material is held in the user's Keychain under a service entry managed by
Claude Code. Phase 4 updates the adapter contract:

- The example adapter reads the access token from the macOS Keychain **only when
  the operator enables the adapter**.
- The current macOS lookup is the login Keychain generic-password item whose
  service is `Claude Code-credentials`; the adapter may invoke
  `/usr/bin/security find-generic-password -s "Claude Code-credentials" -w` and
  parse the returned JSON in memory.
- The access token lives at `claudeAiOauth.accessToken`; expiry lives at
  `claudeAiOauth.expiresAt` (epoch milliseconds). Other fields such as refresh
  token, subscription type, and rate-limit tier may be present but must not be
  emitted.
- The Keychain read is in-memory only. The adapter never writes the access token,
  refresh token, raw credential JSON, account identity, or endpoint response body
  to disk, stdout, stderr, M8Shift ledgers, or relay turns.
- The adapter uses the access token only for the provider usage request, then
  discards it.
- The adapter does not refresh tokens. If the access token is missing or expired,
  it emits an empty official fixture so the runtime records `unknown` and
  remains fail-open.
- Keychain ACLs may prompt the operator or deny access because the adapter is a
  separate subprocess from the app that created the item. Prompt timeout, denial,
  or non-interactive failure is treated exactly like a missing token: empty
  official fixture, `unknown`, no pause.
- Official Claude quota applies only to OAuth/subscription Claude Code sessions
  with a usable Keychain token. API-key-only users should expect this adapter to
  fail open unless a separate explicit adapter is provided.
- Non-macOS systems may use an explicit operator-provided credential file-path
  override (or a custom downstream adapter command), but there is no plaintext
  credential-file default.

The reference script implements both the live top-level used-percent shape and
the earlier normalized remaining-percent compatibility shape described above.
Both map to `windows[].used_ratio` and leave token-named fields `null`: a percent
is never written into `used`, `limit`, `used_tokens`, or `limit_tokens`.

### Codex usage adapters — local scan plus live-verified official rate limits

Phase 4 originally staged `codex-ratelimits` as a disabled TODO until the local
RPC shape could be confirmed. That gate is now satisfied: the shipped
`examples/usage-adapters/codex-ratelimits.py` was verified against the local
Codex app-server protocol and remains disabled by default until operator review.
It:

1. launches the local Codex CLI in its read-only app-server/RPC mode using an
   argv array, never a shell string;
2. performs the minimal account/rate-limit read sequence;
3. maps primary/secondary reset windows to `m8shift.usage.fixture.v1`;
4. emits `provenance: official` only when the source is the provider/Codex
   account rate-limit surface;
5. emits an empty official fixture on any unsupported CLI, malformed response,
   timeout, or missing account state.

Local Codex transcript/log scans remain a separate supported source:
`local_estimate` consumption, useful for reporting and budget-backed estimates,
but not an official quota gate by itself. The rate-limit adapter is the official
ratio source; neither adapter is enabled automatically.

### Credential and subprocess policy

Phase 4 reuses the existing hardened adapter runner contract:

- argv arrays only; no shell strings;
- bounded timeout;
- stdout size cap;
- stderr diagnostic-only, never credential-bearing;
- fail-open to `unknown` on adapter failure;
- no raw provider tokens, raw credential JSON, or raw provider responses in
  output, ledgers, exceptions, reports, or relay turns;
- provider/network behavior stays in `m8shift-runtime.py` adapters and example
  scripts, never in core `m8shift.py`;
- disabled adapters perform no Keychain, filesystem-log, CLI, or network access.

If an adapter wants to expose an account identifier, it must expose only a stable
hash or redact it entirely. The default examples should omit identity.

### Compartmentalization policy

RFC 052 applies to this phase:

- examples and tests use synthetic fixtures only;
- no real token, real account id, real project name, real local path, or real
  provider response capture appears in docs, tests, commits, issues, or relay
  turns;
- docs may name generic locations such as `~/.codex/...` or `~/.claude/...`, but
  must not include an operator-specific absolute path;
- adapter examples must fabricate provider payloads for tests instead of pasting
  real captures.

### Implementation slices

Implemented Phase 4 delivery order:

1. **Docs + scaffolds** — `usage init` scaffolds both Claude and Codex disabled
   entries by default; the docs state that all adapters are off until the
   operator enables them. Each entry includes placeholder config fields (`scan_roots`,
   `command`, `timeout_s`) so enabling is one deliberate edit, not a research task.
2. **Claude Keychain example** —
   `examples/usage-adapters/claude-oauth-usage.py` uses macOS Keychain as the
   default credential source, with fail-open behavior and no plaintext credential
   default.
3. **Codex rate-limit adapter** — keep the `codex-ratelimits` manifest entry
   disabled by default and ship `examples/usage-adapters/codex-ratelimits.py`
   after live verification of the local app-server RPC. `codex-jsonl-scan`
   remains the reporting/local-estimate source unless the operator supplies a
   budget; `codex-ratelimits` supplies the opt-in official ratio source.
4. **Validation tests** — tests prove disabled adapters do not execute, enabled
   adapters normalize fixtures correctly, credential material is not printed, and
   unsupported provider state yields `unknown` rather than a pause.

### Slice 4 — validation and contract tests (implemented)

Slice 4 is a test-hardening slice. It should not add a new provider integration
and should not enable any adapter by default. Its value is to pin the Phase 4
contract so later provider work cannot quietly weaken privacy, fail-open, or
disabled-by-default behavior.

Pinned test surface:

1. **Default adapter manifest contract**
   - Fresh `usage init` creates exactly the four Phase-4 default adapters:
     `claude-jsonl-scan`, `claude-quota-keychain`, `codex-jsonl-scan`, and
     `codex-ratelimits`.
   - All four ship `enabled:false`, bounded `timeout_s`, argv arrays for
     `cli_json`, and explicit placeholder fields (`scan_roots` or `command`).
   - `usage adapters check` is clean for the scaffold: no unsupported-key
     warnings, no stale fixture references, no operator-specific paths.
   - Re-running `usage init` is no-clobber and preserves operator edits.

2. **Disabled means inert**
   - A clean scaffold followed by `usage snapshot` yields no snapshots and writes
     no usage ledger lines.
   - Tests must prove disabled defaults do not perform filesystem scans, Keychain
     reads, Codex CLI launches, subprocess adapter calls, or network access. Use
     synthetic monkeypatches/stubs only; never touch a real Keychain or provider.
   - The disabled `codex-ratelimits` entry remains inert until operator opt-in;
     initialization never launches an RPC probe.

3. **Fixture schema conformance**
   - Every enabled synthetic adapter used in tests emits or normalizes to
     `m8shift.usage.fixture.v1`.
   - Ratio-native fixtures use `windows[].used_ratio` and keep `used`,
     `limit`, `used_tokens`, and `limit_tokens` null/absent as appropriate.
   - `used_ratio` is always in `[0, 1]`: remaining percent below `0` clamps to a
     fully-used ratio (`1.0`), above `100` clamps to `0.0`, and NaN/Infinity
     windows are skipped rather than emitted.
   - Percent values are never encoded in token-named fields; unit-mixed windows
     are rejected or skipped, never coerced.
   - Malformed windows are isolated per entry: one bad window cannot discard
     already-valid windows.
   - Arbitrary-precision numeric values that can overflow float conversion are
     explicit malformed cases: huge `resetsAt` values skip only that window and
     huge `expiresAt` values fail open to no token.

4. **Claude Keychain example contract**
   - The example reads the macOS Keychain via the exact argv
     `security find-generic-password -s "Claude Code-credentials" -w`, with a
     bounded timeout and no shell.
   - Missing, expired, malformed, denied, timed out, non-JSON, bad HTTP, broken
     stdout, and generic provider failures all fail open to an empty official
     fixture and return `0` where `main()` owns the boundary.
   - The fail-open boundary must catch any `Exception` subtype, not an enumerated
     list of known provider or HTTP errors. Tests should inject a custom
     `Exception` subclass to guard against accidental re-narrowing.
   - No access token, refresh token, raw credential JSON, account identity, or raw
     provider response body appears in stdout, stderr, fixture JSON, ledgers, or
     relay text. Tests should include secrets in failing inputs to prove absence.
   - At least one enabled end-to-end snapshot must include a secret-bearing
     synthetic provider payload and then assert the secret is absent from the
     normalized snapshot, stdout/stderr, and the append-only usage ledger. Disabled
     adapters producing no ledger lines are a separate invariant, not a leak proof.
   - Non-macOS has no plaintext credential-file default; any file path is an
     explicit operator/test override.

5. **Adapter identity and runner contract**
   - `cli_json` adapters require argv arrays, not shell strings.
   - Optional `sha256` identity pins are checked for enabled command adapters and
     fail closed on mismatch.
   - Adapter stdout size, timeout, and stderr diagnostics remain bounded; failure
     records are diagnostic-only and credential-free.

6. **No-network test harness**
   - Slice 4 tests must run offline and deterministically.
   - Provider responses, credential blobs, and JSONL logs are fabricated fixtures.
   - Any test that exercises network-capable code must inject a fake fetcher or
     fake subprocess runner; it must not call the real provider endpoint.
   - Tests use fixed clocks for `captured_at` / reset assertions; no wall-clock
     or `Date` value is part of the oracle.
   - Fabricated fixtures use synthetic placeholders only and must pass
     `doctor --hygiene-only --lint` before merge because these files land in the
     public repository.

Coverage note for `codex-jsonl-scan`:

- The active Codex source is already pinned by Phase-3 tests rather than
  duplicated in Slice 4: version-tolerant Codex token extraction, content-nested
  `usage` ignored, raw prompt content absent from stdout and ledger, stale-mtime
  skip, disabled scan inertness, candidate-enumeration cap, and wall-clock
  deadline cap. Slice 4 should cite and keep those tests green; add only missing
  assertions if a future review identifies a gap.

### Acceptance criteria (Phase 4)

- `usage init` creates disabled Claude and Codex adapter entries by default.
- A clean scaffold performs no Keychain read, Codex CLI launch, filesystem scan,
  or network call until an adapter is enabled.
- The Claude example reads OAuth material from macOS Keychain only after opt-in,
  keeps tokens in memory only, emits no identity/token/raw response, and
  fail-opens to an empty official fixture on any error, including Keychain ACL
  prompt timeout/denial and API-key/no-OAuth setups.
- The Codex `jsonl_scan` scaffold is the first real Codex source and remains
  reporting/local-estimate by default.
- The Codex official rate-limit adapter is clearly marked disabled by default;
  its verified RPC mapping may gate only after explicit operator opt-in.
- Both examples use `used_ratio` for ratio-native quota and never encode a
  percent as token counts.
- Local JSONL scans for Claude/Codex remain `local_estimate` and never gate
  unless an explicit operator budget supplies limits.
- Tests use synthetic fixtures and placeholder paths only.
- Core `m8shift.py` has no new network, Keychain, OAuth, or provider-specific
  behavior.

### Non-goals (Phase 4)

- No automatic enabling of Claude or Codex quota adapters.
- No storage of OAuth access tokens, refresh tokens, account ids, or raw provider
  responses by M8Shift.
- No browser-cookie scraping.
- No provider SDK dependency in core.
- No claim that local transcript scans are official quota truth.
- No hosted usage dashboard or account manager.

---

## References

- Claude Code Usage Monitor / `claude-monitor`: https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor
- PyPI `claude-monitor`: https://pypi.org/project/claude-monitor/
- CodexBar: https://github.com/steipete/codexbar
- CodexBar Codex provider notes: https://github.com/steipete/codexbar/blob/main/docs/codex.md
- `codex-stats`: https://pypi.org/project/codex-stats/
- `ccusage`: https://github.com/ccusage/ccusage
- LiteLLM budgets/rate limits: https://docs.litellm.ai/docs/proxy/users
- `token-meter` (local JSONL consumption + CSV/JSON export; README-stated MIT core): https://github.com/whdrnr2583-cmd/token-meter
- `token-monitor` (OAuth usage-endpoint remaining-quota detection + privacy patterns): https://github.com/Javis603/token-monitor
