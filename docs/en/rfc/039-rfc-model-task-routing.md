# RFC 039 — CLI agent launching + model / task-type cost routing

- **Status:** draft (authored by Claude; for Codex review)
- **Builds on:** [032-rfc-tiered-delegation.md](032-rfc-tiered-delegation.md) (the delegation charter this operationalizes), [014-rfc-provider-management.md](014-rfc-provider-management.md) (provider registry + capability vocabulary + `providers render`), [028-rfc-headless-command-templates.md](028-rfc-headless-command-templates.md) + [020-rfc-headless-runner-hardening.md](020-rfc-headless-runner-hardening.md) (safe argv launch), [018-rfc-agent-runtime-architecture.md](018-rfc-agent-runtime-architecture.md) (roles / agent registry / run ledger), [008-rfc-worktree-companion.md](008-rfc-worktree-companion.md) (degree-2 isolation), [034-rfc-companion-adapter-interface.md](034-rfc-companion-adapter-interface.md) (hardened subprocess runner), [031-rfc-decision-traceability.md](031-rfc-decision-traceability.md) (decision record), [040-rfc-ai-session-usage-monitoring.md](040-rfc-ai-session-usage-monitoring.md) (usage/cooldown — the orthogonal cost axis).
- **Core invariant:** routing is an **advisory, degree-2 companion**. The passive, stdlib-only, degree-1 core (`m8shift.py`, the `LOCK`, `M8SHIFT.md`) never learns a model name, never scores a provider, and never gates `claim`/`append` on routing metadata. Removing `.m8shift/routing/` loses only recommendations, never the relay or its journal.

## 1. Problem

A pen-holder often decomposes a turn into sub-tasks of very different difficulty — a mechanical
rename, a search, a review, a design. Running every sub-task on the pen-holder's own flagship model
is capable but wasteful; running everything on the cheapest model is cheap but unsafe. RFC 032
established that a pen-holder may delegate sub-tasks to cheaper-tier sub-agents (as tools, holding no
core pen) and *verify before integrating* — but it left the actual **decision** open (its four open
questions): how is a tier expressed, what command launches a routed sub-agent, how is spend bounded,
and does the verifier need to be a different model family. RFC 039 answers those questions with a
concrete, provider-neutral, advisory routing layer.

The user's framing is the one-line objective: **pick the least-costly model that is still capable
enough for the task** — where *capable enough* is a hard gate and *least-costly* is the objective
within that gate.

## 2. Decision

Add an **advisory model/task routing companion**. It maps a **task-type** to a **capability floor**,
resolves the **cheapest capable-enough model** from an **operator-owned manifest**, and either prints
the recommendation (`route recommend`) or launches the chosen model as an isolated sub-agent
(`route delegate`) through the *existing* hardened headless machinery. **Selection is
capability-first: cost is the tie-breaker among capable-enough models, never a reason to drop below
the floor.** The human / pen-holder confirms; the decision is traceable (RFC 031); the sub-agent's
output is always verified before integration (RFC 032 §4).

## 3. Non-goals

- **No hidden auto-scoring.** RFC 014 §4 and RFC 018/034 already reject "automatic provider selection
  by hidden scoring." Routing **recommends**; the human/pen-holder **decides**. The companion never
  silently picks and runs a model without a recorded, confirmable decision.
- **No baked-in prices or vendor list.** The RFC ships *axes*, *ordinal tiers*, and a *schema*. Concrete
  models and their relative costs live in an operator-owned, gitignored manifest that is re-pointed as
  prices move — so the design survives every price change and model launch.
- **No core changes.** Nothing here touches `m8shift.py`, the `LOCK`, or the mutex. New verbs live in
  the runtime companion.
- **No second pen / no new launch path.** Sub-agents hold no core pen; only the pen-holder commits.
  Launching reuses RFC 028/020/014 verbatim — no new subprocess path.
- **No network requirement, no credentials in M8Shift files.**

## 4. How it answers RFC 032's open questions

| RFC 032 open question | RFC 039 answer |
|---|---|
| #1 How is a tier expressed (per-task field vs policy file vs judgment)? | Per task-type in a `skills.json` manifest: `min_model` (floor) + `optimum_model` + `downgradable`. |
| #2 Expose a `delegate` verb, or stay example-only? | Yes — a runtime-companion `route recommend | delegate` verb (never a core verb). |
| #3 How is spend bounded? | A capability-first, cheapest-eligible selection + an **optional** per-turn sub-agent budget gate (operator policy), reusing RFC 040 usage snapshots for the running total rather than a second cost meter. |
| #4 Same-family vs cross-provider verifier? | Provider-neutral by construction; an open question (§14) on whether `downgradable:false` tasks require a *different-family* verifier. |

## 5. Task-type taxonomy

Each task-type declares a capability **floor** and a bound **verify** recipe. Floors below are
*defaults* the operator tunes; the point is the ordering, not the exact assignment.

| Task-type | Nature | Floor → optimum | Downgradable |
|---|---|---|---|
| `mechanical-edit` | deterministic, byte-verifiable: rename, reformat, lint-fix, accent/typo pass, scaffold | economy → balanced | yes |
| `search-retrieval` | locate code/text, enumerate call-sites, gather references | economy → balanced | yes |
| `extract-classify` | structured extraction/tagging against a schema | economy → balanced | yes |
| `summarize-condense` | compress logs/turns/docs into a brief (feeds RFC 023/033); escalate if the summary is load-bearing evidence | economy → balanced | yes |
| `review-critique` | read a diff/text, report advisory findings a human triages | balanced → flagship | yes |
| `synthesis-authoring` | write new prose/code/design from intent, multi-constraint, cross-file | balanced → flagship | yes |
| `design-architecture` | RFC/spec/system design, trade-off reasoning | flagship → flagship | yes (rarely) |
| `adversarial-verify` / `security-review` | security, deadlock/edge-case, path/write/denylist bypass, tamper analysis | flagship → flagship | **no** |
| `legal-compliance-review` | maps to RFC 014 `legal_review` capability | flagship → flagship + human sign-off | **no** |
| `long-context-synthesis` | large-corpus reasoning | gated by the **context** axis, not tier alone | yes |
| `unknown` / unannotated | no assumable floor | **fail-safe → the pen-holder's own model** | n/a |

`adversarial-verify` is pinned to the strongest annotated tier and is **never** cost-downgraded: the
adversarial hunt is the authority before any APPROVE, and a cheaper hunter defeats the purpose (this
mirrors the maintainer's standing security-review rule).

## 6. Provider-neutral comparison framework

No vendor or dollar figure is baked into the RFC. Every model is scored on four **axes**:

| Axis | Meaning | Role |
|---|---|---|
| **capability** | ordinal competence tier (e.g. T0<T1<T2<T3) | the ONLY axis that gates eligibility (clears the floor) |
| **cost** | relative spend as an ordinal band (`$<$$<$$$<$$$$`), never absolute currency | the minimization objective / tie-breaker |
| **latency** | typical wall-clock per turn | tie-break; parallel fan-out feasibility |
| **context** | max input capacity class (`small<large<xlarge`) | a hard feasibility gate (a model that cannot fit the input is disqualified regardless of cost) |

Tiers are **ordinal and open** — an operator may add bands (`micro`, `frontier`); the selection math
needs only a total order, never a fixed count.

Concrete models live in an operator-owned, gitignored, stdlib-parseable manifest
`.m8shift/routing/models.json` (`schema: m8shift.routing.models.v1`). It reuses RFC 014's capability
vocabulary (`long_context`, `fast_review`, `run_tests`, `review`, `legal_review`, …). Prices/models
change ⇒ the operator edits this file; the design never encodes a model or a price.

```json
{
  "schema": "m8shift.routing.models.v1",
  "cost_basis": "operator-supplied relative bands; NOT currency; re-point as prices move",
  "updated": "2026-07-01T00:00:00Z",
  "models": [
    {"id": "MODEL_ECON", "provider": "PROVIDER_A", "tier": "economy",  "cost_band": "$",    "latency": "fast",   "context_class": "large",  "capabilities": ["read_repo"]},
    {"id": "MODEL_MID",  "provider": "PROVIDER_A", "tier": "balanced", "cost_band": "$$",   "latency": "medium", "context_class": "large",  "capabilities": ["read_repo","review","run_tests"]},
    {"id": "MODEL_TOP",  "provider": "PROVIDER_A", "tier": "flagship", "cost_band": "$$$$", "latency": "slow",   "context_class": "xlarge", "capabilities": ["read_repo","review","run_tests","legal_review"]}
  ]
}
```

## 7. Skill / task-type annotation

`.m8shift/routing/skills.json` (`schema: m8shift.routing.skills.v1`, host-local, gitignored,
advisory — never read by the core mutex). Each entry carries `min_model` (the floor — a bare **tier**
preferred for durability, or a model id), `optimum_model`, `downgradable`, `required_capabilities`
(RFC 014 vocabulary), `required_context_class`, a mandatory `verify` recipe, and `on_ambiguous`
(always `escalate_to_pen_holder`). A **missing** entry fails safe to the pen-holder's own model.

```json
{
  "schema": "m8shift.routing.skills.v1",
  "authority": "advisory",
  "default_on_missing": "escalate_to_pen_holder",
  "defaults": {"min_model": "balanced", "optimum_model": "flagship", "downgradable": true},
  "task_types": {
    "mechanical-edit":  {"min_model": "economy",  "optimum_model": "balanced", "downgradable": true,  "required_capabilities": ["read_repo"], "verify": ["byte-diff","build"]},
    "review-critique":  {"min_model": "balanced", "optimum_model": "flagship", "downgradable": true,  "required_capabilities": ["read_repo","review"], "verify": ["pen-holder triage"]},
    "adversarial-verify": {"min_model": "flagship", "optimum_model": "flagship", "downgradable": false, "required_capabilities": ["read_repo","review"], "required_context_class": "large", "verify": ["hunt is authority; findings reproduced vs source before integrate"]}
  }
}
```

The RFC ships **provider-neutral task-type defaults** only; the tier→model binding is entirely the
operator's (a shipped model binding would be a de-facto vendor opinion — forbidden by the
no-baked-in-list rule).

## 8. Selection algorithm (capability-first, cost tie-break, fail-safe)

1. Resolve `task-type → {floor tier, required_capabilities, required_context_class}` from `skills.json`.
2. `ELIGIBLE` = models with `tier ≥ floor` **and** `capabilities ⊇ required` **and** `context_class ≥ required`.
3. If `ELIGIBLE` is empty → **fail-safe**: recommend the **pen-holder's own model** (never relax the floor).
4. Among `ELIGIBLE`, pick the **least-costly** `cost_band`; break ties by `latency` per the task's time-tolerance.
5. Emit a **ranked, advisory** recommendation + rationale (floor, chosen tier, feasible set, `saved_vs`
   the pen-holder's flagship, `below_optimum` flag, the `verify` recipe, `authority: advisory`).

**Optional start-cheap-escalate** (operator opt-in, per task-type): begin at `min_model`; if the
bound verify gate fails, escalate one tier toward `optimum_model` and retry. Because a failed cheap
attempt pays twice, an `escalation-rate` telemetry field lets operators raise `min_model` for
task-types that escalate too often. For `downgradable:false` task-types, escalation is disabled — they
start and stay at `optimum`.

## 9. CLI launch surface

New advisory verbs in the runtime companion (`m8shift-runtime.py`), never in `m8shift.py`. They
**reuse** RFC 014 `providers render` (placeholder substitution only, no shell string), the RFC 020
hardened runner (argv-only, `--dry-run`, `--turn-timeout`, run ledger, no force-steal), and RFC 008
worktrees for isolation.

```bash
# 1) Recommend — read-only, advisory; never launches, never claims a pen
python3 m8shift-runtime.py route recommend --task-type mechanical-edit --input-tokens 12000 [--skill NAME] [--json]
#    → {"floor":"economy","optimum":"balanced","feasible":[...],"picked":"MODEL_ECON",
#       "picked_tier":"economy","below_optimum":true,"saved_vs":"MODEL_TOP",
#       "verify":["byte-diff","build"],"authority":"advisory"}

# 2) Delegate — recommend, then render argv (RFC 014) and run in an isolated worktree (RFC 008)
#    via the RFC 020 hardened runner; --dry-run prints the effective argv as JSON and launches nothing
python3 m8shift-runtime.py route delegate --task-type mechanical-edit \
  --prompt "Apply the rename across src/, no logic change" --worktree wt-rename --dry-run

# 3) The pen-holder VERIFIES the sub-agent output vs ground truth (tests/build/byte-diff)
# 4) Only the pen-holder commits, through the core pen, as its own turn (degree-1 unchanged)
```

**Chat-UI degradation (RFC 035):** `route delegate` assumes a headless runner. In a pure chat-UI
session with no runner, `route recommend` degrades to a **print-only** advisory that the human
executes by hand — stated explicitly so a chat-only operator is never stranded.

## 10. Provenance and telemetry

Every routed sub-task records, in the RFC 018 run ledger / `.m8shift/runtime/runs.jsonl` (advisory,
deletable): the sub-agent's `model` + version + resolved `tier`, the task-type's `floor`, the
`verify` outcome, and `saved_vs` the pen-holder's flagship. This lets an auditor confirm **no
below-floor model was used** and **that verify ran** — not merely which model was chosen. The
existing `Agent-Model:` provenance trailer (agents-guide §5) records the *executing* model on the
resulting commit; a future enhancement could auto-stamp it from the routing decision.

## 11. Hard rails (what keeps routing honest)

1. **The floor is inviolable** — a task annotated `min_model: balanced` never routes to economy.
2. **Verify-before-integrate is unconditional** (RFC 032 §4) — a cheaper sub-agent's output is always
   checked against ground truth before the pen-holder integrates. *Economy never starves verification.*
3. **`adversarial-verify` / security / legal are pinned** to the top tier, `downgradable:false`.
4. **Fail-safe on ambiguity** — unknown/unannotated/below-floor/ambiguous → the pen-holder's own model.
5. **Advisory + traceable** — routing recommends; the human decides; RFC 031 records model, why, who confirmed.

## 12. Charter boundary

A degree-2 companion, exactly like RFC 032 delegation and RFC 034's adapter interface. It never
touches the core, never becomes a second routing/mutex authority (sub-agents hold no core pen), never
auto-selects (advisory only), and never bakes prices/vendors into the design. Deleting
`.m8shift/routing/` costs only recommendations.

## 13. Security

Launching a routed sub-agent inherits the RFC 034 / RFC 020 hardened path: **argv arrays only** (no
shell string), resolved-path adapters where subprocess identity matters, **bounded** timeout /
stdout, **no credentials** in M8Shift files, **gitignored** sidecars, **no network requirement**, and
**no force-steal** of a valid lock. The implementing turn must carry an adversarial security review of
any new subprocess path before merge.

## 14. Open questions (for review)

1. **Budget altitude** (RFC 032 #3): advisory warn by default, opt-in fail-closed operator policy; reuse
   RFC 040 usage snapshots for the running total (not a second cost meter). Confirm.
2. **Tier/rank provenance**: keep `capability` ordinals operator-asserted (stdlib, network-free) with an
   optional evidence field + a staleness/timestamp warning, or offer a benchmark-import?
3. **Escalation economics**: for which task-types is start-cheap-and-escalate cheaper *in expectation*
   than starting at optimum? Drive it with per-task-type `escalation-rate` telemetry.
4. **Cross-provider verifier** (RFC 032 #4): should `downgradable:false` tasks require a *different-family*
   verifier (conflict-of-interest guard), or is the human pen-holder as final authority enough?
5. **Fail-safe identity**: where does the pen-holder's own model come from — active RFC 014 provider
   adapter, env, or explicit `--self`? Must be unambiguous so "escalate" never resolves cheaper.
6. **Manifest lint**: should a `doctor`-style lint **hard-fail** a skill whose floor references a tier no
   manifest model reaches, or warn only?
7. **RFC 040 interaction**: if the least-costly eligible model is in usage-cooldown, `route recommend`
   skips to the next eligible (still ≥ floor) and records the substitution in provenance. Confirm.
8. **Shipped defaults**: ship provider-neutral task-type defaults only, leaving every tier→model binding
   to the operator (avoid a de-facto vendor opinion). Confirm.

## 15. Recommendation

Adopt the advisory, capability-first routing companion: a task-type taxonomy with capability floors, a
provider-neutral axes+tiers comparison framework filled by an operator manifest, skill annotations
(`min`/`optimum`/`downgradable`), a fail-safe selection algorithm with cost as the tie-breaker, and a
`route recommend | delegate` verb that reuses the existing hardened launch machinery. Keep it
charter-pure: **advisory, degree-2, verify-before-integrate, no hidden auto-scoring, no baked-in
prices** — routing illuminates the cheapest capable-enough choice; the human decides and the decision
is traced.
