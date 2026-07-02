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
automatically, and **gates the "auto-route to Headroom" branch behind measured evidence** (the
Round 3 pilot only measured the regime where builtin wins).

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

| Signal | Route to | Why |
|--------|----------|-----|
| Consumer **can retrieve** raw **and** queries touch **a few facts** | **builtin (digest + retrieval)** | tiny digest + fetch-on-demand → far fewer tokens at tied completeness |
| **No retrieval** (one-shot handoff, external agent, raw not kept) | **Headroom** *(if enabled + pinned)* | digest-alone is near-useless; Headroom's near-lossless output preserves in-place |
| Task needs **most of the content at once**, or **many rapid facts** | **Headroom** *(if enabled + pinned)* | avoids many retrieval round-trips |
| Any signal unknown / Headroom absent / unpinned / errored | **builtin** (fail-closed) | never worse than today's default |

Note: content-type (shell/tool vs broad) still selects the RTK vs native *family* as in RFC 037;
this RFC adds the builtin-vs-Headroom choice *within* the broad family, on the retrieval/query
determinant.

## Routing signal

The determinant is supplied to `compress` as explicit, advisory hints (defaulting to the safe,
common case), never inferred silently:

- `--access-mode retrieve|inline` (default `retrieve`) — can the eventual consumer of this context
  fetch the raw by reference? `retrieve` ⇒ builtin is eligible; `inline` (no retrieval) ⇒ Headroom
  regime.
- `--whole-content` (default off) — the consumer needs most of the content at once (not a few
  facts) ⇒ Headroom regime.
- Callers that know their consumer set these (e.g. a one-shot handoff to an external agent →
  `--access-mode inline`; a local relay handoff → `retrieve`). Absent hints ⇒ `retrieve` +
  few-facts ⇒ builtin. **The common M8Shift path stays builtin with zero configuration.**

## Evidence gate (do not route on a hypothesis)

**Auto-routing to Headroom stays DISABLED until:** (a) the no-retrieval / whole-content regimes are
**measured** (the full rigorous benchmark, #84) and confirm Headroom wins there under the DoD
(real-tokenizer gain **and** equivalence), **and** (b) Headroom is identity-pinned (RFC 034). Until
both hold, the router behaves exactly as v3.40.0: builtin default, Headroom only via explicit
`--backend headroom_ext` or the manual `auto_enabled` opt-in. This RFC specifies the *mechanism*; it
does not flip auto-Headroom on.

## Charter

stdlib-only · advisory · no network/daemon (Headroom runs only via the RFC 034 argv-only,
identity-pinned, output-capped runner) · **fail-closed to builtin** on any unknown signal, absent /
unpinned / errored Headroom, or config problem. Redaction-before-store and "compression never
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
- Should the router expose a `route recommend`-style advisory (RFC 039 verb) for compression, so an
  operator can see *why* a backend was chosen before it runs?

## Non-goals

Auto-installing Headroom; enabling auto-Headroom without measurement; inferring signals silently;
any network/daemon; changing the RTK-vs-native (content-type) split from RFC 037; replacing the
manual opt-in before the evidence gate opens.
