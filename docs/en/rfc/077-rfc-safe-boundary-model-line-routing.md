# RFC 077 — Safe-boundary model-line evidence and routing

- **Status:** accepted design; Slice A schema, fixtures, and fixture-only base
  conformance implemented; automatic routing remains disabled
- **Date:** 2026-07-18
- **Issue:** #212
- **Scope:** same-provider model-line evidence, deterministic safe-boundary
  routing, and reconstructible decision records
- **Builds on:** [RFC 040](040-rfc-ai-session-usage-monitoring.md),
  [RFC 070](070-rfc-provider-pinned-model-launch.md),
  [RFC 073](073-rfc-adapter-registry-detached-durability.md),
  [RFC 075](075-rfc-model-line-budget-observability.md), and
  [RFC 076](076-rfc-incident-first-deterministic-reentrant-discipline.md)

## 1. Decision and non-negotiable boundary

RFC 075 established that account headroom and one model line's capacity are not
interchangeable. This RFC selects the Phase 2 contract without rewriting that
accepted research record.

“Switch” means selecting another operator-declared model line **between managed
provider invocations**. It happens only after a durable checkpoint and before
the next provider request. It never changes a model inside a streamed response,
replays partial output or tool effects, replaces an agent while it holds
`WORKING_<agent>`, synthesizes a relay turn, releases a pen, or force-recovers a
lock. Relay ownership and stale-lock recovery remain exclusively governed by the
core protocol.

V1 routes only among operator-declared model pins under the same provider, auth
scope, and launch mode. Cross-provider failover is deferred because credentials,
capabilities, cost, and output semantics change. The relay agent identity never
changes.

The default policy is `observe_only`. Automatic selection requires all of:

1. `auto_at_safe_boundary=true` in an explicit operator policy;
2. an ordered fallback list containing validated RFC 070 model pins;
3. fresh automatable evidence for the target;
4. the durable checkpoint in §2;
5. no per-agent usage hold under §5; and
6. a switch ordinal below the configured cap, whose V1 default is one.

No adapter invents a target and no account percentage is promoted to line
evidence.

## 2. Named durable checkpoint and blank-agent reconstruction

The safe-boundary checkpoint is not conversational memory or a vague “last
known good” state. It is the compound `checkpoint` object in an immutable
`m8shift.route-decision.v1` record, containing:

- the resolved immutable attempt plan at
  `.m8shift/runtime/fleet/attempts/<attempt-id>.json` and its SHA-256;
- the relay session, last closed turn number, exact closed-turn SHA-256, and the
  non-working relay state observed at the boundary;
- the last completed managed invocation ordinal; and
- the next invocation ordinal to which the selected pin applies.

The attempt plan supplies the validated provider/auth/mode and current RFC 070
pin. The immutable relay turn plus session identifies the authoritative journal
position without copying a live lock or process listing. The ordinal pair names
the precise gap between provider requests. A checkpoint is invalid while the
relay state is `WORKING_*`; the schema consequently accepts only `IDLE`,
`AWAITING_*`, `PAUSED`, or `DONE` as recorded states, and policy admits a launch
only from a state already eligible under the existing listener contract.

For the RFC 076 blank-agent drill, the agent receives the relay journal, the
referenced attempt plan, the route/evidence directory, and the checked-in
schemas. It must verify the hashes and reconstruct the old pin, selected pin,
last completed ordinal, next ordinal, policy, evidence freshness, and stable
reason code without chat, shell scrollback, a live process, or wall-clock
inference. A missing file, hash mismatch, half-written record, or disagreement
fails closed to `needs_reconciliation`; it never reconstructs a switch from the
currently configured model alone.

Runtime route files remain recoverable operational evidence, not relay
authority. Their loss cannot mutate the relay or justify a launch. A completed
routed turn may cite its decision id in the agent-authored immutable handoff, but
the launcher never authors that handoff itself.

## 3. Evidence schema

An external adapter emits `m8shift.model-line.evidence.v1`. Its checked-in JSON
Schema is:

```text
examples/model_line_budget_adapter/schema/
  m8shift.model-line.evidence.v1.schema.json
```

The normalized record contains provider, mode (`api`, `subscription_cli`, or
`cloud`), requested model, scope, applicability (`exact_model`,
`documented_group`, or `unknown`), nullable `provider_bucket_id`, nullable
reported ratios/reset, signal, provenance, capture/freshness instants, adapter
name/version, and an optional documented mapping reference/version.

`provider_bucket_id` is never synthesized. A null bucket id does not by itself
forbid automation: a vendor adapter may establish exact or documented-group
applicability while leaving the provider id null, as Anthropic headers require.
`applicability=unknown` never becomes line evidence merely because an invocation
names a model.

Forecasts live only in the separate nullable `estimate` object. Estimated values
are never copied into provider-reported remaining quota and never authorize an
automatic launch.

The RFC 075 anti-recurrence fixture retains three independent records:

```text
account headroom > 0
model-a remaining = 0
model-b remaining > 0 or unknown
```

No argmax, aggregate percentage, requested slug, or account bucket may collapse
them.

## 4. Adapter boundary and vendor honesty

RFC 040's process boundary remains intact. The passive core/runtime invokes a
bounded `cli_json` command, validates normalized JSON, and never imports vendor
SDKs, reads credentials, or opens provider sockets.

An external adapter package owns `ModelLineBudgetAdapter`, bounded request and
result dataclasses, common nullability/freshness validation, redaction, and
schema serialization. Its two fact-producing methods are:

```text
probe(target) -> evidence
classify_refusal(observation) -> rejection evidence
```

Vendor subclasses contain retrieval and documented model/group mapping only.
Adapters report facts, never `switch`, `continue`, or `halt` decisions. A pure
generic policy function consumes evidence and operator policy in a later slice.

Vendor rules are pinned to RFC 075's verified matrix:

- Anthropic API headers may establish documented model/group applicability while
  the bucket id stays null; subscription OAuth remains aggregate/unknown.
- OpenAI API shared-limit mappings must be documented/provider-derived; Codex
  app-server subscription buckets remain aggregate/unknown.
- Google model-dimensioned quota metrics may be line evidence; console-only,
  dynamic shared quota, and CLI statistics remain non-automatable diagnostics.
- Mistral configured per-model limits and Admin history may warn or forecast;
  live switching needs fresh remaining evidence with justified applicability.

Failure to parse, time out, or verify applicability yields unknown, never
availability. Commands are argv arrays with `shell=False`, bounded
stdout/stderr/time, redacted output, and disabled-by-default registration.

## 5. Usage holds precede line routing

RFC 040's per-agent `m8shift.usage.hold.v2` is a higher-priority admission gate
than every model-line rule. Before evidence probing or fallback selection, the
launcher reads and validates:

```text
.m8shift/runtime/usage-holds/<agent>.json
```

If a valid hold exists, routing stops with `agent_usage_hold_active`. It does not
probe or launch another line. An available fallback does not clear, shorten, or
supersede the hold; line routing never “de-holds” a throttled agent. A corrupt
hold fails closed under RFC 040's existing contract. Only the existing explicit
`usage resume` path may clear the hold after its own fresh-`ok` gate.

This precedence also applies during startup reconciliation. A decision record
from before a hold cannot be replayed after the hold appears; the next invocation
must pass hold admission again and, when eligible, receive a new decision id.

## 6. Deterministic decision table

Evidence states are `available`, `drain`, `exhausted`, `unknown`, and `stale`.
The hold gate in §5 is priority zero. If it passes:

1. Active available → continue on the current pin.
2. Active drain + target fresh/available + automatable line evidence → write the
   checkpoint/decision, compile the target through RFC 070, and use it only for
   the next invocation.
3. Active exhausted, or refusal before output/effect + target independently
   fresh/available → stop the failed invocation and switch only for the next
   invocation. V1 never silently replays the failed prompt.
4. Any partial stream, tool effect, ambiguous completion, missing checkpoint, or
   non-retry-safe refusal → clean halt even if a target looks available.
5. Target unknown/stale/console-only/history-only → never automatic switch;
   clean halt if the active line cannot proceed, otherwise warn and continue.
6. Active unknown/stale without refusal → preserve RFC 040 fail-open behavior as
   an `observe_only` warning. Optional `require_known_preflight` may halt before
   launch but never upgrades unknown to available.
7. Subscription CLI → no automatic switch by default. Even with explicit
   policy, aggregate account data cannot authorize it; V1 requires a direct
   no-output refusal for the active line and independently automatable target
   evidence.
8. Switch cap reached or all candidates rejected → clean halt with a stable cause
   and actionable operator message.

A clean halt stops the managed producer/listener, persists the redacted decision
and evidence, and notifies. It does not mutate relay ownership. Existing
TTL/stale recovery stays authoritative if the failed process held the pen.

## 7. Immutable route and evidence records

The runtime companion writes one record per decision with create-exclusive,
atomic semantics under:

```text
.m8shift/runtime/model-line-routing/<relay-session>/
  evidence/<evidence-id>.json
  decisions/<decision-id>.json
```

Evidence files use `m8shift.model-line.evidence.v1`. Decision files use the
checked-in `m8shift.route-decision.v1` schema:

```text
examples/model_line_budget_adapter/schema/
  m8shift.route-decision.v1.schema.json
```

The path components are bounded opaque ids, never provider text. Existing files
are immutable: a retry, warning, halt, or reconsideration receives a new id.
Each decision records requested/selected model, adapter name/version, hashed
evidence references and freshness, policy id, reason code, switch ordinal, and
the exact checkpoint from §2. It stores no credential, raw provider body, prompt,
completion, session token, or secret-bearing command.

Reconciliation enumerates decision files by id, validates their schemas and
hashes, and orders them by recorded timestamp plus decision id. It does not trust
directory mtime. Duplicate ids, invalid ordinals, or two selected pins for one
next-invocation ordinal are conflicts and fail closed.

## 8. Slice A implementation

This change implements only the fixture-safe contract surface:

- the evidence and route-decision JSON schemas;
- the exact RFC 075 three-way split fixture;
- Anthropic null-bucket/documented-group, Codex aggregate/unknown, and Gemini
  console-only fixtures;
- an immutable route-decision fixture with the named checkpoint; and
- the abstract base class plus deterministic fixture conformance tests for exact
  target binding, nullability, freshness, redaction-by-shape, schema ids, and
  fail-closed unknown fields.

It includes no vendor subclass, provider SDK, network call, credential lookup,
live authentication, route policy integration, listener switch, or relay
mutation.

## 9. Gated delivery slices

- **A — implemented here:** RFC, schemas, fixtures, and base-class conformance;
  no live auth.
- **B:** external fixture-backed vendor subclasses, disabled by default.
- **C:** pure policy state machine and dry-run route/audit plan; no switching.
- **D:** opt-in listener integration at the safe invocation boundary, including
  hold precedence, halt/notify, reconstruction, and no-relay-mutation tests.
- **E:** one live-vendor pilot only after separate operator authorization and
  contract re-verification. All other vendors stay degraded/disabled until their
  evidence qualifies.

Each slice requires separate review. Acceptance includes stale target, ordered
fallback, oscillation cap, refusal before output, partial stream/tool effect,
adapter crash/oversize/malformed output, active/corrupt usage hold, exact RFC 070
argv, immutable decision record, reconstruction from durable artifacts, and
proof that the relay bytes and ownership are unchanged.

## 10. Rejected alternatives

- **Amend RFC 075 in place:** rejected; its accepted Phase 1 evidence record
  should remain distinct from the selected Phase 2 behavior.
- **Switch inside a provider stream:** rejected; partial output and tool effects
  cannot be replayed safely.
- **Use aggregate account headroom:** rejected by the incident fixture.
- **Synthesize a bucket id from the model slug:** rejected as false precision.
- **Let a healthy target bypass a usage hold:** rejected; it violates RFC 040's
  explicit resume authority.
- **Store only a mutable latest decision:** rejected; it cannot reconstruct the
  exact boundary or expose oscillation.
- **Cross-provider fallback in V1:** deferred until auth, capability, cost, and
  semantic differences receive their own gated design.
