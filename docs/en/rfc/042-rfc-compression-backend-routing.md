# RFC 042 — Compression backend routing (hybrid builtin / Headroom)

- Status: draft (design only — auto-routing gated behind measured evidence)
- Builds on: [RFC 037 Agent context compression backends](037-rfc-agent-context-compression-backends.md) (the `compress` dispatch this extends), [RFC 033 Context Economy](033-rfc-context-economy.md) (policy), [RFC 034 Companion Adapter Interface](034-rfc-companion-adapter-interface.md) (argv-only pinned runner)
- Related: [RFC 039 Model/task routing](039-rfc-model-task-routing.md) (same *capability-first, evidence-gated* routing philosophy, applied to the compressor instead of the model)
- Date: 2026-07-02
- Origin: operator request for a **hybrid** — use builtin *and* Headroom each where it is best. Grounded in the Round 3 pilot in [`context-pack-measurements.md`](../context-pack-measurements.md).

## Summary

Pick the compression backend by the **actual determinant of which one wins — whether the consumer
can retrieve the raw, and the query shape — not by content-type**. builtin (a ~2% digest + bounded
retrieval) and Headroom (near-lossless, keeps ~45%) are not competitors; they are optimal in
*different* regimes. This RFC defines the routing signal and decision rule to select between them
automatically. **M8Shift's operator priority is explicit: preservation + precision rank above token
efficiency** (losing information loses the meaning of the work). Under that priority, **Headroom is
the *preferred* backend in the regimes where it measurably wins** — **large** contexts that are
inline / no-retrieval / whole-content / many-rapid-facts — when it is installed and identity-pinned
(Round 3 measured it highest on single-pass precision, full inline preservation, zero hallucinations).
**builtin+retrieval stays preferred for retrieve-capable few-fact work** (it tied findability 9/9 at
~1/5 the tokens with no probed-fact loss — the right default there, not a fallback) and is the
fail-closed fallback when Headroom is absent/unpinned. This *refines* — it does **not** globally flip
— the earlier efficiency-first default.

## Motivation

Round 3 measured, at 100k on M8Shift-style content:
- **builtin+retrieval** reached comparable accuracy to Headroom at **~1/5 the tokens** when the
  consumer can retrieve and queries touch a few facts; findability was tied (both preserve all
  probed facts).
- **builtin digest *alone* is near-useless (1/9)** — its value depends entirely on retrieval.
- Headroom's *winning* regimes (no retrieval; whole-content; many rapid facts) were **reasoned from
  the mechanism, not measured**.

Today's dispatch (RFC 037 / v3.40.0) routes broad content to builtin by default, or to Headroom only
via a manual `backends.headroom_ext.auto_enabled` flag — a per-content-type + manual choice, **not**
the determinant that actually decides which wins. A true hybrid routes on that determinant.

## The determinant and decision rule

| Condition | Route to | Why |
|-----------|----------|-----|
| **Large** ctx **AND** (`inline`/no-retrieval **OR** `--whole-content` **OR** many-rapid-facts) **AND** Headroom installed + identity-pinned | **Headroom** | the *measured* Headroom-winning regime: highest single-pass precision + full inline preservation, 0 hallucinations, retrieval can't cheaply cover it |
| **Retrieve-capable + few-fact** query (any length, **even long**) | **builtin + retrieval** | tied findability 9/9 at ~1/5 tokens, no probed-fact loss — the *right default* here, **not** a fallback; retrieval mandatory (digest-alone near-useless) |
| **Short** context (below `compress_above_tokens`) | **builtin** | Headroom's precision edge is negligible on short input; keep the ~5× token saving |
| **Headroom absent / unpinned / errored / config problem, or unknown signal** | **builtin + retrieval** (fail-closed) | comparable, reliable, **no data loss** (raw retrievable); default until the Phase C/D gate opens |

Note: content-type (shell/tool vs broad) still selects the RTK vs native *family* as in RFC 037;
this rule governs the builtin-vs-Headroom choice *within* the broad family, under the precision-first
priority.


## Routing signal

The determinant is supplied to `compress` as explicit, advisory hints (defaulting to the safe,
common case), never inferred silently:

- `--access-mode retrieve|inline` (default `retrieve`) — can the eventual consumer of this context
  fetch the raw by reference? `retrieve` ⇒ builtin is eligible; `inline` (no retrieval) ⇒ Headroom
  regime.
- `--whole-content` (default off) — the consumer needs most of the content at once (not a few
  facts) ⇒ Headroom regime.
- **context size** — length is a **risk *amplifier*, not a standalone determinant**. Short contexts
  (below the RFC 037 `compress_above_tokens` threshold) carry no real precision risk → **builtin**
  (efficiency). Large contexts *raise the stakes* of the access-mode / query-shape choice above, but
  do **not** by themselves route to Headroom: the Round 3 case is long (100k) and **still** favored
  builtin+retrieval for retrieve-capable few-fact queries. So **long + inline/whole-content/many-fact →
  Headroom; long + retrieve + few-fact → still builtin+retrieval**. (The operator framing "short →
  internal, long → Headroom" holds only once retrieval is unavailable or the task needs broad inline
  recall.)
- Callers that know their consumer set these (e.g. a one-shot handoff to an external agent →
  `--access-mode inline`; a local relay handoff → `retrieve`). Absent hints ⇒ `retrieve` +
  few-facts ⇒ builtin. **The common M8Shift path stays builtin with zero configuration.**

## Evidence gate (do not route on a hypothesis)

The precision-first preference rests on **directional** evidence (Round 3: N=9, 1 run, 1 genre, 1
size — a +1-2 precision margin). It is a **fail-safe priority choice**: in the retrieve-capable
benchmark, builtin+retrieval lost **no probed facts** while raw references stayed
retained/authorized/retrievable — so preferring **Headroom in its gated regimes** is a *conditional
priority choice*, **not a general no-loss proof**, and it does not lose recoverable information versus
the retrieve-capable fallback. Two guards:
(a) Headroom is used only when **identity-pinned** (RFC 034) and offline-safe; (b) the full rigorous
benchmark (#84 — incl. no-retrieval / whole-content regimes) **firms or revises** the margin, and the
policy is reversible if fuller measurement contradicts it. Enabling Headroom-preferred-in-its-gated-regimes
as the shipped default is a version-gated change (Phase D).

## Charter

stdlib-only · advisory · no network/daemon (Headroom runs only via the RFC 034 argv-only,
identity-pinned, output-capped runner) · **fail-closed to builtin** on any unknown signal, absent /
unpinned / errored Headroom, or config problem. The online `pip install` for #84 is **measurement-harness
setup only**, never shipped runtime behavior — the runtime path stays offline/cache-only. Redaction-before-store and "compression never
starves verification" (RFC 033 §9) are unchanged: the retrieve path is the safety net, and the
router never sends a form that drops content a consumer cannot recover.

## Relationship to RFC 039

RFC 039 routes the *model* (capability-first, cost tie-breaker, evidence-gated, recommendation
before launch). RFC 042 applies the same philosophy to the *compressor*: pick by fitness
(retrieval/query determinant), fail-safe by default, and require **evidence before enabling** the
non-default branch. The two are orthogonal (one picks who does the work, the other how the context
is packed) and compose.

## Implementation phases

- **Phase A — this RFC (design).** No behavior change.
- **Phase B — signal plumbing.** `compress` accepts `--access-mode` / `--whole-content`, records
  them on the compressed-context record; the router reads them but, until the gate opens, still
  resolves the broad family to builtin unless Headroom is explicitly requested. Fail-closed
  everywhere. Tests: default → builtin; `inline`/`whole-content` → builtin *until gate open*;
  explicit Headroom still honored.
- **Phase C — measurement.** Run the deferred benchmark on the no-retrieval / whole-content regimes
  (part of #84) to confirm (or refute) that Headroom wins there.
- **Phase D — open the gate.** Only if Phase C confirms it: enable auto-route-to-Headroom for the
  `inline`/`whole-content` regimes when Headroom is pinned; document the measured basis.

## Acceptance criteria

1. The decision rule + the `access-mode`/`whole-content` signals are specified and recorded on the
   record.
2. Default and unknown-signal behavior is **builtin** (fail-closed), byte-identical to v3.40.0 until
   the gate opens.
3. Auto-route-to-Headroom is explicitly **gated behind measured evidence (#84) + identity-pinning**.
4. Explicit `--backend headroom_ext` remains available as an operator experiment.

## Open questions

- Should `access-mode` be inferable from the consumer/handoff type (e.g. external one-shot →
  `inline`) or always explicit? (Default: explicit, with sensible per-command defaults.)
- Is there a third regime (streaming / incremental) that neither backend serves well?
- **Combined hybrid** (operator idea): rather than route one-or-the-other, *combine* them — e.g. ship
  Headroom's near-lossless compact **plus** the retrievable raw reference (belt-and-suspenders), or
  route per-chunk (Headroom for prose chunks, digest+retrieval for structured/log chunks) — to
  maximize preservation without losing precision. Worth prototyping + measuring if it beats either
  alone.
- Should the router expose a `route recommend`-style advisory (RFC 039 verb) for compression, so an
  operator can see *why* a backend was chosen before it runs?

## Non-goals

Auto-installing Headroom; enabling auto-Headroom without measurement; inferring signals silently;
any network/daemon; changing the RTK-vs-native (content-type) split from RFC 037; replacing the
manual opt-in before the evidence gate opens.
