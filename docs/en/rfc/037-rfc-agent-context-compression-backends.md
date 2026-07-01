# RFC 037 — Agent Context Compression Backends and Digest-Based Handoffs

- Status: draft
- Target stage: optional context companion (`m8shift-context.py`) — policy + file protocol
- Builds on: [RFC 033 Context Economy](033-rfc-context-economy.md) (policy), [RFC 034 Companion Adapter Interface](034-rfc-companion-adapter-interface.md) (mechanism), [RFC 026 sidecar retention](026-rfc-sidecar-retention.md)
- Related: [RFC 036 Token-window exhaustion](036-rfc-token-window-exhaustion.md), [RFC 040 AI session usage monitoring](040-rfc-ai-session-usage-monitoring.md)
- Date: 2026-07-01
- Origin: external draft (Codex), reviewed and re-architected by Claude against the shipped code before placement.

## Summary

M8Shift should add an optional **context-compression policy layer** that measures large
agent-bound context, compresses eligible blocks close to the point of insertion, preserves
raw content locally, and hands agents **compact digests and bounded references instead of raw
bulk**. Raw content is retrieved only on demand, by bounded reference.

This RFC is the **mechanism** under the policy already defined by **RFC 033 (Context Economy)**
— "agents exchange contracts, not context". It does **not** introduce a new adapter framework:
compression backends are **RFC 034 companion adapters**, reusing that RFC's argv-only,
identity-pinned, output-capped, fail-closed runner. It complements the two exhaustion RFCs on
their own axes: **RFC 040** pauses a shift when a rolling provider usage window nears its limit;
**RFC 036** detects local token-window pressure; RFC 037 reduces how much context is sent *before*
either limit is reached.

The target problem is concrete: real M8Shift sessions routinely run very large — roughly 90% of
observed contexts exceed 90,000 tokens. Context width is the normal operating condition, not a
rare optimization.

Operational goal:

```text
Measure before sending.
Compress before insertion.
Store raw locally (redacted).
Send digests and bounded references, not bulk.
Retrieve raw content only on demand.
Never remove context that verification needs.
```

## Motivation

Long M8Shift sessions involve several agents (typically Claude and Codex). Each can read files,
inspect logs, run tests, generate diffs, and pass findings on. Without a compression boundary,
every agent becomes a context amplifier: one reads a large tree, the next receives a full command
output, a third receives that output plus two summaries, and the next handoff repeats all of it.

RTK-style tools compress shell output but do not address conversation history, file reads, long
handoffs, JSON payloads, traces, or repeated task state. Headroom-style tools compress broader
agent context, but M8Shift must not hard-code its architecture around a single external project.
**M8Shift owns the policy; compression engines are optional backends.**

## Positioning — three RFCs, one boundary

| Concern | RFC | This RFC's relationship |
|---------|-----|-------------------------|
| *What* agents exchange and why (contracts not context) | **033** policy | 037 implements it as a concrete file protocol + backends |
| *How* an external tool is run safely (manifest, argv, identity-pin, caps, fail-closed) | **034** mechanism | 037 backends **are** 034 adapters — no parallel interface |
| Local token-window pressure detection + graceful pause | **036** | 037 reduces context before the window is stressed |
| Rolling provider usage-window monitoring + cooldown | **040** | 037 reduces consumption before the window nears its cap |

RFC 037 **does not** define new handoff semantics, a new adapter framework, or a new usage
monitor. It defines: measurement, a compression decision policy, a JSON record/digest protocol,
bounded local retrieval, and the reuse of RFC 034 adapters as compression backends.

## Design principles

### 1. M8Shift owns policy

Compression engines are implementation details. M8Shift decides what is eligible, when to
compress, when to reference-only, what raw is retained, and what digests reach agents.

```text
M8Shift policy → RFC 034 adapter (backend) → compressed context → agent
```

### 2. Measure before send (advisory)

Before a large block is sent to an agent, M8Shift estimates its size and records it. The estimate
is the **advisory proxy** already used by the context companion (`estimated_proxy_tokens = bytes/4`,
`m8shift-context.py`), never a provider tokenizer. It drives runtime **policy decisions only**.

### 3. Estimates are advisory; measured gains use real tokenizers

Runtime records carry `estimated_proxy_tokens_before/after` (bytes/4) and are labelled as
estimates. Any **claimed compression gain** (a benchmark, a release note, an operator report as
fact) must be validated with **real tokenizers** — `tiktoken` `o200k_base` for Codex, the Anthropic
`count_tokens` API for Claude, **never mixed** — plus an **output-equivalence check** (verbatim
content preserved; dropped content flagged and referenced by hash), following
[`docs/en/context-pack-measurements.md`](../context-pack-measurements.md) and RFC 034's rule that
**compression is not proof of equivalence**. If a real-token gain cannot be shown, the optimization
is reconsidered, not shipped.

### 4. Preserve raw locally (redacted), reference by bound

Raw content is written to local `.m8shift/` storage **after redaction** (see Security), before
compression, when retention allows. Agents receive `compact summary + raw reference`, or for very
large content `digest + raw reference only` — never the full raw plus summaries.

### 5. Compression never starves verification

This is the load-bearing invariant, inherited from **RFC 033 §9**. A digest or compact view too
thin to verify or review the work is a **failure, not an economy**. Digests and compact refs are
**operational views, never evidence**. The retrieved **raw original** — not the digest — is the
source of truth for verification, adversarial review, and tamper-checking (RFC 030). Any agent
proving, reviewing, or auditing must always be able to pull the bounded raw it needs. Economy
must never win over correctness.

### 6. Fail **closed** to reference-only — never fail open to raw

If a backend errors, redaction errors, or the secret classifier is unsure, M8Shift degrades to a
**`raw_output_reference` only** (path + digest, zero inline content). It must **never** fall back
to inserting the original un-redacted blob — that is the exact outcome the feature exists to
prevent. All compression operations run in the companion and are advisory: a failure degrades to
reference-only and never touches the core lock or the append path.

## Compression backends are RFC 034 adapters

RFC 037 introduces **no new adapter interface**. Each backend is a companion adapter under
[RFC 034](034-rfc-companion-adapter-interface.md), described by an `m8shift.adapter.v1` manifest,
validated by the existing `adapter_findings()` doctor lint, and executed by the existing
`run_adapter_process()` runner — which is **argv-only (`shell=False`), identity-pinned by absolute
path + sha256, output-byte-capped, timeout-bounded, telemetry-disabled, and fail-closed**. A
backend result is the existing `m8shift.adapter.result.v1`; the compressed-context record (below)
**wraps** that result rather than defining a parallel schema.

Backend → RFC 034 mapping:

| Backend | RFC 034 adapter type | Status |
|---------|----------------------|--------|
| **builtin** | *native* (no adapter — in-process stdlib) | always available, the fallback |
| **RTK** | `shell_output_filter` | already shipped (`rtk-shell-output`, RFC 034 / #64 / #76) — reused verbatim |
| **Headroom (external, Apache-2.0)** | `context_transform` (promoted from RFC 034 §11 reserved) | optional, opt-in, identity-pinned like RTK |

Rules for every backend:

- **argv-only, one-shot, local.** A backend is a local subprocess that reads stdin (or a temp
  file) and writes stdout, then exits. No backend may open a socket, listen on a port, run a
  persistent process, or reach the network. Consequently **Headroom "proxy" mode
  (`--port`), "MCP" mode, and any `allow_network` toggle are out of scope** — they are network
  daemons and violate the charter.
- **identity-pinned** by absolute path + sha256 (RFC 034), fail-closed to native/reference-only
  when absent, unpinned, or mismatched — the same model as RTK-default (#76).
- **retrieval is local filesystem reads** of the `raw_ref`/`compact_ref` written under `.m8shift/`.
  There is no external retrieval service.

Default backend priority: **builtin → RTK (for shell/tool content types) → Headroom (broad
context, if pinned) → reference-only**. The default `default_backend` is **`builtin`**, not an
external tool.

> Naming note: "Headroom" here is the external compression tool; it is unrelated to the internal
> `m8shift-runtime.py headroom` token-window guard (RFC 036). Backend id: `headroom_ext`.

## Records and digests (JSON/JSONL only)

All on-disk state is **JSON** (append-only streams as `.jsonl`), matching the stdlib-only charter
and the existing context companion (`m8shift-context.py` uses `json` exclusively — there is no YAML
anywhere in the tree, and adding a YAML parser would break "no external Python dependency").
Records extend the existing `.m8shift/context/` layout (`metrics.jsonl`, receipts) and add a
task-scoped raw store.

### `compressed_context_record` — `m8shift.compressed_context_record.v1`

Describes one compression operation; **wraps** an `m8shift.adapter.result.v1`.

```json
{
  "schema": "m8shift.compressed_context_record.v1",
  "id": "ccr-20260701-121455-pytest",
  "task_id": "task-123",
  "agent": "claude",
  "content_type": "test_output",
  "created_at": "2026-07-01T12:14:55Z",
  "input": { "command": "pytest", "cwd": "<root>", "exit_code": 1 },
  "backend": "builtin",
  "adapter_result": { "schema": "m8shift.adapter.result.v1", "...": "the RFC 034 result" },
  "estimated_proxy_tokens_before": 94320,
  "estimated_proxy_tokens_after": 6840,
  "compression_ratio": 0.9275,
  "estimate_basis": "proxy_bytes_div_4",
  "reversible": true,
  "fallback_used": false,
  "storage": {
    "raw_ref": ".m8shift/context/tasks/task-123/runs/20260701-121455/pytest.raw.txt",
    "compact_ref": ".m8shift/context/tasks/task-123/runs/20260701-121455/pytest.compact.txt",
    "meta_ref": ".m8shift/context/tasks/task-123/runs/20260701-121455/pytest.meta.json"
  },
  "summary": { "status": "failed", "key_findings": ["..."] }
}
```

The `*_tokens_*` fields are **estimates** (`estimate_basis` names the method). Real-token gains, if
claimed, live in the measurements doc, not here.

### `context_digest` — `m8shift.context_digest.v1`

The compact state of a task (where are we, what was decided, what files matter, what is open). It
is the concrete serialization of RFC 033's shared working memory / Task Packet — **not** a new
handoff semantic. Stored at `.m8shift/context/tasks/<task-id>/context-digest.json`.

### `handoff_digest` — `m8shift.handoff_digest.v1`

A direction-specific transfer packet between agents (what I did, what I found, what to preserve,
what to do next, where the raw evidence is), aligned with the RFC 033 handoff contract and the
relay `append` fields. Stored at `.m8shift/context/tasks/<task-id>/handoffs/NNN-<from>-to-<to>.json`.

### `raw_output_reference` — `m8shift.raw_output_reference.v1`

Points to retained (redacted) raw content without injecting it. This is also the **fail-closed
degrade target**: when compression cannot proceed safely, M8Shift emits a reference only.

## Storage, identity, and bounded retrieval

- **Layout.** Records under `.m8shift/context/` (reusing the RFC 034 tree and `metrics.jsonl`);
  task raw stores under `.m8shift/context/tasks/<task-id>/runs/…`. All runtime-generated,
  gitignored by default (RFC 026 retention applies; only explicit doc examples are committed).
- **record-id → path is validated, never trusted.** A record id must match `SAFE_ID_RE`
  (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`, the existing constant) and is the **sole** input to path
  construction via the existing `safe_join(root, …)`. A stored path string is never re-used as an
  input path. This blocks `../`, absolute-path, and symlink traversal through a crafted id.
- **Bounded retrieval is mandatory.** `context show <id> --raw` **without** an explicit
  `--lines A:B` (or byte cap) returns at most a small default window (the profile
  `raw_log_inline_limit_lines`, currently 80) plus an explicit truncation notice. Full raw
  retrieval requires an explicit range or an explicit policy opt-in.
- **`context grep <id> "pattern"` is a native stdlib `re` scan** inside the companion — never a
  subprocess, never a shell. The pattern is length-capped and rejected if catastrophic
  (bounded repetition), the scanned bytes are capped, and matches are line-bounded. No external
  grep/rg process is invoked.

## Security constraints

Normative — none of these may be violated:

- **Redaction is the default, not an opt-in.** If `context-compression.json` is missing or
  malformed, behave as `redact_before_store: true` **and** reference-only (fail-safe). Disabling
  redaction requires an explicit, present, valid config value.
- **Redaction is concrete and versioned.** Before any `*.raw.txt` write, apply a defined, versioned
  secret pattern set (PEM/private-key headers; AWS / GitHub / OpenAI / Anthropic key shapes;
  `Authorization:` / `Bearer` headers; `.env` `KEY=VALUE`; JWTs). A detected secret triggers
  **reference-quarantine or refusal**, never verbatim storage.
- No provider credentials in `M8SHIFT.md`; no OAuth tokens in sidecars; no private keys in raw
  stores; no browser-cookie or Keychain reading by default.
- **Backends are argv-only** (`shell=False`), identity-pinned, output-capped, timeout-bounded,
  **no network, no port, no persistent process** (reusing the RFC 034 runner).
- Compression / retrieval / redaction errors **fail closed to reference-only** (never to raw),
  are advisory, and never crash or block the core relay lock or append path.

## Configuration — `.m8shift/context-compression.json`

Policy-only knobs. **Backend enablement, identity (path + sha256), and modes are owned by the
RFC 034 adapter manifests** under `.m8shift/context/adapters/`, not duplicated here.

```json
{
  "schema": "m8shift.context_compression.config.v1",
  "enabled": true,
  "default_backend": "builtin",
  "measurement": { "estimate_basis": "proxy_bytes_div_4", "measure_before_send": true, "record_metrics": true },
  "thresholds": { "compress_above_tokens": 2000, "reference_only_above_tokens": 20000, "warn_above_tokens": 90000, "hard_limit_tokens": 120000 },
  "policy": {
    "preserve_raw": true,
    "redact_before_store": true,
    "include_raw_ref": true,
    "include_token_estimates": true,
    "never_compress": ["secrets", "credentials", "private_keys", "tokens"]
  },
  "backends": { "rtk": { "scope": ["shell_output", "test_output", "logs", "git_output"] } }
}
```

## Compression decision policy

Advisory, driven by the proxy estimate:

```python
def decide_context_action(tokens_estimate: int) -> str:
    if tokens_estimate >= 120000:
        return "refuse_raw_reference_only"
    if tokens_estimate >= 20000:
        return "reference_only_with_digest"
    if tokens_estimate >= 2000:
        return "compress"
    return "send_as_is"
```

Because most real sessions exceed 90,000 tokens, the practical default for large tasks is
`reference_only_with_digest`.

## Relationship with the exhaustion RFCs

RFC 037 sits *upstream* of both exhaustion mechanisms and shares **labelled, axis-separated**
metrics — it never conflates them:

```text
agent prepares context
  → RFC 037 measures (advisory estimate) and compresses / references bulk
  → provider usage grows more slowly
  → RFC 040 monitors the rolling usage window (real provider rate-limit ratio); cools down at threshold
  → RFC 036 detects local token-window pressure; pauses gracefully
```

Report families stay separate: **usage-window** (RFC 040, rolling account, real ratio) vs
**context-compression** (RFC 037, per-context, advisory estimate unless real-token validated).

## Command surface (`m8shift-context.py`)

Adapter execution (compress / retrieve / stats) lives in `m8shift-context.py`, the existing
context companion that already owns the adapter runner, `metrics.jsonl`, receipts, and the doctor
lint. (Resolves the draft's open question: the companion already exists; there is no new script.)

```bash
python3 m8shift-context.py context init
python3 m8shift-context.py context backends list
python3 m8shift-context.py context backends check          # reuses adapter doctor lint (identity-pin, argv-only)
python3 m8shift-context.py context measure <file|ref> --json
python3 m8shift-context.py context compress <file|ref> --type test_output --agent claude --json
python3 m8shift-context.py context show <record-id> [--compact | --raw] [--lines 1:80]
python3 m8shift-context.py context grep <record-id> "pattern"     # native stdlib re, bounded
python3 m8shift-context.py context digest update --task <task-id>
python3 m8shift-context.py context handoff create --from claude --to codex --task <task-id>
python3 m8shift-context.py context stats --json
```

## Suggested implementation phases

- **Phase A — documentation (this RFC).** Place the RFC; link it from the RFC index; add a pointer
  in `context-pack-measurements.md` that RFC 037 backends inherit the **same real-tokenizer +
  output-equivalence DoD**. Validation: `rg "RFC 037|compressed_context_record|handoff_digest" docs/en`.
- **Phase B — local records + builtin fallback.** Implement the JSON records/digests, the
  in-process builtin compressor (head/tail preservation, repeated-line collapse, error/path
  extraction, exit-code preservation), redaction-before-store, `SAFE_ID_RE`/`safe_join` path
  discipline, and mandatory bounded retrieval — **before any external backend**.
- **Phase C — RTK backend (reuse).** Wire the existing `rtk-shell-output` RFC 034 adapter as the
  shell/tool-output backend for the configured content types; preserve exit code + key
  diagnostics; fall back to builtin.
- **Phase D — Headroom backend (optional).** Add a `context_transform` RFC 034 adapter manifest for
  Headroom (`headroom_ext`), argv-only + identity-pinned; detect-and-use only when present and
  pinned; never require installation; preserve raw refs independently.
- **Phase E — handoff integration.** Agents receive `context_digest` + `handoff_digest` + compact
  summaries + raw refs by default — not full logs/diffs/trees/outputs/transcripts.
- **Phase F — reporting.** Add `context stats` (`m8shift.context.stats.v1`): records, estimated
  raw/sent/avoided tokens (labelled estimates), average reduction, counts by backend.

Each phase carries its own tests, including negative/abuse cases (traversal id, oversized/ReDoS
grep pattern, secret-bearing raw, missing/malformed config → fail-safe).

## Acceptance criteria

RFC 037's first implementation is accepted when M8Shift can:

1. Measure a context estimate before agent insertion (advisory proxy).
2. Create a `compressed_context_record` that wraps an RFC 034 adapter result, with redacted raw +
   compact refs stored locally.
3. Generate/update a `context_digest` for a task and a `handoff_digest` between agents.
4. Retrieve raw content by validated record-id with **mandatory bounded** selectors.
5. Use the builtin fallback with no external dependency.
6. Optionally detect and use RTK (`shell_output_filter`) and Headroom (`context_transform`) **as
   RFC 034 identity-pinned adapters**, fail-closed when absent/unpinned.
7. Report estimated raw/sent/avoided tokens, labelled as estimates.
8. Keep compression policy under M8Shift control, degrade **fail-closed to reference-only**, and
   never remove context that verification needs.

## Open questions

- Should `context_digest` update automatically after each run record, or by explicit command only
  (default: explicit)?
- Should raw retention be per-task, global, or both (interacts with RFC 026)?
- Should raw references be portable across worktrees (RFC 008)?
- What exact versioned secret pattern set ships in v1, and how is it updated?

## Non-goals

This RFC does not: make Headroom or RTK required; proxy or intercept provider traffic; open any
network port or run any daemon; store provider credentials, secrets, or private keys; replace the
relay lock; replace RFC 036 / RFC 040; guarantee identical model outputs after compression; define
a new adapter framework (it reuses RFC 034); or insert raw logs into prompts by default.
