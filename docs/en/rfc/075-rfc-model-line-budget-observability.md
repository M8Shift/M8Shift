# RFC 075 — Model-line budget observability and graceful exhaustion research

- **Status:** Phase 1 research draft; no implementation or failover policy is
  authorized
- **Date:** 2026-07-18
- **Issue:** #212
- **Scope:** evidence available before a model or model-family quota is exhausted
- **Builds on:** [RFC 040](040-rfc-ai-session-usage-monitoring.md),
  [RFC 051](051-rfc-usage-advisory-in-core-display.md),
  [RFC 054](054-rfc-pre-exhaustion-session-rotation.md), and
  [RFC 070](070-rfc-provider-pinned-model-launch.md)

## 1. Incident packet first

### Symptom and impact

During an active turn, one selectable model line stopped accepting work while the
provider account still displayed credit or aggregate headroom. The relay had no
line-specific warning, so the failure arrived after the turn had begun. Account
credit and model-line capacity were incorrectly treated as interchangeable.

### Minimal abstract reproduction

1. Configure two selectable model lines, `model-a` and `model-b`, under one
   provider account.
2. Consume `model-a` until its own rate/budget bucket rejects a request.
3. Observe that the account surface still reports non-zero aggregate credit, or
   that `model-b` remains available.
4. Start a relay turn pinned to `model-a`.
5. Observe a mid-turn provider refusal without an earlier actionable line-level
   signal in the normalized M8Shift usage snapshot.

### Root cause

The existing usage contract normalizes provider/account windows for a target
agent. It does not identify the quota bucket that governs the selected model.
Provider products also expose different concepts through API, subscription CLI,
and cloud-console surfaces. A valid account-level percentage therefore cannot
prove that a particular model line can complete the next turn.

### Required anti-recurrence guard

Before any future implementation can claim anticipatory protection, a fixture
must demonstrate this exact split:

```text
account headroom > 0
model-a headroom = 0 or near-limit
model-b headroom > 0 or unknown
```

The normalized decision must never collapse those three facts into one account
percentage. An unavailable line signal remains `unknown`; it is never inferred
from account credit or API list price.

## 2. Research method and vocabulary

This phase asks what a provider makes observable, not what M8Shift could estimate
from historical tokens. A **model line** means the provider quota bucket that
governs a named model, model family, or documented shared-limit group. It is not
necessarily one model slug. Providers may pool several slugs behind one bucket.

Evidence classes:

- **documented:** an official public contract describes the surface;
- **runtime-observed:** a dated local product response establishes behavior for
  one account and version, but is not a portable public contract;
- **console-only:** visible to an authenticated operator, with no supported
  machine-readable contract established;
- **unknown:** no evidence sufficient to support the claim.

“Freshness” below is the best usable cadence of the surface. “Access cost” means
operational work and privilege, not provider token price. This research was
assembled on 2026-07-18 from the cited official contracts plus the already
captured 2026-07-10/14 runtime evidence in RFC 040 and Study 59. Live browser
retrieval re-opened the cited public contracts on 2026-07-18. Claims that still
depend on an authenticated product UI or an undocumented CLI RPC are labelled
accordingly rather than promoted to portable fact.

## 3. Comparative matrix

| Vendor / surface | Observable granularity | Freshness | Access cost | Authentication | Can warn for one model line? |
|---|---|---|---|---|---|
| Anthropic Messages API rate-limit response headers | Organization/workspace limits applied separately per model, with explicit combined buckets (including pooled Opus 4.x and Sonnet 4.x families, while Sonnet 5 is separate); token headers report the most restrictive limit in effect but do not identify that bucket | Per response | Low once traffic is already instrumented | API key | **Yes, for API traffic**, at the documented model/model-group bucket; `provider_bucket_id` stays null unless the provider contract supplies or maps it |
| Anthropic Rate Limits API | Configured organization and workspace limits, including their model/model-group applicability | On administrative read | Medium; privileged polling and normalization | Organization Admin API key | **Yes, for API configuration**; pair it with response evidence for current remaining capacity |
| Anthropic Admin Usage/Cost API | Usage can be grouped by model; this is consumption history, not necessarily remaining quota | Bucketed report; not a pre-request reservation | Medium; separate polling and normalization | Organization Admin API key | **Partial**: model usage is visible, but remaining line headroom still needs the limit contract/header |
| Anthropic Console limits/usage | Account/workspace configuration and historical usage | Operator refresh | Medium/manual | Signed-in organization role | **Partial/console-only**; unsuitable as the sole headless gate |
| Claude Code subscription usage surface / OAuth usage observation | Five-hour and weekly account windows in current observed shapes | Near-live when the product endpoint is fresh | Low locally, but unsupported contract risk | Claude subscription OAuth/session | **No established line dimension**; current fixture is account/agent aggregate |
| OpenAI API rate-limit response headers | Project/organization bucket for the requested model; models may share a documented limit group | Per response | Low once API calls are instrumented | API key | **Yes, for API traffic**, provided the active shared-limit group is retained rather than guessed from the slug |
| OpenAI Organization Usage API | Usage grouped by model/project/key/user | Bucketed report | Medium; polling plus Admin surface | Organization Admin API key | **Partial**: strong attribution, but usage history alone is not remaining quota |
| OpenAI Limits/Usage console | Model limits and project/account usage | Operator refresh | Medium/manual | Signed-in owner/admin | **Yes for configured API limits; partial for live exhaustion** |
| Codex CLI app-server `account/rateLimits/read`, `/status`, ChatGPT usage UI | Current observed `codex` primary/secondary or weekly subscription buckets | Near-live, account-specific | Low local RPC/UI; experimental schema risk | Signed-in Codex/ChatGPT account | **No established per-model line signal**; one account has exposed weekly-only despite general documentation |
| Google Gemini API quota failure details | Project quota metric with model/location dimensions where the quota defines them | On rejection | Low, but too late for anticipation | API key or Google Cloud credentials | **Yes for diagnosis**, not a remaining-headroom forecast by itself |
| Google Cloud Quotas / Service Usage / Cloud Monitoring | Project/service quota limits and usage dimensions; model-specific dimensions depend on the quota | Configuration reads plus monitoring cadence | High; cloud project, IAM, metric mapping | Google Cloud OAuth/service account with quota/monitoring roles | **Yes for documented model-dimensioned quotas**, with dynamic/shared quota explicitly allowed to stay unknown |
| Google AI Studio / Cloud Console quota pages | Per-project quota tables, often model-qualified | Operator refresh | Medium/manual | Signed-in project member | **Yes/console-only** where the table has a model dimension |
| Gemini CLI session statistics and quota errors | Local session token counts; refusal text may name a model/fallback | Session-live or on rejection | Low | Gemini CLI login/API key | **No supported remaining line budget established**; session tokens are not provider quota headroom |
| Mistral API response and 429 surface | Request evidence for chat/embeddings can include `x-ratelimit-remaining-requests` and `Retry-After`; treat header shape and reset semantics as runtime-observed rather than a stable bucket-identity contract | Per response or on rejection | Low | API key | **Partial**: useful for the requested call, but it does not supply a portable model-bucket identity |
| Mistral La Plateforme tier contract and Admin usage metrics | Documented per-model TPM and requests/second limits plus usage metrics available through the Admin API | Administrative read/reporting cadence | Medium; admin polling and normalization | Signed-in workspace admin / Admin API credentials | **Yes for documented per-model configured limits; partial for live exhaustion** |
| Mistral CLI/Vibe local statistics or errors | Local request/session evidence and provider refusal | Session-live or on rejection | Low | CLI/provider login | **No supported remaining line budget established** |

## 4. Vendor findings

### 4.1 Anthropic

The Messages API documents response headers for request and token limits,
remaining capacity, and reset instants. Anthropic applies rate limits at the
organization/workspace level and separately by model, with explicit combined
model-family buckets: the documented Opus 4.x models share one pool, the Sonnet
4.x models share another, and Sonnet 5 has a separate limit. The
`anthropic-ratelimit-tokens-*` headers describe the most restrictive token limit
currently in effect without returning a bucket identifier. A caller may use the
documented mapping but must not manufacture a `provider_bucket_id` from the
requested slug. This remains the strongest near-live line-level signal in API
mode.

The programmatic Rate Limits API reads configured limits at organization and
workspace scope and preserves their model/model-group applicability. The Admin
Usage and Cost API adds model-attributed history with privileged organization
access. It can explain burn and support forecasting, but a usage bucket is not a
promise of remaining capacity unless joined to the corresponding limit. The
Claude Code subscription surfaces already normalized by RFC 040 expose account
windows, not a documented model-line key. They must remain aggregate.

### 4.2 OpenAI

OpenAI API responses expose request/token limit, remaining, and reset headers.
Rate limits are model- and project/organization-sensitive, and some models share
limit groups. The adapter therefore needs a provider-supplied group identity or a
documented mapping; copying the requested slug into `bucket_id` would create false
precision.

The Organization Usage API supports model attribution and is useful for burn-rate
forecasting. The Limits console supplies configured limits. Neither establishes a
portable contract for Codex subscription model lines. The current Codex app-server
RPC supplies aggregate rate-limit windows keyed to the product bucket, and its
experimental shape has already varied by account. It is actionable for an account
cooldown, not proof that a selected Codex model line is healthy.

### 4.3 Google

Gemini API and Vertex AI quotas are project/service quotas with documented
dimensions that may include model and location. Cloud quota/monitoring APIs and
console tables can expose those dimensions, while rejection details identify the
quota that was actually exceeded. Dynamic shared quota and capacity-controlled
models weaken any static “remaining requests” interpretation; absence of a model
dimension must stay unknown.

Gemini CLI session statistics are useful consumption telemetry but are not a
quota API. A fallback or 429 message may diagnose the exhausted line only after
the fact. Anticipation requires the cloud quota surface or a separately documented
subscription signal.

### 4.4 Mistral

Mistral's tier contract publishes limits per model in both tokens per minute and
requests per second, and exposes usage metrics through the Admin API. That is a
documented model-line configuration and usage surface, not merely a diagnostic
429. Official support guidance also describes
`x-ratelimit-remaining-requests` and `Retry-After` for chat and embeddings, but
the reviewed evidence does not establish a stable response contract that names
the governing model bucket or provides portable reset semantics. Phase 1
therefore treats those headers as runtime-observed evidence: configured
per-model limits and Admin usage may be normalized, while live remaining/reset
fields and `provider_bucket_id` stay nullable unless an observed response and a
documented mapping justify them. Vibe-local statistics remain consumption
evidence, not provider quota headroom.

## 5. Cross-vendor conclusion

There is no vendor-neutral, subscription-CLI model-line quota API.

- API mode can obtain strong per-request bucket evidence from Anthropic and
  OpenAI, model-dimensioned cloud quota evidence from Google, and documented
  per-model configuration plus Admin usage evidence from Mistral; Mistral's
  remaining/reset response shape stays runtime-observed.
- Historical usage grouped by model improves forecasting but never proves the
  selected line is currently admitted.
- Subscription CLI surfaces are predominantly account/product-window signals.
  They must not inherit a model-line label merely because the current invocation
  names a model.
- A graceful failover design must accept `unknown` as a first-class result. It
  cannot advertise prevention for vendors or modes that reveal only a terminal
  429 or aggregate account percentage.

## 6. Candidate normalized evidence for Phase 2 review

This is a research output, not an authorized schema. The minimum evidence a
future design appears to need is:

```text
provider
mode = api | subscription_cli | cloud
scope = account | organization | project | workspace | model_group | model
requested_model
provider_bucket_id (nullable; never synthesized)
used_ratio / remaining_ratio / reset_at (nullable)
signal = response_header | usage_report | quota_metric | console | runtime_observation | rejection
provenance = documented | runtime_observed | console_only | unknown
captured_at
```

Claude review must decide before Phase 2:

1. whether a missing provider bucket identity forbids automatic model failover;
2. how historical burn forecasts are kept separate from provider-reported
   remaining quota;
3. which API-mode signals justify a mid-shift switch and which only justify a
   clean halt;
4. whether subscription CLI mode can ever switch automatically without an
   explicit operator policy; and
5. how adapter inheritance extends RFC 040 without putting vendor subclasses in
   the passive core.

No base class, vendor subclass, switch policy, or halt threshold is selected in
this phase.

## 7. Official source ledger

- Anthropic rate limits and headers:
  <https://platform.claude.com/docs/en/api/rate-limits>
- Anthropic programmatic Rate Limits API:
  <https://platform.claude.com/docs/en/manage-claude/rate-limits-api>
- Anthropic Usage and Cost Admin API:
  <https://platform.claude.com/docs/en/api/usage-cost-api>
- Anthropic Claude Code costs and usage:
  <https://platform.claude.com/docs/en/docs/claude-code/costs>
- OpenAI rate limits and response headers:
  <https://developers.openai.com/api/docs/guides/rate-limits>
- OpenAI Organization Usage API:
  <https://developers.openai.com/api/reference/usage>
- OpenAI Codex pricing and limits:
  <https://developers.openai.com/codex/pricing/>
- Google Gemini API rate limits:
  <https://ai.google.dev/gemini-api/docs/rate-limits>
- Google Cloud quota concepts:
  <https://docs.cloud.google.com/docs/quotas/overview>
- Vertex AI generative AI quotas:
  <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/quotas>
- Google Cloud quota monitoring:
  <https://docs.cloud.google.com/docs/quotas/view-manage>
- Mistral per-model tiers and Admin usage metrics:
  <https://docs.mistral.ai/admin/user-management-finops/tier>

URLs identify the official evidence re-opened for this draft. Phase 2 must still
re-open each contract before implementation because provider fields, model
groups, and documentation routes can change independently of this design.
