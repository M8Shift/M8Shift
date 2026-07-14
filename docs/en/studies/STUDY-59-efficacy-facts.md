# #59 efficacy facts — sourced by claude (WebSearch), retrieved 2026-07-14

**Evidence class: SOURCED OBSERVATION (third-party, harness-dependent).** These are
capability/efficacy signals to LINK to cost (operator's point: cost means nothing
without efficacy on the SAME task — a 5x-cheaper model that is 10x less effective
loses). Treat every number as harness-conditioned, NOT an absolute fact.

## ⚠️ RELIABILITY CAVEATS (must be front-and-center in the report)
1. **Trackers disagree because of SCAFFOLDING, not the models.** Same family scores
   ~51.9% (Scale SEAL) vs 69.2% (vendor harness). **"Agent tooling moves results
   more than model swaps."** → For M8Shift, the HARNESS (our prompts/tools/verify
   loop) may matter more than the model choice for coding efficacy. Report a RANGE
   per model, cite the harness, never a single point.
2. **SWE-bench Verified = Python-only.** SWE-bench **Pro** = 4 languages, contamination-
   resistant → more reliable for real work. Prefer Pro where available.
3. **gpt-5.3-codex is DEPRECATED in Codex**; OpenAI recommends general **gpt-5.5**
   (no 5.5-codex variant). → codex MUST confirm what its CLI 0.144.3 actually invokes.
4. **Name discrepancy**: Anthropic docs list **Sonnet 5** (`claude-sonnet-5`), but
   benchmark trackers still show **Sonnet 4.6** (79.6% Verified). Sonnet 5 may be too
   new for trackers → cross-check; mark Sonnet 5 efficacy UNKNOWN until sourced.

## SWE-bench Verified (coding, Python-only) — approx, harness-varying
| Model | Verified % | note |
|---|---|---|
| Claude Mythos 5 | 95.5 | invitation-only |
| Claude Fable 5 | 95.0 | |
| GPT-5.5 | 88.7 | OpenAI-reported; #1 |
| Claude Opus 4.8 | 88.6 (Anthropic harness) / ~80.8 (some trackers) | **spread = harness** |
| gpt-5.3-codex | ~85.0 (third-party) | OpenAI emphasized Pro, not Verified |
| Claude Sonnet 4.6 | 79.6 | (Sonnet 5 not yet on trackers) |
| Claude Haiku 4.5 | ~73.3 (varies) | budget tier |

## SWE-bench Pro (4 languages, contamination-resistant) — more reliable
| Model | Pro % | note |
|---|---|---|
| Claude Fable 5 | 80.3 | |
| Claude Opus 4.8 | 69.2 | "highest of any buyable model" (Anthropic harness) |
| gpt-5.3-codex | 56.8 (xhigh effort) | vs 41.0 under Scale's standardized harness (scaffold!) |

## Other codex signals
- gpt-5.3-codex: Terminal-Bench 2.0 77.3%, OSWorld-Verified 64.7%, GDPval 70.9% win/tie, often fewer tokens. Released 2026-02-05, "25% faster than 5.2-codex".

## How to LINK cost↔efficacy (operator's directive)
Decision metric = **expected cost per ACCEPTED result**, not raw price:
`= run cost + P(retry)*retry cost + verification cost`, where P(retry) falls as
efficacy rises. A cheap model with high retry/rework on task T is NOT cheap.
Route to the **cheapest model whose efficacy clears the task's acceptance bar**;
upgrade when the efficacy gain cuts expected retries/risk more than the cost delta.

## Sources (retrieved 2026-07-14)
- morphllm.com/claude-benchmarks · morphllm.com/swe-bench-pro · morphllm.com/best-ai-model-for-coding
- vals.ai/benchmarks/swebench · llm-stats.com/benchmarks/swe-bench-verified · benchlm.ai/benchmarks/sweVerified
- benchlm.ai/models/gpt-5-3-codex · openai.com/index/introducing-gpt-5-3-codex · neowin (gpt-5.3-codex launch)
