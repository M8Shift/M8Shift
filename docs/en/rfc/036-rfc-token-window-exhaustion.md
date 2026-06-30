# RFC 036 — Token-window exhaustion detection and graceful pause

- **Status:** proposed
- **Date:** 2026-06-30
- **Scope:** define how M8Shift companions should detect likely context-window exhaustion
  and force an explicit checkpoint / pause instead of letting agents silently degrade.
- **Builds on:** [021-rfc-pause-resume.md](021-rfc-pause-resume.md),
  [022-rfc-session-reports.md](022-rfc-session-reports.md),
  [031-rfc-decision-traceability.md](031-rfc-decision-traceability.md),
  [033-rfc-context-economy.md](033-rfc-context-economy.md),
  [034-rfc-companion-adapter-interface.md](034-rfc-companion-adapter-interface.md),
  [035-rfc-interactive-listener-gap.md](035-rfc-interactive-listener-gap.md).

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

```bash
python3 m8shift-runtime.py headroom codex --json
python3 m8shift-runtime.py headroom codex --pause-on high --reason "context window risk"
```

or, if implemented in the context companion:

```bash
python3 m8shift-context.py headroom --agent codex --json
```

The command should not mutate the relay unless `--pause-on` is explicit and the
caller is authorized to pause the current holder under RFC 021 semantics.

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

## 10. Acceptance criteria

This RFC is implemented when:

- a companion command computes Tier-0 proxy headroom signals;
- runtime status can display `ok` / `warning` / `high` headroom;
- doctor can report missing checkpoints on long sessions;
- an explicit `--pause-on high` path can call the existing `pause` command, with
  reason text and audit trail;
- no provider API is required;
- optional provider-specific counters are clearly marked optional;
- tests cover proxy thresholds, checkpoint detection, and explicit pause gating.

## 11. Non-goals

- No exact token accounting in the core.
- No automatic pause without explicit policy.
- No model-provider dependency.
- No hidden context summarization.
- No replacement for human scope decisions.
