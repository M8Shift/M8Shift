# RFC 043 — Routing principle

- Status: draft (principle / design-only — introduces no behavior)
- Builds on: [RFC 033 Context economy](033-rfc-context-economy.md) (objective + the §9 verification floor), [RFC 034 Companion adapter interface](034-rfc-companion-adapter-interface.md) (argv-only, identity-pinned, output-capped runner + benchmark evidence gate), [RFC 014 Provider management](014-rfc-provider-management.md) (capability manifest + safe argv render)
- Related: [RFC 037 Agent context compression backends](037-rfc-agent-context-compression-backends.md), [RFC 039 Model/task routing](039-rfc-model-task-routing.md), [RFC 042 Compression backend routing](042-rfc-compression-backend-routing.md), [RFC 032 Capability-tiered sub-agent delegation](032-rfc-tiered-delegation.md) — the four **instances** this principle generalizes
- Date: 2026-07-02
- Origin: operator request (2026-07-02) for a unifying routing principle after the RFC 042 contradictory review showed each router re-derives the same skeleton

## Summary

M8Shift now has four routers — model selection (RFC 039), sub-agent tier delegation
(RFC 032), compression-backend family (RFC 037), and builtin-vs-Headroom within the
broad family (RFC 042) — and each **re-derives the same decision skeleton** from
scratch, which is how RFC 042 drifted into an apparently contradictory framing on
review. This RFC extracts that shared skeleton into **one canonical routing pipeline**
so every existing and future router is an *instance* of it rather than a fresh
re-derivation. It is **design-only**: it introduces **no new runtime behavior, no new
script, and no new schema**, makes **no measured claim of its own**, and is fully
reversible — deleting it changes nothing that ships. It does **not** override, restate,
or re-specify any instance RFC; those remain authoritative and unchanged. Where the
mapping below names an instance's signal role, it **points at the owning RFC section**
rather than copying that instance's thresholds, config keys, or flag names, so the
principle cannot drift out of sync with the routers it generalizes.

## Motivation

The same shape was invented four times, and the divergence is now a maintenance and
correctness hazard: RFC 042's review exposed that "size → Headroom" *reads* like the
rule until you recall RFC 037's family split and RFC 039's capability-first ordering,
which 042 assumes but does not restate. A future fifth router (e.g. a retrieval or a
verifier router) has nothing canonical to point at and will re-derive the skeleton a
fifth time, free to reorder the stages or weaken the fail-closed default by accident.
RFC 042 already says it applies "the same *capability-first, evidence-gated* routing
philosophy" as RFC 039 — **this RFC is that shared philosophy made canonical**, written
once, so routers reference a single pipeline and a single signal vocabulary instead of
each carrying a private copy.

## The normalized signal vocabulary

Every M8Shift router speaks the same small set of signals. Each is either a **hard gate**
(can disqualify a candidate outright) or **soft fitness** (ranks or amplifies, never
disqualifies alone).

| Signal | Kind | Meaning | Canonical rule |
|--------|------|---------|----------------|
| `feasibility / context-class` | **hard gate** | Can the candidate physically do the job — fit the input, be present, be pinned? | A candidate that cannot fit the input, or an absent / unpinned / identity-mismatched backend, is disqualified **regardless of cost**. |
| `capability-requirement` | **hard gate** | Does the candidate clear the task's capability floor + required capabilities? | Floor is **inviolable**; cost is never a reason to drop below it. |
| `access-mode` (`retrieve` vs `inline`) | **hard gate — *context/compression routers only*** | Can the eventual consumer fetch the raw by reference, or must it be inline? *(Not universal: it does not apply to model routing or delegation, where nothing is being compressed/delivered as a form.)* | `retrieve` keeps the low-cost default (no probed-fact loss where the raw stays retrievable — RFC 042) eligible; `inline` (no retrieval) opens the higher-fidelity regime. |
| `task-type` / `content-type` | soft fitness | What *kind* of work / content this is. | Selects a *family* or a starting fit — **never the sole determinant**; the real determinant (below) decides within the family. |
| `size` | soft fitness | Estimated tokens (proxy: bytes/4, advisory). | **A risk *amplifier*, not a standalone determinant.** Large *raises the stakes* of the access-mode / query-shape choice; it does **not** by itself select a backend. "Long → the expensive branch" is a misframing (RFC 042): long + retrieve + few-fact still routes to the cheap default. |
| `cost-band` / `latency` | soft fitness (tie-break) | Ordinal operator bands (`$<$$<$$$<$$$$`), never currency. | Breaks ties **among already-feasible, fit candidates only**. |

The single most-repeated mistake the vocabulary guards against is treating `size` or
`content-type` as a hard determinant. Both are context, not verdicts: the verdict comes
from feasibility + the real fitness determinant, in that order.

## The decision pipeline

Every router runs the same six stages, **in this order**. Reordering them is what
produces the drift this RFC exists to stop.

1. **FEASIBILITY GATE (hard disqualify).** Drop every candidate that cannot do the job:
   input it cannot fit, capability floor it cannot clear, a backend that is absent,
   unpinned, or whose resolved realpath + SHA-256 does not match its RFC 034 manifest
   identity. This runs **before cost is ever considered**. If the set empties, go
   straight to stage 6.
2. **FITNESS MATCH (real determinant).** Among the survivors, pick the best fit by the
   signal that *actually decides which one wins* — for a model, capability; for a
   compressor, retrieval capability + query shape — **not** by a proxy like content-type
   or raw size alone. This is where RFC 042's "route on the determinant, not the
   content-type" rule lives, generalized.
3. **COST TIE-BREAK.** Only among the fit-and-feasible, choose the cheapest cost-band,
   breaking further ties by latency. Cost is the *objective within the gate*, never a
   reason to re-admit a disqualified or unfit candidate.
4. **NON-DOWNGRADABLE GUARD.** Before committing, confirm the choice does not trade away
   a pinned capability. High-stakes work (adversarial-verify, security-review, legal)
   is `downgradable:false` and stays at its pinned tier; and **routing never emits a form
   that starves verification** — the retrievable raw must stay retained, authorized, and
   recoverable (RFC 033 §9). Economy never wins over correctness here.
5. **INSTANCE EVIDENCE / PROMOTION GATE (non-default branch only).** An instance's branch that
   departs from its safe default ships **only** behind that instance's **own** evidence — and the
   *kind* of evidence is **instance-owned, not universal**: for compression/adapters (037/042) a
   **measured** gate (real-token gain **and** output-equivalence, per the RFC 034 §8 benchmark); for
   model routing (039) operator-asserted capability ordinals + staleness + a **verify-before-integrate
   output** gate (no real-token concept); for delegation (032) **verify-before-integrate** against
   ground truth (no measured branch gate at all). In every case it is **version-gated**, and a
   directional pilot is not proof — it does not open the gate.
6. **FAIL-CLOSED DEFAULT.** On any unknown, absent, errored, or unpinned signal — or an empty
   eligible set — degrade to **the instance's own safe default**, never a guessed cheap candidate.
   That default is instance-specific, **not** a universal "raw stays retrievable": for
   compression/context (037/042) builtin+retrieval or reference-only *while the raw stays
   retained/authorized/retrievable* (no probed-fact loss while retrieval is intact — RFC 033 §9), and
   never the un-redacted raw blob; for model routing (039) the pen-holder's own model / manual /
   launch nothing; for delegation (032) integrate **no** unverified output. The default is the floor
   of correctness, not a convenience.

## Instance mapping

The principle is real, not invented, because all four routers already implement it — they
differ only in *what* is being routed. This table names the **signal role** each instance
fills at every stage and **points at the owning RFC** for the concrete thresholds, config
keys, and flag names; those specifics live in and are governed by the instance RFC, never
copied here (so this table cannot fall out of sync when an instance changes its numbers).

| RFC (instance) | Feasibility gate | Fitness determinant | Cost tie-break | Evidence gate | Fail-closed default |
|----------------|------------------|---------------------|----------------|---------------|---------------------|
| **037** compression family | backend identity-pin present/matched; oversized-input refuse threshold; never-compress content classes (RFC 037 §config) | content-type selects family (shell/tool vs broad); extended-context backend only if pinned | deterministic per type; size ladder trades richness for reference-only (RFC 037) | measured (real-tokenizer gain + output-equivalence) **for any claimed gain / promotion / defaulting**; explicit/configured experiments still allowed behind pin + fail-closed (RFC 037) | reference-only output (path + digest, zero inline); default backend + redact-before-store forced (RFC 037 §config) |
| **039** model / task-type | tier floor **AND** required capabilities **AND** required context-class (RFC 039) | capability-first (floor is the only eligibility axis) | cheapest cost-band among eligible, then latency | **output gate** — operator-asserted ordinals + staleness on *selection*; the empirical gate is verify-before-integrate on *output* | pen-holder's own model by strict precedence; launch nothing; floor never relaxed |
| **042** builtin vs Headroom | Headroom installed + pinned + offline-safe; short ctx → builtin (RFC 042) | retrieval capability + query shape (the *determinant*, not content-type) | token efficiency, **subordinate** to preservation+precision | **measured** — auto-route-to-Headroom gated behind its operator gate + pin + version gate (RFC 042 Phase D) | builtin + retrieval (comparable, no probed-fact loss while the raw stays retrievable) |
| **032** delegation charter *(+ 039 operationalization)* | architectural charter: no sub-agent touches LOCK/M8SHIFT.md; worktree-only parallel writes; verify-before-integrate; provenance (RFC 032). Tier/cost/`downgradable:false` mechanics are **039's operationalization of 032**, not 032 itself | tier matched to task difficulty, operator/orchestrator-chosen *(via 039)* | advisory budget *(via 039/040: WARN default; opt-in fail-closed, RFC 040 snapshots)* | **output gate** — mandatory verify-before-integrate against ground truth (tests/build/byte diffs), ledger-recorded; **no measured branch gate** | integrate no unverified output; delegation absence never loses mutex/log |

Two honest asymmetries the table preserves rather than papering over. First, the *evidence*
axis is not uniform: RFC 042 carries a **measured** gate (real-token gain + output-equivalence) on
the non-default branch itself, and RFC 037 carries a measured gate **for any claimed gain /
promotion / defaulting** — while explicit, configured experiments stay allowed behind pin +
fail-closed. RFC 039 and RFC 032 instead gate on **output** — via verify-before-integrate against
ground truth — not on the selection. (RFC 032 in particular has *no* measured/benchmark gate at all;
its only gate is the output check before integration, structurally the same shape as RFC 039's.)
Second, RFC 039's model-eligibility rests on **operator-asserted** ordinals rather than a measured
selection gate. The principle accommodates all of these: the evidence/promotion gate applies wherever
a non-default branch exists, and its *kind* is owned by the instance — where a *measured* branch gate
is not available the branch relies on the output gate and stays design-only / advisory until it firms.

## Reuse of shared substrate

A router that follows this principle **SHOULD reuse** (rather than re-derive) — as design guidance, not a mandate; the instance RFCs remain authoritative:

- **RFC 034** — the argv-only, identity-pinned, env-allowlisted, output-capped,
  timeout-bounded `run_adapter_process()` runner as the *only* way to launch a chosen
  backend/model CLI, plus its `--require-real-tokens` benchmark as the stage-5 promotion gate
  **for compression/adapter branches** (the measured-evidence path; model/delegation branches use
  their own output gate instead). No new subprocess path.
- **RFC 033** — the "cheapest still capable-enough" objective (stages 2–3) and the §9
  verification floor (stage 4). No new budget model.
- **RFC 014** — the provider/capability manifest as the candidate registry + feasibility
  descriptors (stage 1), and its `argv` / `argv_by_platform` arrays convention (argv arrays,
  not shell strings) for safe launch. No new
  capability vocabulary.

None of the three is itself a router (each explicitly disclaims auto-selection); they are,
respectively, the policy + floor, the execution + evidence boundary, and the capability
model. This RFC supplies only the **decision shape** that composes them.

## Charter

stdlib-only · advisory (routers recommend; the human/pen-holder decides — no hidden
auto-scoring) · no network / no daemon / no persistent process · **fail-closed** on any
unknown/absent/errored/unpinned signal · **identity-pinned adapters only** (RFC 034;
renamed/wrapped/symlink-hijacked binaries fail closed) · the passive stdlib-only degree-1
core (`m8shift.py`, the LOCK, `M8SHIFT.md`) never learns a model name, scores a provider,
or gates `claim`/`append` on routing metadata · **routing never starves verification**
(RFC 033 §9): the retrievable raw is the safety net and a pinned non-downgradable
capability such as adversarial-verify is never traded for cost.

## Non-goals

- **No auto-installing tools** — a router never fetches/installs a backend; absent means
  fail-closed.
- **No new runtime** — no new script, schema, subprocess path, budget model, or capability
  vocabulary; only the reuse of existing substrate.
- **Does NOT override or restate the instance RFCs** — 037/039/042/032 remain
  authoritative; this RFC references (by pointer, not copy), it does not re-specify, and it
  carries no private copy of their thresholds or flag names.
- **No hidden auto-scoring / no automatic model or backend selection** — the manifest
  describes, a companion recommends, the human confirms.
- **No cross-vendor identity crypto** — identity-pinning is local realpath + SHA-256 per
  RFC 034, nothing more.

## Relationship

RFC 042 states it applies "the same *capability-first, evidence-gated* routing philosophy"
as RFC 039. **This RFC is that shared philosophy, extracted and made canonical.**
RFC 037/039/042/032 stay exactly as they are — the four instances — and this document adds
nothing to their behavior; it only gives them (and any future router) a single skeleton to
point at. It sits *beside*, not *above*, the instances: a principle they already satisfy,
not a new constraint imposed on them.

## Acceptance criteria

1. The signal vocabulary and six-stage pipeline are specified once, with `size` and
   `content-type` explicitly classed as soft (amplifier / family), feasibility + capability as
   **universal** hard gates, and `access-mode` as a hard gate **scoped to context/compression routers**.
2. The instance-mapping table shows all four routers (037/039/042/032) as instances by
   **signal role + pointer to the owning RFC**, with no literal threshold/config/flag
   copied, and states the honest evidence-gate asymmetry correctly (042 measured branch gate;
   037 measured gate for claims/promotion/defaulting; 039/032 output gate; 032 carries no
   measured gate).
3. The RFC introduces no behavior, no script, no schema; deleting it changes nothing that
   ships (design-only, reversible).
4. It makes no measured claim of its own and points every empirical claim back to the
   instance RFC and RFC 034's benchmark gate; it asserts no general no-loss property,
   only "no probed-fact loss where the raw stays retrievable" per RFC 042/033.
5. It restates no instance RFC's rules as normative here; conflicts are resolved in favor
   of the instance.

## Open questions

- Should M8Shift ship a shared `route recommend`-style advisory **library** (read-only,
  stdlib) that all routers call, so the six stages exist in one place in code and not just
  in prose — or does a shared library risk becoming the "second routing authority" the
  charter forbids? **If ever built it must be explain-only / read-only: no `claim`/`append`/LOCK
  mutation, no subprocess launch, no hidden auto-selection — it emits *rationale, not authority*,
  and the instance RFCs remain authoritative.**
- Per-router **adoption order**: do we retrofit the existing four to cite this principle
  opt-in (039 first, since it is the reference philosophy), or leave them untouched and
  only bind future routers to it?
- Is stage 4 (non-downgradable guard) better expressed as a **shared registry** of
  `downgradable:false` capabilities that every router consults, rather than each router
  re-declaring its own?
- Should the evidence gate (stage 5) define a **canonical minimum** (N, regimes, real-token
  + output-equivalence) that any non-default branch must clear, or stay per-instance?
- **[drift guard]** Should each signal in the normalized vocabulary declare **which router families
  it applies to**, so compression-only signals (`access-mode`, raw-retrieval) are not accidentally
  treated as universal model/delegation signals? *(This is the exact drift RFC 043's own first draft
  fell into — the review caught compression assumptions leaking into the universal pipeline.)*