# RFC 036 — Token-window exhaustion detection and graceful pause

- **Status:** accepted / implemented in `m8shift-runtime.py`
- **Date:** 2026-06-30
- **Scope:** define how M8Shift companions should detect likely context-window exhaustion
  and force an explicit checkpoint / pause instead of letting agents silently degrade.
- **Builds on:** [021-rfc-pause-resume.md](021-rfc-pause-resume.md),
  [022-rfc-session-reports.md](022-rfc-session-reports.md),
  [031-rfc-decision-traceability.md](031-rfc-decision-traceability.md),
  [033-rfc-context-economy.md](033-rfc-context-economy.md),
  [034-rfc-companion-adapter-interface.md](034-rfc-companion-adapter-interface.md),
  [035-rfc-interactive-listener-gap.md](035-rfc-interactive-listener-gap.md).

## 0. Implementation summary

Implemented in the optional runtime companion, not in the passive core:

- `python3 m8shift-runtime.py headroom [agent]` computes Tier-0 proxy signals:
  turns since the latest recorded headroom checkpoint, relay bytes, runtime ledger
  bytes, and handoff body bytes.
- Harnesses may pass an exact local signal with `--window-status ok|warning|high`
  and `--window-reason`.
- `--checkpoint` writes a derived `session report current` checkpoint under
  `.m8shift/runs/` and records a `headroom.checkpoint` runtime event.
- `--pause-on warning|high --reason TEXT` is the only mutating pause path: it
  checkpoints first, then calls the core `pause` command, and only succeeds when
  the named agent is the current holder.
- `status-runtime` includes the current headroom payload and `doctor` reports
  `runtime.headroom` when checkpointing is overdue.

### 0.1 Positioning

This RFC is about **local context-window pressure**, not provider/account usage.
It answers: "is this relay/session becoming too large for the next agent turn to
remain reliable?"

It deliberately stays separate from adjacent token-economy work:

| Concern | RFC | Signal | Remedy |
|---|---|---|---|
| Static protocol footprint | [RFC 023](023-rfc-agent-token-footprint.md) | generated protocol size | split core/reference docs |
| Context economy policy | [RFC 033](033-rfc-context-economy.md) | unnecessary context in handoffs | exchange contracts, not raw bulk |
| Local context-window pressure | **RFC 036** | turns/bytes/harness window status | checkpoint, then optional pause |
| Context compression backends | [RFC 037](037-rfc-agent-context-compression-backends.md) | large context block before insertion | digest/reference/compress locally |
| Rolling provider usage limit | [RFC 040](040-rfc-ai-session-usage-monitoring.md) | 5-hour/weekly/account usage ratio | cooldown until provider reset |

The word "headroom" here names the runtime guard. It is not the same thing as
the optional `headroom_ext` compression backend in RFC 037, though both protect
the same broad outcome: keep agents from wasting context.

## 1. Problem

Long shifts can fail before the lock fails. The agent may still hold the pen, but
its context window is overloaded, the UI becomes sluggish, or the model starts
losing earlier constraints.

M8Shift cannot read a proprietary model context window directly. It can, however,
observe proxy signals:

- growing turn count;
- growing handoff body size;
- repeated status / wait churn;
- repeated "I forgot / restart / reprise" incidents;
- large logs or packs pasted into handoffs;
- long-running `WORKING_*` states with no compact checkpoint.

Without a protocol, agents keep working past the point where a pause/checkpoint
would be safer.

## 2. Core invariant

The core remains tokenizer-less and passive.

`m8shift.py` should not call provider token counters, model APIs, or external
compression tools. It may expose existing state. Detection and policy live in
companions / harnesses.

## 3. Decision

Add a companion-level "headroom guard" that uses tiered self-checks and proxy
thresholds. When risk is high, the recommended recovery is:

1. write a compact checkpoint / session report;
2. record open decisions and blockers;
3. pause the relay with `pause <agent> --reason "...context checkpoint..."`;
4. resume explicitly when the next scoped turn starts.

This reuses RFC 021 `PAUSED` instead of inventing a new terminal state.

## 4. Detection tiers

| Tier | Signal | Authority |
|---|---|---|
| 0 | advisory proxy count: turns, bytes, lines, pack size | runtime/context companion |
| 1 | local harness signal: UI slow, repeated retries, command output too large | operator/runtime |
| 2 | provider-specific token counter, if available | optional provider adapter |
| 3 | agent self-report: "I am losing context / need checkpoint" | agent, recorded as evidence |

Tier 0 must work without dependencies. Tiers 1–3 are optional and advisory.

## 5. Proposed command surface

The shipped command surface is:

```bash
python3 m8shift-runtime.py headroom codex --json
python3 m8shift-runtime.py headroom codex --checkpoint --json
python3 m8shift-runtime.py headroom codex --pause-on high --reason "context window risk"
```

Supported policy overrides:

```bash
python3 m8shift-runtime.py headroom codex \
  --warn-after-turns-since-checkpoint 8 \
  --warn-after-handoff-body-bytes 12000 \
  --warn-after-relay-bytes 250000 \
  --pause-recommendation-after-turns-since-checkpoint 15 \
  --pause-recommendation-after-relay-bytes 500000 \
  --json
```

Harnesses with better local knowledge may add an explicit window signal:

```bash
python3 m8shift-runtime.py headroom claude \
  --window-status high \
  --window-reason "Claude Code UI reports exhausted context" \
  --pause-on high \
  --reason "context checkpoint required"
```

The command should not mutate the relay unless `--pause-on` is explicit and the
caller is authorized to pause the current holder under RFC 021 semantics.

`m8shift-context.py` may reduce context before insertion under RFC 037. It should
not grow a second, competing headroom state machine.

### 5.1 JSON contract

`headroom --json` emits one object with these stable top-level fields:

```json
{
  "status": "ok|warning|high",
  "reasons": ["16 turns since checkpoint"],
  "next": "checkpoint + pause recommended before more implementation",
  "metrics": {
    "turn": 16,
    "turns_total": 16,
    "turns_since_checkpoint": 16,
    "relay_bytes": 12345,
    "runtime_ledger_bytes": 2345,
    "last_handoff_body_bytes": 321,
    "max_handoff_body_bytes": 12001
  },
  "thresholds": {
    "warn_after_turns_since_checkpoint": 8,
    "warn_after_handoff_body_bytes": 12000,
    "warn_after_relay_bytes": 250000,
    "pause_recommendation_after_turns_since_checkpoint": 15,
    "pause_recommendation_after_relay_bytes": 500000
  },
  "checkpoint": {
    "turn": 12,
    "ts": "2026-07-01T12:00:00Z",
    "path": ".m8shift/runs/headroom-...md"
  },
  "relay": {
    "state": "WORKING_CLAUDE",
    "holder": "claude",
    "session": "20260701T120000Z-example"
  },
  "agent": "claude",
  "runtime_findings": [],
  "runtime_version": "3.x"
}
```

When mutation flags are used, the same object may also include:

| Field | Meaning |
|---|---|
| `checkpoint_written` | relative checkpoint path, or empty string |
| `paused` | whether the runtime successfully called core `pause` |
| `pause_output` | stdout from the core pause command |
| `pause_skipped` | why `--pause-on` did not mutate because risk was below threshold |

## 6. Proxy thresholds

Initial advisory defaults:

```yaml
headroom:
  warn_after_turns_since_checkpoint: 8
  warn_after_handoff_body_bytes: 12000
  warn_after_relay_bytes: 250000
  warn_after_repeated_wait_ready_without_resume: 2
  pause_recommendation_after_turns_since_checkpoint: 15
  pause_recommendation_after_relay_bytes: 500000
```

These are not correctness rules. They are prompts to checkpoint.

Thresholds are disable-able per invocation by passing `0`. They must never be
serialized into `M8SHIFT.md`; local policy belongs to runtime arguments or local
sidecars.

## 7. Checkpoint content

A checkpoint should contain:

- current objective;
- active decisions;
- disagreements and resolution;
- files changed / commits pushed;
- tests and evidence;
- open risks;
- blocked items;
- next intended action;
- source references back to original relay/session reports.

It should avoid copying raw logs and full histories. Use RFC 034 context packs and
RFC 022 session reports by reference.

The shipped implementation writes the checkpoint through:

```bash
python3 m8shift.py session report current --write --output .m8shift/runs/headroom-...md
```

It then records one runtime event in `.m8shift/runtime/runs.jsonl`:

```json
{
  "event": "headroom.checkpoint",
  "run_id": "headroom-...",
  "agent": "claude",
  "session_id": "20260701T120000Z-example",
  "path": ".m8shift/runs/headroom-...md",
  "turn": 16,
  "reason": "context checkpoint required",
  "payload": {
    "headroom_status": "high",
    "metrics": {}
  }
}
```

That event is the reset point for `turns_since_checkpoint`. If the runtime ledger
is unreadable or malformed, `headroom` should still return a payload and include a
diagnostic under `runtime_findings`.

## 8. Graceful pause rule

When headroom risk is high and no immediate action is safe:

```bash
python3 m8shift.py pause <agent> \
  --reason "context window risk; checkpoint written; waiting for explicit resume"
```

`PAUSED` means:

- session remains open;
- holder is `none`;
- no agent should claim without explicit user scope;
- the next turn starts from a checkpoint, not from implicit memory.

The runtime may call `pause` only when all of the following are true:

- `--pause-on warning|high` was passed;
- `--reason` is non-empty;
- computed status is at or above the selected threshold;
- an `agent` argument was supplied;
- the supplied agent is the current holder;
- the relay is not already `PAUSED` or `DONE`.

If those checks fail, the runtime must refuse without changing `M8SHIFT.md`.

## 9. Status/runtime composition

Runtime status should surface:

```text
headroom: warning
reason: relay is 310 KB and 11 turns since checkpoint
next: write checkpoint, then pause if no immediate safe handoff exists
```

For high risk:

```text
headroom: high
next: checkpoint + pause recommended before more implementation
```

The JSON shape in `status-runtime --json` embeds the same `headroom` object and
adds the corresponding `runtime.headroom` finding to `runtime_findings` for
`warning` or `high`.

## 10. Operational playbooks

### 10.1 Normal warning

```text
headroom: warning
action: finish the current small edit if it is already in progress, then write a
checkpoint or hand off with a compact summary. Do not paste raw logs to "help"
the next agent.
```

### 10.2 High risk while holding the pen

```bash
python3 m8shift-runtime.py headroom claude \
  --pause-on high \
  --reason "context window risk; checkpoint written; waiting for explicit resume"
```

Expected result:

1. `.m8shift/runs/headroom-...md` is written;
2. `.m8shift/runtime/runs.jsonl` records `headroom.checkpoint`;
3. `m8shift.py pause claude --reason ...` parks the relay as `PAUSED`;
4. the next agent resumes only after explicit user scope.

### 10.3 High risk while not holding the pen

Do not force-pause another agent. Report the status, ask the holder to checkpoint,
or use the operator/interrupt mechanisms from the runtime companion. The holder
must be the one to park its own turn unless a separate recovery RFC applies.

### 10.4 Near provider limit

Do not use RFC 036 for account limits. Use RFC 040 usage monitoring/cooldown.
Context-window pressure and subscription-window pressure can happen together, but
they are different signals and should be reported separately.

## 11. Acceptance criteria

This RFC is implemented when:

- a companion command computes Tier-0 proxy headroom signals;
- runtime status can display `ok` / `warning` / `high` headroom;
- doctor can report missing checkpoints on long sessions;
- an explicit `--pause-on high` path can call the existing `pause` command, with
  reason text and audit trail;
- no provider API is required;
- optional provider-specific counters are clearly marked optional;
- tests cover proxy thresholds, checkpoint detection, and explicit pause gating.

Current regression coverage includes:

- high risk after many turns since checkpoint;
- `status-runtime --json` embedding headroom status;
- `doctor --json` surfacing `runtime.headroom`;
- `--checkpoint` writing a headroom session report and resetting turn distance;
- `--pause-on high` refusing a non-holder;
- `--pause-on high` checkpointing then pausing the current holder.

## 12. Non-goals

- No exact token accounting in the core.
- No automatic pause without explicit policy.
- No model-provider dependency.
- No hidden context summarization.
- No replacement for human scope decisions.
- No billing, cost, or weekly/quota accounting. That belongs to RFC 040 or to a
  provider/dashboard adapter.
