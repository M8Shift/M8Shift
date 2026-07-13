# RFC 054 — Pre-exhaustion checkpoint and session rotation

- **Status:** draft / design only
- **Date:** 2026-07-13
- **Scope:** extend the shipped RFC 036 headroom guard with a provider-aware,
  operator-confirmed session-rotation procedure before native compaction becomes impossible.
- **Builds on:** [RFC 021](021-rfc-pause-resume.md),
  [RFC 022](022-rfc-session-reports.md),
  [RFC 033](033-rfc-context-economy.md),
  [RFC 036](036-rfc-token-window-exhaustion.md),
  [RFC 037](037-rfc-agent-context-compression-backends.md), and
  [RFC 040](040-rfc-ai-session-usage-monitoring.md).

## 0. Proposal summary

Add an advisory pre-exhaustion policy to `m8shift-runtime.py headroom`:

1. ingest an exact provider/harness context signal when available;
2. warn before the model session reaches its context limit;
3. create a compact, source-referenced checkpoint at a high threshold;
4. recommend an explicit session rotation;
5. generate a bounded resume packet for a fresh session;
6. never close an interactive client or start a replacement session without operator action.

This RFC does not add a compressor. It makes the existing checkpoint and pause
primitives preventive rather than waiting for a terminal `prompt too long` failure.

## 1. Problem

RFC 036 detects likely context-window exhaustion from relay-local proxy signals and
can checkpoint and pause. A real long-running adopter session exposed a remaining
failure mode:

- the provider cache approached the full context window;
- the client continued to accept work while latency remained superficially normal;
- native compaction itself required the oversized history;
- the client finally rejected the request as too long;
- a local proxy remained healthy but performed no effective reduction;
- recovery required abandoning the saturated session and reconstructing state from
  durable project artifacts.

The current guard says "checkpoint + pause" but does not define when a client session
must be rotated, how to package the restart, or how to distinguish provider-context
pressure from account-usage pressure and proxy health.

## 2. Non-goals

- No provider UI automation, process termination, or implicit new-session launch.
- No model API call from the core.
- No hard-coded assumption that every provider has the same context window.
- No replacement for native provider compaction.
- No claim that a compression ratio predicts answer quality.
- No forwarding of raw conversation history, hidden reasoning, large logs, or
  complete tool transcripts into the resume packet.
- No change to the degree-1 relay or pen authority.

## 3. Terminology and separation of concerns

| Concern | Owner | Remedy |
|---|---|---|
| Provider context pressure | RFC 036 + this RFC | checkpoint, pause, rotate session |
| Provider account limits | RFC 040 | cooldown until reset |
| Large block before insertion | RFC 037 | digest/reference or optional compression |
| Proxy transport failure | operator/IT operations | restart or transport remediation |
| Shared relay growth | RFC 033 | compact contracts and references |

`headroom` in the runtime command continues to mean remaining model-session capacity.
It is not the optional Headroom/Kompress backend and is not a proxy-health check.

## 4. Signals

### 4.1 Signal hierarchy

The guard uses the best available signal and records its provenance:

1. exact provider/harness token counts and advertised context limit;
2. local proxy metrics for original input/cache-read/cache-write tokens;
3. client events such as native compaction failure or `prompt too long`;
4. RFC 036 local estimates: turns, relay bytes, handoff bytes and checkpoint age.

Lower-quality signals never override a fresher exact signal. All estimates must be
labelled as estimates.

### 4.2 Normalized payload

```json
{
  "window": {
    "status": "ok|warning|high|critical|unknown",
    "used_tokens": 750000,
    "limit_tokens": 1000000,
    "used_ratio": 0.75,
    "signal": "provider|proxy|client|estimate",
    "observed_at": "2026-07-13T00:00:00Z",
    "reason": "provider cache and uncached input"
  }
}
```

Counts are optional when unavailable. A client terminal event sets `critical` even
without a numeric ratio.

## 5. Advisory thresholds

Defaults are ratios of a known provider window, not fixed token counts:

| State | Default | Required guidance |
|---|---:|---|
| `ok` | `< 0.60` | continue |
| `warning` | `>= 0.60` | prepare checkpoint at next phase boundary |
| `high` | `>= 0.75` | checkpoint now; finish only the bounded current action |
| `critical` | `>= 0.85` | stop adding context; checkpoint/pause/rotate |

Operators and provider adapters may override thresholds. The invariant is ordering:
`0 < warning < high < critical <= 1.0`. Invalid policies fail closed to RFC 036 local
signals and emit a doctor finding.

`unknown` is not an ok-equivalent: when the signal yields `unknown` (for example a used
count with no advertised limit) the guard defers to the RFC 036 proxy status and never
downgrades below it.

**Backward compatibility.** This RFC widens the existing `--window-status` flag and the
JSON `status` field to add `critical` and `unknown`; `ok`, `warning` and `high` keep their
RFC 036 meaning. A consumer that only knows the legacy three must treat an unrecognized
value as `unknown` (advisory), never as an error.

The defaults are deliberately early. Native compaction needs spare capacity to read
and summarize the current history; waiting until 95–100% makes the recovery operation
compete with the failure it is meant to prevent.

## 6. Phase-boundary policy

Even below numeric thresholds, the runtime should recommend a checkpoint after:

- exploration before implementation;
- implementation before broad verification;
- verification before review or release;
- completion of a large delegated workflow;
- task or repository-scope change;
- repeated native compaction in a short interval.

A recent checkpoint is not by itself a rotation. Rotation is recommended when context
pressure is high/critical or the client reports a terminal context event.

## 7. Command surface

Extend, do not replace, the RFC 036 command:

```bash
python3 m8shift-runtime.py headroom claude \
  --window-used-tokens 750000 \
  --window-limit-tokens 1000000 \
  --window-signal proxy \
  --checkpoint \
  --prepare-rotation \
  --json
```

Client/harness fallback remains supported:

```bash
python3 m8shift-runtime.py headroom claude \
  --window-status critical \
  --window-reason "client rejected oversized prompt" \
  --checkpoint \
  --prepare-rotation \
  --pause-on critical \
  --reason "fresh provider session required"
```

Proposed new flags:

| Flag | Meaning |
|---|---|
| `--window-used-tokens N` | exact/advisory current context usage |
| `--window-limit-tokens N` | provider context limit associated with the signal |
| `--window-signal KIND` | `provider`, `proxy`, `client`, or `estimate` |
| `--prepare-rotation` | write a bounded resume packet after a successful checkpoint |
| `--resume-output PATH` | explicit output path under `.m8shift/runs/` |

`--prepare-rotation` does not pause unless the existing explicit `--pause-on` gate is
also supplied and satisfied.

## 8. Rotation bundle

One rotation operation produces two immutable, referenced artifacts:

1. the existing RFC 036 checkpoint/session report;
2. a new bounded resume packet.

The resume packet contains:

- current objective and scope;
- relay state and last completed turn;
- locked decisions and unresolved disagreements;
- changed files, worktree and exact Git revision;
- commits pushed/not pushed;
- tests and evidence references;
- blockers and open risks;
- next concrete action;
- paths/run ids for the checkpoint, session report and raw evidence;
- a generated fresh-session instruction.

It excludes raw logs, full diffs, full files, conversation history, model reasoning,
subagent transcripts and credentials. Exact claims remain references to raw evidence
under the RFC 033 verification floor.

### 8.1 Generated fresh-session instruction

```text
Start a fresh provider session. Do not resume the exhausted session.
Read the referenced M8Shift checkpoint, latest handoff, decisions and Git status.
Resume only the stated objective. Retrieve raw evidence only when needed for
verification; do not reconstruct or paste the prior conversation.
```

The text must use project-relative paths and placeholders in documentation. Runtime
artifacts may contain the active project paths under existing local-state policy.

## 9. State machine

```text
ok
  -> warning: advise next-boundary checkpoint
  -> high: checkpoint + rotation recommendation
  -> critical: checkpoint + explicit pause + fresh-session requirement

critical
  -> rotated: operator confirms fresh session and consumes resume packet
  -> blocked: checkpoint failed; preserve current state and report recovery command
```

No automatic transition may close a client, discard a session, force-claim the pen or
resume the relay. The operator owns the UI/session boundary.

## 10. Failure behavior

- Missing token limit: fall back to RFC 036 local thresholds.
- Stale external signal: ignore it and emit a finding.
- Checkpoint failure: do not pause automatically; report the failure and preserve state.
- Resume-packet failure after checkpoint: retain the checkpoint and return non-zero.
- Agent is not the holder: read-only recommendation; no pause or relay mutation.
- Already critical and client rejects prompts: an external operator/agent may generate
  the bundle from durable M8Shift/Git state without asking the saturated model to summarize.
- Compression backend absent or ineffective: rotation still works; compression is not a
  prerequisite.

## 11. Security and privacy

- Reuse RFC 022/033 redaction and source-reference rules.
- Never ingest credentials from process environments into the rotation bundle.
- Treat provider/proxy metrics as untrusted advisory input; validate types, ranges and age.
- Keep the core stdlib-only and network-free.
- Do not store model hidden reasoning.
- Preserve exact decisions, checksums and evidence references verbatim.
- Apply RFC 052 project-compartmentalization rules to generated artifacts and fixtures.
- The `rotation_confirmed` signal must originate from an explicit, authenticated operator
  action (a command invocation); it is never inferred from model, relay or handoff text,
  which are untrusted coordination data (prompt-security floor).
- The consuming fresh session treats the resume packet as untrusted coordination data: it
  re-applies claim -> work -> append and derives no new authority, secrets access, or scope
  from packet text. The generated fresh-session instruction (§8.1) is guidance to the
  operator/agent, not a system prompt.

## 12. Observability

Proposed runtime events:

```text
headroom.warning
headroom.checkpoint
headroom.rotation_prepared
headroom.rotation_confirmed
headroom.rotation_failed
```

`status-runtime` should show:

- current normalized window state and signal age;
- last checkpoint and rotation packet;
- recommended next action;
- whether a fresh session has been operator-confirmed.

The display must not imply that a checkpoint freed provider context. Only a fresh
session or provider-confirmed compaction changes that state.

## 13. Delivery plan

### Phase A — contract and fixtures

- finalize JSON fields, thresholds and stale-signal rules;
- add provider-neutral fixtures for ok/warning/high/critical/unknown;
- add an anonymized regression fixture for terminal oversized-prompt recovery.

### Phase B — read-only recommendation

- accept normalized token signals;
- compute ratios and surface rotation advice in `headroom --json`, status and doctor;
- no new mutation.

### Phase C — rotation bundle

- implement `--prepare-rotation` and bounded resume-packet generation;
- reuse the existing checkpoint writer;
- verify project-relative references, size bounds and redaction.

### Phase D — explicit pause integration

- connect critical rotation to the existing `--pause-on` authorization path;
- add operator-confirmation recording for a fresh session;
- document Claude, Codex and generic-client examples without UI automation.

### Phase E — measured adoption

- dogfood on long-running sessions;
- measure false positives, checkpoint size, recovery completeness and time-to-resume;
- adjust defaults only from evidence, not a single provider incident.

## 14. Acceptance criteria

1. A known 75% window signal produces `high` and a checkpoint, and — only when
   `--prepare-rotation` is passed — a rotation packet; without that flag it recommends
   rotation but writes no packet.
2. A known 85% signal or terminal client event produces `critical` guidance.
3. No command closes or starts an AI client session.
4. No relay mutation occurs without the existing holder and explicit pause gate.
5. A fresh session can resume objective, decisions, Git state and next action using only
   the bundle plus referenced project evidence.
6. The packet stays within a configurable exact byte/line budget.
7. Raw logs, full history, credentials and hidden reasoning are absent.
8. Missing/stale/malformed metrics degrade to RFC 036 estimates with findings.
9. A saturated-model recovery can be prepared externally from durable state.
10. Tests cover provider-neutral behavior and do not require network or model access.

## 15. Test plan

- Unit: threshold ordering, ratio boundaries, unknown limit, stale signal and bad types.
- Unit: bundle schema, size cap, redaction, references and deterministic ordering.
- Unit: explicit pause authorization and non-holder read-only behavior.
- Regression: native compaction unavailable / oversized prompt event.
- Regression: checkpoint succeeds but resume packet fails.
- Integration: warning -> high -> critical -> operator-confirmed rotation lifecycle.
- Compatibility: existing RFC 036 commands and JSON remain valid without new flags; the
  widened `--window-status`/`status` enum keeps `ok|warning|high` intact and a legacy
  consumer treats `critical`/`unknown` as advisory (not an error).
- Hygiene: RFC 052 path/identity/secret scans on fixtures and generated examples.

## 16. Rollback

The feature is companion-only and opt-in during delivery. Rollback removes the new flags,
events and display fields while preserving ordinary RFC 036 checkpoints and session reports.
Previously written rotation bundles remain inert local evidence.

## 17. Open decisions

1. Should the warning/high/critical defaults be global ratios or provider-manifest data?
2. What exact byte and line limits should the resume packet enforce?
3. Does `rotation_confirmed` require a new command, or can an existing `resume` event carry
   the packet reference?
4. Which proxy metrics are stable enough to ingest without coupling M8Shift to one proxy?
5. Should phase-boundary checkpoints be advisory text first or a dedicated runtime event?
6. How long may an exact external window signal remain fresh?

## 18. Decision requested

Approve Phase A/B as a provider-neutral extension of RFC 036. Keep bundle creation,
pause integration and provider adapters behind separate review gates. Do not implement
automatic UI/session lifecycle management.
