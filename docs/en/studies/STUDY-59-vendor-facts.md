# #59 vendor facts — sourced by claude (WebFetch), retrieved 2026-07-14

**Evidence class: SOURCED FACT.** Claude fetched these because the codex sandbox
cannot reach the vendor pages. Each agent still adversarially cross-checks its own
vendor table. Prices are API list price per **million tokens (MTok)**, standard tier.

## Pricing-basis correction (operator, supersedes turn 703)
- Agents run in **CLI mode on subscriptions**, NOT the pay-per-token API. So the
  OPERATIVE cost for routing = **token consumption against the weekly subscription
  budget** ("weekly headroom"), not API $/token.
- Subscription usage limits are **vaguely documented** ("Usage limits apply") → use
  **token consumption as the measurable proxy + a conservative assumed upper bound**,
  marked **assumption/unknown** per the evidence rules (never a fact). Better to
  over-estimate consumption than under-estimate.
- **API $/MTok below = the RELATIVE-cost proxy** (a model's per-token "weight",
  which plausibly tracks how heavily it counts against the cap) + objective
  comparison layer. It is NOT the direct cost. The routing playbook (§8) is framed
  in subscription/weekly-budget terms.

## Claude models — source: platform.claude.com/docs/en/about-claude/models/overview
| Model | API ID | Input $/MTok | Output $/MTok | Context | Max out | Latency | Notes |
|---|---|---|---|---|---|---|---|
| Fable 5 | `claude-fable-5` | 10 | 50 | 1M | 128k | Slower | most capable widely-released; adaptive thinking always-on |
| Opus 4.8 | `claude-opus-4-8` | 5 | 25 | 1M | 128k | Moderate | complex agentic coding/enterprise; `effort` defaults **high** |
| Sonnet 5 | `claude-sonnet-5` | 3 | 15 | 1M | 128k | Fast | best speed+intelligence; **intro $2/$10 until 2026-08-31** |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | 1 | 5 | 200k | 64k | Fastest | fastest, near-frontier; extended thinking = Yes |
| Mythos 5 | `claude-mythos-5` | =Fable 5 | =Fable 5 | =Fable 5 | =Fable 5 | =Fable 5 | **invitation-only** (Project Glasswing, defensive-cyber); not GA |

- Reasoning-effort tiers (Claude): `low | medium | high | xhigh`. Opus 4.8 & Sonnet 5 default `high` on Claude Code/API.
- Knowledge cutoff: Jan 2026 (Fable/Opus/Sonnet), Feb 2025 (Haiku).
- Note: prompt-caching + Batch discounts exist (see /docs/en/about-claude/pricing) — not captured here; mark as UNKNOWN until sourced.

## Claude subscription — source: claude.com/pricing (the OPERATIVE basis)
Free $0 · Pro **$17/mo annual ($20 monthly)** · Max **from $100/mo** · Team $20/seat (std) or $100/seat (premium) · Enterprise $20/seat + API-rate usage. **"Usage limits apply. Prices exclude tax. Subject to change."** Exact per-model weekly-budget weighting is NOT published → assumption territory.

## OpenAI / Codex models — source: developers.openai.com/api/docs/pricing
| Model ID | Input $/MTok | Cached in | Output $/MTok | Notes |
|---|---|---|---|---|
| `gpt-5.3-codex` | 1.75 | 0.175 | 14.00 | **the Codex CLI model**; Priority tier 3.50 / 0.35 / 28.00 |
| `gpt-5.6-sol` | 5.00 | 0.50 | 30.00 | GPT-5 flagship |
| `gpt-5.6-terra` | 2.50 | 0.25 | 15.00 | |
| `gpt-5.6-luna` | 1.00 | 0.10 | 6.00 | |
| `gpt-5.5-pro` | 30.00 | – | 180.00 | |
| `gpt-5.4-mini` | 0.75 | 0.075 | 4.50 | |
| `gpt-5.4-nano` | 0.20 | 0.02 | 1.25 | |

- Context: page uses "Short context" vs "Long context" tiers, **no explicit token counts** → UNKNOWN, needs another source.
- Regional-processing (data-residency) endpoints: **+10% uplift** for models released ≥ 2026-03-05.
## OpenAI / Codex SUBSCRIPTION — source: chatgpt.com/codex/pricing + morphllm/uibakery (retrieved 2026-07-14)
Codex CLI is **free software**; it draws on the ChatGPT plan allowance (no standalone Codex sub).
Free $0 · Go $8 · **Plus $20** · **Pro from $100 (5x) / $200 (20x)** · Business $25/user/mo · Enterprise custom.
- **Token-based billing since 2026-04-02** (aligned to API token usage) → cost = token consumption vs the plan allowance. Vendor gives ESTIMATE RANGES, not fixed caps.
- Typical real-world cost cited ~**$100-200/developer/month**.
- ⚠️ **5h-window discrepancy (reliability)**: general Codex docs describe a **5-hour rolling window + weekly cap**, BUT the OPERATOR's actual account shows **WEEKLY-ONLY** (our direct #42 observation: `account/rateLimits/read` returned weekly-only + the operator's ChatGPT usage UI shows no 5h, only weekly + reset-credits, since ~2026-07-12). → For THIS operator's routing, the real constraint is **weekly-only**; the general-doc 5h may be account/tier/rollout-specific. Source says one thing, our observation says another — the OBSERVED reality wins for our routing, and the discrepancy is itself a finding.
- Plus 5h-window message ranges (per general docs, may not apply to this account): Sol 15-90, Terra 20-110, Luna 50-280 per 5h; Pro 5x is ~5×, Pro 20x ~20×.

## Caveats / unknowns (do not fill with guesses)
- Sonnet 5 intro pricing expires 2026-08-31 → snapshot-dated.
- Prompt-caching + Batch rates: unsourced here.
- Explicit context-token counts for OpenAI models: unsourced.
- Both vendors' subscription weekly-limit exact weights: undocumented → assumption + conservative bound.
