# Context companion — DoD measurements

This page is the living **evidence log** for the M8Shift context companion
(`m8shift-context.py`, [RFC 034](rfc/034-rfc-companion-adapter-interface.md)). It records
what was measured, with which tools, the before/after numbers, and the output-equivalence
checks. It grows as adapters (e.g. Headroom, RTK) are added and re-measured. See also
[RFC 033 — context economy](rfc/033-rfc-context-economy.md).

> **Definition of Done** for any context-reduction step is two-fold: a **real measured token
> reduction** *and* an **equivalent output** — fewer tokens with the same answers. A reduction
> that loses needed information is a failure, not a saving (RFC 034 §16, RFC 033 §9). Measure
> with vs without, on small / medium / large contexts, for **both Claude and Codex**.

## Round 1 — native pack (Phase 1) · 2026-06-30

### Models and versions under test

| Role | Identifier | Notes |
|---|---|---|
| Equivalence inference, Claude side | `claude-sonnet-4-6` | cost-efficient **stand-in** used for the test |
| Claude token count (Anthropic `count_tokens`) | `claude-sonnet-4-6` | model param passed to the API |
| Equivalence, Codex side (self-reported) | `gpt-5-codex` | the relay's actual Codex agent |
| Codex token tokenizer | `tiktoken` `o200k_base` | the GPT-4o / GPT-5 / Codex BPE |
| Reference tokenizer | `tiktoken` `cl100k_base` | cross-check / invariance |
| **Deployed relay agents** | **`claude-opus-4-8`** (Claude) · **`gpt-5-codex`** (Codex) | what actually runs in the relay |

> ⚠️ **Caveat — test model vs deployed model.** The Claude-side equivalence and token
> count used `claude-sonnet-4-6` as a cost-efficient stand-in, **not** the deployed relay
> Claude agent `claude-opus-4-8`. The Codex side used the actual `gpt-5-codex`. A re-run on
> `claude-opus-4-8` is **pending / optional** for deployed-exact Claude numbers; the
> equivalence behaviour (preserved-verbatim, dropped-flagged) is expected to hold across
> Claude tiers, but the exact token counts will differ slightly.

### Tools tested

| Tool | Role | Notes |
|---|---|---|
| `m8shift-context.py` native pack | thing under test | Phase 1, stdlib-only, no external adapter |
| `tiktoken` `o200k_base` | real token count for **Codex** (`gpt-5-codex`) | exact |
| `tiktoken` `cl100k_base` | reference tokenizer | cross-check / invariance |
| Anthropic `count_tokens` API | real token count for **Claude** | exact (key-gated) |
| Anthropic Messages API | output-equivalence inference | `claude-sonnet-4-6` |

### Token reduction (before → after)

**Synthetic benchmark fixtures** (Codex `o200k`, exact):

| Fixture | raw → pack | reduction | `cl100k` cross-check |
|---|---|---|---|
| small | 275 → 177 | −36 % | −37 % |
| medium | 2035 → 177 | −91 % | −92 % |
| large | 9955 → 177 | −98 % | −98 % |

`o200k` and `cl100k` agree within ~2 pp → the reduction is **tokenizer-invariant**, so it
applies to Claude as well.

**Real relay context** (live `M8SHIFT.md`, 293 KB, proxy `bytes/4`):

| Metric | before | after | reduction |
|---|---|---|---|
| proxy tokens | 73 394 | 1 727 | **−97.6 %** |
| lines | 3 305 | 145 | −95.6 % |

The pack is roughly **constant-size**, so the reduction grows with input size: small contexts
gain modestly (~36 %), medium/large 91–98 %.

### Output equivalence (the harder half)

The real pack preserves the **recent turns verbatim** (`ask`/`done`/`decisions`/`files`),
compacts supporting sources, and lists a **Source references** table with `path` + `SHA-256`
back to `M8SHIFT.md`, under a *"this is an operational view, not evidence — verify against
originals"* disclaimer.

Canonical-question test against the **real** pack — one **preserved** recent fact, one
**dropped** older fact — for both models:

| Model | Recent preserved fact | Older dropped fact |
|---|---|---|
| **Claude** (`claude-sonnet-4-6`) | answered correctly, verbatim from the pack | **not hallucinated** — flagged absent, pointed to `M8SHIFT.md` to retrieve |
| **Codex** (`gpt-5-codex`, self-reported) | answered correctly, verbatim from the pack | **not hallucinated** — flagged absent, pointed to the `SHA-256` source references to retrieve |

**Result:** equivalence holds **for both models** — preserved facts are usable; dropped facts
are safely flagged and referenced, never answered falsely. Equivalence is **conditional on the
agent retrieving when it detects a gap**, which both models did.

### Verdict

Round 1 **passes the DoD**: a real, large token reduction (−97.6 % on real context) **with**
equivalence-preserving behaviour for both Claude and Codex.

### Caveats (honest)

- The **first equivalence attempt was flawed**: it used the benchmark's synthetic compactor
  (`native_compact_fixture`) on a hand-crafted input it does not parse, producing an empty
  pack; that result was discarded and the test re-run against the **real** `pack` command.
- Synthetic fixtures and the real pack differ; the real-context numbers are authoritative.
- Real-relay token figures are the `bytes/4` proxy (the core is tokenizer-less); the fixture
  figures are exact (`tiktoken` / Anthropic API).
- The Codex-side equivalence is **self-reported** by `gpt-5-codex` reading the real pack (no
  independent OpenAI tokenizer/inference was run from the Claude side).

### Method / reproduction

Tokenizers: `tiktoken` `o200k_base` (Codex) and the Anthropic `count_tokens` API (Claude);
equivalence via the Anthropic Messages API. Native pack via
`m8shift-context.py pack --profile reviewer`. The external-dependency measurement harnesses
live **outside** the stdlib-only core (they require `tiktoken` and a model API key).

## Round 2 — first external adapter (Headroom or RTK)

*Pending a maintainer decision.* To beat Round 1, an external adapter must reduce **beyond**
~177 tokens / −97.6 % **while staying equivalent** — a high bar against the native baseline.
