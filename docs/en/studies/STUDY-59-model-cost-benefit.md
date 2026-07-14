# Study 59 — Codex and Claude model cost/benefit routing

**Status:** integrated draft for final arithmetic and fact review

**Market snapshot:** 2026-07-14

**Decision target:** minimize subscription headroom per accepted result while
meeting the task's efficacy and risk bar, under the actual constraint of
weekly-capped CLI subscriptions.

## 1. Executive summary

1. Optimize subscription headroom per accepted result, not API dollars per call.
   Track tokens consumed, retries, verification, and acceptance; leave the
   vendor-specific conversion from tokens to weekly-limit burn unknown.
2. Published efficacy is harness-conditioned. The same model can move by more
   than 15 points between agent scaffolds, so report ranges with their harnesses
   and treat the M8Shift prompt/tool/verification loop as part of the route.
3. Use a small/fast model at modest reasoning for deterministic, reversible work;
   escalate on ambiguity, failed acceptance, broad context, or high consequence.
4. For ordinary implementation and documentation, prefer the balanced tier:
   Codex `gpt-5.6-terra` or Claude Sonnet 5. Use the frontier tier for design,
   high-risk review, difficult debugging, and final adversarial verification,
   but mark efficacy for Terra and Sonnet 5 as unbenchmarked.
5. Use a long-context Claude route when the job cannot fit the 272k context
   envelope exposed by this Codex runtime. Do not treat a catalog maximum as a
   context size usable in the current session.
6. A cheap implementer plus a stronger reviewer is economical only when review is
   actually required or materially reduces miss risk. Mandatory full review can
   erase the cheap primary's apparent saving.
7. API prices below are a reproducible relative-cost comparison layer. They are
   not a conversion to subscription headroom, and API availability does not prove
   that a model is selectable in either CLI subscription.

## 2. Evidence, scope, and unknowns

Evidence classes used throughout:

- **Sourced fact:** an official vendor page captured on 2026-07-14, with a URL
  in the source ledger.
- **Runtime observation:** exact metadata offered to Codex CLI 0.144.3 by its
  service catalog, fetched at `2026-07-14T01:23:21.869788Z`. This establishes
  current local selectability, not public rollout.
- **Sourced observation:** a third-party benchmark or account-specific product
  observation, dated and labeled with its harness or scope. It is evidence, not
  a universal vendor guarantee.
- **Judgment:** a routing recommendation derived from the facts and explicit
  assumptions. It is not a vendor capability claim.

Included are the current Claude family supplied from official Anthropic pages,
the OpenAI API pricing rows supplied from the official OpenAI pricing page, and
the models visible in the dated local Codex catalog. Prices are USD per one
million tokens, standard API tier, before tax unless stated otherwise.

Material unknowns are deliberately not filled from memory:

- Exact token conversion and per-model weighting for either vendor's weekly
  subscription limit: **UNKNOWN / unpublished**.
- Explicit public OpenAI context and output limits for the priced API rows:
  **UNKNOWN**. The API pricing page distinguishes short and long context but the
  captured page did not state token counts.
- Anthropic prompt-cache and Batch prices: **UNKNOWN in this snapshot**.
- Cross-vendor quality, latency, and effort equivalence on the same task and
  harness: **not established**. Section 3.4 supplies conditional coding signals,
  not a universal ranking.

No M8Shift-controlled micro-benchmark was run. Third-party coding benchmarks are
included as priors, but their harness spread is evidence that they cannot replace
task acceptance. Invoking extra tiers would consume the weekly resource the study
is intended to conserve; run a later fixture only for a genuinely uncertain,
decision-relevant minimum-adequate boundary.

## 3. Inventory

### 3.1 Claude: official product/API facts

| Model | Exact API ID | Input | Output | Context | Max output | Positioning / constraint |
|---|---|---:|---:|---:|---:|---|
| Fable 5 | `claude-fable-5` | $10 | $50 | 1M | 128k | Most capable widely released; slower; adaptive thinking always on |
| Opus 4.8 | `claude-opus-4-8` | $5 | $25 | 1M | 128k | Complex agentic coding; moderate latency; effort defaults high |
| Sonnet 5 | `claude-sonnet-5` | $3 | $15 | 1M | 128k | Fast speed/intelligence balance |
| Sonnet 5, introductory | same | $2 | $10 | 1M | 128k | Temporary price through 2026-08-31 |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | $1 | $5 | 200k | 64k | Fastest, lower-cost tier; extended thinking supported |
| Mythos 5 | `claude-mythos-5` | = Fable 5 | = Fable 5 | = Fable 5 | = Fable 5 | Invitation-only defensive-cyber program; not GA |

Claude reasoning efforts are `low`, `medium`, `high`, and `xhigh`. Opus 4.8 and
Sonnet 5 default to `high` in the cited Claude Code/API description. Matching
effort names across vendors do not establish matching computation or quality.

Claude subscription facts: Free is $0; Pro is $17/month with annual billing or
$20 month-to-month; Max starts at $100/month; Team is $20/seat standard or
$100/seat premium; Enterprise is $20/seat plus API-rate usage. The pricing page
states that usage limits apply. Exact weekly weights are not published.

### 3.2 OpenAI: official API comparison rows

| Model ID | Input | Cached input | Output | Public evidence in this snapshot |
|---|---:|---:|---:|---|
| `gpt-5.3-codex` | $1.75 | $0.175 | $14 | Official API pricing row; priority is $3.50 / $0.35 / $28 |
| `gpt-5.6-sol` | $5 | $0.50 | $30 | Official API pricing row |
| `gpt-5.6-terra` | $2.50 | $0.25 | $15 | Official API pricing row |
| `gpt-5.6-luna` | $1 | $0.10 | $6 | Official API pricing row |
| `gpt-5.5-pro` | $30 | — | $180 | Official API pricing row |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 | Official API pricing row |
| `gpt-5.4-nano` | $0.20 | $0.02 | $1.25 | Official API pricing row |

Regional-processing endpoints add 10% for models released on or after
2026-03-05. The captured API page calls `gpt-5.3-codex` the Codex CLI model, but
that slug was not present in the current local selectable catalog. Treat the
official row as an API/product fact and current local selectability as unknown.

ChatGPT/Codex subscription facts: the Codex CLI is free software and consumes the
allowance of the connected ChatGPT plan rather than a separate Codex
subscription. The captured Codex pricing page lists Free at $0, Go at $8, Plus at
$20, Pro at $100 for 5x or $200 for 20x, Business at $25/user/month, and
Enterprise as custom. The supplied pricing capture reports token-based accounting
since 2026-04-02 and vendor estimate ranges rather than fixed public caps. These
plan prices establish the subscription basis, not a token-to-weekly-percent
conversion.

General Codex documentation describes a five-hour rolling window plus a weekly
cap. This operator's account has instead exposed **weekly-only** limits since
approximately 2026-07-12 in both the `account/rateLimits/read` response and the
ChatGPT usage UI (no five-hour bucket, only weekly usage and reset credits). This
direct, account-specific observation governs routing here. The mismatch is a
product reliability finding and may reflect tier or rollout differences; do not
generalize it to other accounts.

### 3.3 Codex: dated local runtime inventory

| Local slug | Current runtime context / catalog maximum | Default effort | Supported efforts | Reconciliation |
|---|---:|---|---|---|
| `gpt-5.6-sol` | 272k / 272k | low | low, medium, high, xhigh, max, ultra | Matches an official API pricing row |
| `gpt-5.6-terra` | 272k / 272k | medium | low, medium, high, xhigh, max, ultra | Matches an official API pricing row |
| `gpt-5.6-luna` | 272k / 272k | medium | low, medium, high, xhigh, max | Matches an official API pricing row |
| `gpt-5.5` | 272k / 272k | medium | low, medium, high, xhigh | Do not substitute the priced `gpt-5.5-pro` row |
| `gpt-5.4` | 272k / 1M | medium | low, medium, high, xhigh | Local runtime envelope is 272k; no exact public price captured |
| `gpt-5.4-mini` | 272k / 272k | medium | low, medium, high, xhigh | Matches an official API pricing row |
| `gpt-5.3-codex-spark` | 128k / 128k | high | low, medium, high, xhigh | Product-only/runtime observation; `supported_in_api=false` |

All entries report an effective context-window percentage of 95. That is a
runtime envelope/truncation datum, not a vendor claim that the API withholds 5%.
The catalog's hidden `codex-auto-review` metadata is excluded because it is not
established as a user-selectable route.

The local catalog describes Sol as frontier, Terra as balanced, Luna as fast and
affordable, GPT-5.4 as strong for everyday coding, Mini as small/fast, and Spark
as ultra-fast. These descriptions are runtime observations. Sol/Terra advertise
a fast service tier at 1.5x speed with increased usage, but no headroom multiplier
is documented. Service tier and reasoning effort remain independent controls.

The benchmark capture describes `gpt-5.3-codex` as deprecated in Codex and says
OpenAI recommends general `gpt-5.5`; the absent local slug is consistent with
that report but does not identify the model used by an arbitrary invocation.
Record the actual runtime model slug for each measured turn rather than mapping a
legacy benchmark score onto Sol, Terra, Luna, or GPT-5.5.

### 3.4 Coding efficacy: ranges, harnesses, and gaps

Raw price is not a decision metric without efficacy on the same task. A route
that is five times cheaper per run but causes ten times the retries or missed
acceptance checks is more expensive per accepted result. The operative rule is:
choose the cheapest route whose observed efficacy clears the task's acceptance
bar, then upgrade when the reduction in retry, rework, or consequence risk is
worth more than the added headroom.

The available third-party evidence is conditional and coding-specific:

| Model | SWE-bench Verified (Python-only) | SWE-bench Pro (4 languages, contamination-resistant) | Interpretation |
|---|---:|---:|---|
| Claude Fable 5 | about 95.0%; one sourced tracker, range unavailable | 80.3%; one sourced harness | Strongest buyable Claude signal in this capture; single-harness points are not ranges |
| Claude Opus 4.8 | about 80.8% across some trackers to 88.6% with Anthropic's harness | about 51.9% in Scale SEAL to 69.2% with Anthropic's harness | The 7.8-point Verified and 17.3-point Pro spreads demonstrate scaffold sensitivity |
| GPT-5.5 | 88.7% OpenAI-reported; range unavailable | not captured | Local `gpt-5.5` exists, but `gpt-5.5-pro` pricing must not be substituted |
| `gpt-5.3-codex` | about 85.0% third-party; range unavailable | 41.0% in Scale's standardized harness to 56.8% at xhigh in the reported model harness | The 15.8-point Pro spread is the clearest harness warning; the slug is not locally selectable |
| Claude Sonnet 5 | **UNKNOWN** | **UNKNOWN** | Trackers still list Sonnet 4.6 (79.6% Verified); do not transfer that score to Sonnet 5 |
| Claude Haiku 4.5 | about 73.3%, reported as varying but without a captured numeric range | not captured | Budget-tier coding prior only |
| Claude Mythos 5 | 95.5%; one sourced tracker | not captured | Invitation-only; excluded from ordinary routing |

SWE-bench Verified covers Python only. SWE-bench Pro covers four languages and is
designed to resist contamination, so prefer Pro where it exists. Neither suite
measures documentation, research synthesis, security review, long-context
retention, or this repository's exact acceptance contract.

Most importantly, trackers disagree by **harness**, not merely by model. In the
captured Pro evidence, `gpt-5.3-codex` moves from 41.0% to 56.8% when the scaffold
changes. The practical finding is that agent tooling can move results more than a
model swap. Report the range and harness together; never present one point as an
intrinsic model capability.

## 4. Subscription-first cost model

Let `I`, `C`, and `O` be uncached input, cached input, and output tokens for a
route, including every agent invocation.

The directly measurable subscription quantity is:

```text
raw tokens = I + C + O
```

For weekly planning, use this conservative envelope:

```text
planned tokens = 1.25 * (primary raw tokens
                       + maximum allowed retry raw tokens
                       + required verifier raw tokens)
```

The 25% factor is a **planning assumption**, not a vendor fact or a model-weight
estimate. It covers ordinary prompt/tool variance; budgeting the full permitted
retry and required verifier is the main conservative bound. If observed usage
exceeds the envelope, replace 25% with the measured percentile. Never translate
planned tokens into a weekly percentage without a published or measured
plan-specific conversion.

The comparison-only API formula is:

```text
API proxy dollars = (I * input_rate
                   + C * cached_input_rate
                   + O * output_rate) / 1,000,000
```

For a route with a retry probability `q` and mandatory verifier cost `V`:

```text
expected API proxy per accepted result = primary_cost + q * retry_cost + V
```

API proxy dollars indicate relative token weighting under published API rates.
They are not actual M8Shift spend and are not proof of weekly-limit weighting.
Estimate `q` from accepted outcomes on comparable tasks and the same harness.
Benchmark efficacy is only a prior: it cannot be inserted directly as `1-q`.

Planning token bands used in the matrix are judgments, after the 25% margin:
XS <= 25k; S <= 100k; M <= 300k; L <= 1M; XL > 1M. The band is a workload
envelope, not a model price or quality score.

## 5. Worked arithmetic

### 5.1 Same 100k-input / 10k-output call, no cache

| Route | Arithmetic | API proxy |
|---|---|---:|
| GPT-5.4 Mini | `0.1*$0.75 + 0.01*$4.50` | $0.120 |
| GPT-5.6 Luna | `0.1*$1 + 0.01*$6` | $0.160 |
| GPT-5.3 Codex | `0.1*$1.75 + 0.01*$14` | $0.315 |
| GPT-5.6 Terra | `0.1*$2.50 + 0.01*$15` | $0.400 |
| GPT-5.6 Sol | `0.1*$5 + 0.01*$30` | $0.800 |
| Claude Haiku 4.5 | `0.1*$1 + 0.01*$5` | $0.150 |
| Claude Sonnet 5, introductory | `0.1*$2 + 0.01*$10` | $0.300 |
| Claude Sonnet 5, standard | `0.1*$3 + 0.01*$15` | $0.450 |
| Claude Opus 4.8 | `0.1*$5 + 0.01*$25` | $0.750 |
| Claude Fable 5 | `0.1*$10 + 0.01*$50` | $1.500 |

The call consumes 110k raw tokens regardless of its API proxy. With one full
retry allowed and no verifier, its conservative subscription envelope is
`1.25 * (110k + 110k) = 275k` planned tokens. The actual weekly burn can still
differ by model because vendor weights are unknown.

### 5.2 Cached repeated context

For 20k uncached input, 80k cached input, and 2k output:

| Route | Arithmetic | API proxy |
|---|---|---:|
| GPT-5.4 Mini | `0.02*$0.75 + 0.08*$0.075 + 0.002*$4.50` | $0.030 |
| GPT-5.6 Luna | `0.02*$1 + 0.08*$0.10 + 0.002*$6` | $0.040 |
| GPT-5.3 Codex | `0.02*$1.75 + 0.08*$0.175 + 0.002*$14` | $0.077 |
| GPT-5.6 Terra | `0.02*$2.50 + 0.08*$0.25 + 0.002*$15` | $0.100 |
| GPT-5.6 Sol | `0.02*$5 + 0.08*$0.50 + 0.002*$30` | $0.200 |

The API discount is visible, but subscription planning still counts all 102k
tokens because cached-token treatment against weekly limits is undocumented.

### 5.3 Retry and verifier break-even

On the 100k/10k fixture, Mini primary plus a Terra retry with probability `q`
has proxy cost `0.120 + q*0.400`. Terra primary alone is $0.400. Mini-first is
cheaper while `q < ($0.400-$0.120)/$0.400 = 0.70`. This is a price threshold,
not evidence that Mini succeeds at any particular rate.

If every Mini result requires a full Terra verification call, the route is
`$0.120 + $0.400 = $0.520`, already above Terra alone before rework. Therefore
use cheap-primary/strong-verifier for risk reduction, not by assuming it always
saves headroom.

## 6. Task-to-model routing matrix

Every recommendation in this section is a **judgment** pending controlled
observations. “Minimum” means the first route worth trying for a bounded fixture,
not the cheapest listed model. “Preferred” includes reliability and rework risk.
The section 3.4 signals support the broad budget/frontier prior for coding but do
not score current Sol, Terra, Luna, Mini, or Sonnet 5. Those efficacy gaps stay
explicit: acceptance checks, not tier labels, decide adequacy.

| Task class | Risk / token band | Minimum Codex | Minimum Claude | Preferred primary | Verify / escalate when |
|---|---|---|---|---|---|
| Trivial mechanical | low, XS | Mini low; Luna low | Haiku low | deterministic tool first, then Mini/Haiku | output differs from deterministic check, scope expands, or files are security/release critical |
| Documentation edit | low-medium, S | Luna medium | Haiku medium | Terra medium or Sonnet medium | facts require sourcing, terminology is normative, or cross-file consistency fails |
| Code review | medium-high, S-M | Terra high | Sonnet high | Sol high or Opus high for consequential diffs | security, auth, concurrency, destructive state, or disagreement -> opposite-vendor frontier reviewer |
| Complex reasoning/design | high, M | Terra high | Sonnet high | Sol xhigh or Opus/Fable high-xhigh | unresolved tradeoff, novel trust boundary, or normative protocol impact -> adversarial peer review |
| Long-context refactor | high, L-XL | Terra/Sol only if <=272k runtime envelope | Sonnet/Opus high | Claude 1M-context route when >272k; otherwise strongest locally adequate route | context truncation, cross-cutting invariants, generated copies, or >1M -> decompose with explicit map |
| Research/synthesis | medium-high, M-L | Terra high | Sonnet high | balanced model with official-source tools; frontier for conflicting evidence | missing primary sources, temporal claims, or unresolved contradictions -> source-owner peer review |
| Adversarial verification | high, S-M | Sol high-xhigh | Opus/Fable high-xhigh | different-vendor strong reviewer, independent evidence path | any material disagreement -> preserve both findings and obtain human decision |

Mythos 5 is excluded from ordinary routing because it is invitation-only and not
GA. Spark is excluded as a default because its 128k context and product-only
status are material constraints; it may be tested later for bounded mechanical
work. GPT-5.4 Nano is priced publicly but was not exposed in the local catalog,
so it is not a current Codex subscription route.

The minimum-adequate calls above are grounded by these acceptance gates:

| Task group | Available efficacy signal | Minimum acceptance bar |
|---|---|---|
| Mechanical work | Coding benchmarks are unnecessary and weakly relevant | Deterministic diff/check exactly passes; otherwise escalate |
| Implementation and debugging | Pro gives strong reported signals for Fable/Opus, but the cross-harness ranking is uncontrolled and current Codex/Sonnet 5 scores are unknown | Project tests and scoped invariants pass with no unexplained change; retry or escalate on first material failure |
| Code/security review | No cited suite measures review recall or security findings | Independent evidence covers every risk surface; high consequence requires a strong opposite-vendor reviewer |
| Documentation/research | No same-task efficacy evidence captured | Sources resolve every material factual claim and cross-file consistency passes |
| Long-context work | Context limits are sourced; retention efficacy is not | Context map proves coverage with no truncation; decompose or escalate on omission |

Thus Mini/Haiku-first is justified only where deterministic acceptance makes a
failed cheap attempt inexpensive and visible. Frontier-first is justified where
misses are costly, acceptance is weak, or the captured coding prior and risk both
favor stronger scaffolding. A price ratio alone never establishes either route.

## 7. M8Shift co-shift playbook

### Pattern A — deterministic executor

- **Use for:** checksums, exact renames, formatting, generated-copy sync.
- **Primary:** a deterministic tool; Mini/Luna low or Haiku low only for the
  orchestration text.
- **Artifact:** command, exact diff, and deterministic verification result.
- **Stop/escalate:** any ambiguous semantic change or failed invariant.

### Pattern B — balanced implementer, frontier reviewer

- **Use for:** normal code/docs with meaningful but bounded risk.
- **Primary:** Terra medium-high or Sonnet medium-high.
- **Reviewer:** Sol/Opus high, preferably from the other vendor, only when the
  consequence or acceptance contract warrants it.
- **Artifact:** scoped diff, tests, assumptions, and identified risk surfaces.
- **Stop/escalate:** review disagreement, missing source, or failed test.

### Pattern C — strong designer, economical executor

- **Use for:** architecture or protocol decisions followed by mechanical work.
- **Designer:** Sol xhigh or Opus/Fable high-xhigh.
- **Executor:** Terra/Luna or Sonnet/Haiku at the lowest tier that preserves the
  approved design.
- **Artifact:** decision record with invariants and acceptance criteria.
- **Stop/escalate:** executor discovers an unmade design decision.

### Pattern D — long-context specialist

- **Use for:** a coherent input above the 272k current Codex envelope.
- **Primary:** Claude Sonnet/Opus with the cited 1M context, chosen by risk.
- **Reviewer:** a compact mapped summary can be reviewed by Codex; do not claim
  that review covered omitted raw context.
- **Artifact:** context map, included/omitted ranges, and invariant ledger.
- **Stop/escalate:** input exceeds 1M or critical evidence cannot be retained.

### Pattern E — asymmetric adversarial verification

- **Use for:** security, releases, destructive operations, relay correctness,
  and high-consequence factual reports.
- **Primary/reviewer:** different vendors and independent evidence paths; strong
  tiers at high or above.
- **Artifact:** raw proof references and explicit agreement/disagreement.
- **Stop/escalate:** unresolved disagreement goes to the operator; never average
  contradictory conclusions.

Model self-declaration is provenance only. It is not authorization, proof of
capability, or permission to bypass the relay pen.

## 8. Adoption and measurement

Adopt the matrix initially as guidance, not automatic routing. For each closed
turn, capture only the measurements needed to improve the decision:

- model slug, reasoning effort, and service tier as independent fields;
- primary, retry, and verifier token counts;
- acceptance result and reason for escalation;
- weekly headroom before/after when the product exposes it;
- whether the task fit the declared context envelope.

After enough comparable turns, replace the 25% planning margin with an observed
high percentile and estimate retry rates by task class. Do not infer hidden model
weights from a single weekly percentage change. Automating selection belongs in
later RFC 050 work and requires a consumer-specific schema and fail-safe route.

Refresh this study whenever a relevant model, price, context limit, subscription
limit, or product availability changes. Codex owns the OpenAI/Codex source refresh;
Claude owns the Anthropic source refresh; the peer adversarially checks the other
table and all arithmetic.

## Appendix A — source ledger

| Source | URL | Retrieved | Use / limitation |
|---|---|---|---|
| Anthropic model overview | https://platform.claude.com/docs/en/about-claude/models/overview | 2026-07-14 | Model IDs, pricing rows, context/output, latency, effort notes; captured by Claude via WebFetch |
| Anthropic pricing | https://platform.claude.com/docs/en/about-claude/pricing | 2026-07-14 | Confirms cache/Batch mechanisms exist; exact discount rows not captured |
| Claude plans and pricing | https://claude.com/pricing | 2026-07-14 | Plan prices and “usage limits apply”; captured by Claude via WebFetch |
| OpenAI API pricing | https://developers.openai.com/api/docs/pricing | 2026-07-14 | API standard/cached/output rows, priority row, regional uplift; captured by Claude via WebFetch |
| Codex plans and pricing | https://chatgpt.com/codex/pricing | 2026-07-14 | Codex CLI/ChatGPT plan relationship, plan prices, estimate ranges; captured by Claude through a network-capable source path |
| Codex subscription (secondary) | chatgpt.com/codex/pricing (primary); help.openai.com/en/articles/20001106-codex-rate-card; morphllm.com/codex-pricing; uibakery.io/blog/openai-codex-pricing | 2026-07-14 (WebSearch aggregation) | Plan prices ($0/$8/$20/$100/$200/$25) + 2026-04-02 token-accounting change; cross-consistent across these sources but retrieved via search aggregation, so evidence class = sourced observation, not a single direct official-page capture |
| GPT-5.3 Codex model page | https://developers.openai.com/api/docs/models/gpt-5.3-codex | retrieval failed 2026-07-14 | Intended source for explicit public context/output limits; values remain unknown |
| Codex service model catalog | local Codex CLI cache, fetched `2026-07-14T01:23:21.869788Z` | inspected 2026-07-14 | Runtime observation only; exact local slugs, effort tiers, and runtime context envelopes |
| SWE-bench tracker set | morphllm.com, vals.ai, llm-stats.com, and benchlm.ai pages enumerated in `STUDY-59-efficacy-facts.md` | 2026-07-14 | Harness-conditioned Verified/Pro observations; third-party except the labeled vendor-reported points |
| OpenAI GPT-5.3 Codex launch | https://openai.com/index/introducing-gpt-5-3-codex | 2026-07-14 | Product benchmark context and ancillary Terminal-Bench/OSWorld/GDPval signals; captured in the efficacy fact note |
| Operator Codex limits | `account/rateLimits/read` plus ChatGPT usage UI observation | since about 2026-07-12 | Account-specific weekly-only constraint; governs this routing but is not generalizable |

## Appendix B — review checklist

- Recheck every Claude row against the raw official capture, including the
  temporary Sonnet price and Mythos availability.
- Recheck each arithmetic expression and its units.
- Recheck ChatGPT plan prices against the captured official Codex pricing page;
  retrieve explicit OpenAI context/output limits when a network-capable source
  path is available.
- Preserve model, benchmark, and harness together; do not transfer Sonnet 4.6 or
  legacy `gpt-5.3-codex` scores to current selectable models.
- Capture exact URLs for the secondary token-accounting summaries or downgrade
  the 2026-04-02 date to unverified in the next source refresh.
- Confirm whether `gpt-5.3-codex` is selectable in any current Codex subscription
  surface; do not infer selectability from its API pricing row.
- Run a controlled fixture only where the minimum-adequate boundary remains
  decision-relevant after the source gaps are closed.
