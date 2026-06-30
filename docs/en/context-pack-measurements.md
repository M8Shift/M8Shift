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
> Claude agent `claude-opus-4-8`. The Codex side used the actual `gpt-5-codex`. **Update — the
> `claude-opus-4-8` re-run is now done (see below):** the equivalence behaviour holds on the
> deployed model and the Claude-exact reduction is ~96 % for both Claude tiers. The
> `claude-sonnet-4-6` figures are kept alongside the `claude-opus-4-8` ones.

### Tools tested

| Tool | Role | Notes |
|---|---|---|
| `m8shift-context.py` native pack | thing under test | Phase 1, stdlib-only, no external adapter |
| `tiktoken` `o200k_base` | real token count for **Codex** (`gpt-5-codex`) | exact |
| `tiktoken` `cl100k_base` | reference tokenizer | cross-check / invariance |
| Anthropic `count_tokens` API | real token count for **Claude** | exact (key-gated) |
| Anthropic Messages API | output-equivalence inference | `claude-sonnet-4-6` |

> **Note on tokenizers.** `tiktoken` is OpenAI's tokenizer (`o200k_base` / `cl100k_base` = the
> GPT family) and is used here for the **Codex / GPT side only** — it does **not** tokenize
> Claude. Every **Claude** token count comes exclusively from the Anthropic `count_tokens` API
> (Claude's real, proprietary tokenizer). The two are never mixed.

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

**Claude-exact** (Anthropic `count_tokens`, raw `M8SHIFT.md` → real pack, a later snapshot):

| Model | raw → pack | reduction |
|---|---|---|
| `claude-sonnet-4-6` | 51 082 → 1 967 | −96.1 % |
| `claude-opus-4-8` (**deployed**) | 69 088 → 2 537 | −96.3 % |

`opus-4-8` counts more tokens per text than `sonnet-4-6` (finer tokenizer), but the **reduction
ratio is the same** — confirming the saving holds for the deployed model.

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
| **Claude** (`claude-opus-4-8`, **deployed**) | answered correctly, verbatim from the pack | **not hallucinated** — flagged absent, pointed to the source, and even distinguished near-miss facts (git-alignment ≠ the asked branch list; pack version ≠ a relay engine promotion) |
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

## Round 2 — RTK (Rust Token Killer), shell-output filter · 2026-06-30

**Honest reframe.** RTK ([`rtk-ai/rtk`](https://github.com/rtk-ai/rtk), a zero-dependency Rust
binary) does **not** compete with the native pack: it compresses **live shell command output**
(test runs, git, listings, logs) before it reaches the model — a **different and complementary
token axis** to the relay-context pack. So Round 2 is not "beat −97.6 %"; it measures RTK's
**additive** saving on shell output, under the same DoD (real reduction *and* equivalence, both
models).

### Tools and method

`rtk 0.43.0` (installed via Homebrew). For each real command: raw output vs `rtk <command>`,
tokenized for **both models** — `tiktoken o200k` (Codex) and the Anthropic `count_tokens` API
with `claude-opus-4-8` (the deployed Claude). Cross-checked against RTK's own `rtk gain`.

### Token reduction (raw → rtk)

| Command | Codex (`o200k`) | Claude (`opus-4-8`) |
|---|---|---|
| `git diff HEAD~15` | 24 978 → 8 294 (−66.8 %) | 39 487 → 12 512 (−68.3 %) |
| `git log --stat -25` | 5 636 → 2 172 (−61.5 %) | 8 674 → 3 616 (−58.3 %) |
| `ls -lR` | 127 820 → 58 690 (−54.1 %) | 187 220 → 71 355 (−61.9 %) |

Both models agree closely, and my independent count matches RTK's self-report (`rtk gain` =
−68.5 %). Real reduction, **54–68 %** on shell output.

### Output equivalence (mode/task-dependent — the decisive half)

| RTK mode | Reduction | Equivalence |
|---|---|---|
| `rtk err` / `rtk test` | very high | ✅ **excellent** — keeps errors/warnings/failures, drops INFO noise (52 lines → 2: the ERROR + WARNING). Equivalent for "are there problems?" |
| `rtk git log` | −58/62 % | ✅ keeps commits + messages, marks omitted body lines `[+N lines omitted]` |
| `rtk ls` | −54/62 % | ✅ keeps the file list (4 965/5 165 entries), compacts the format |
| `rtk git diff` | −67/68 % | ⚠️ **lossy** — drops the actual hunks (raw 16 hunks / 1 685 `+` lines → 0 / 0), keeps only the stat. **Not equivalent for code review.** The dedicated `rtk diff` expects files, not git refs. |

### Verdict

RTK **passes the DoD selectively**: a real, large reduction (54–68 %) **with** equivalence for
**noisy / summary / error** output (logs, errors, status, listings) — its design target — but
**`rtk git diff` is lossy** for verbatim content, so a code review must read the actual diff
from raw output. RTK is **complementary** to the native pack (a different token axis); notably
`rtk err` *preserves* critical error lines that the native pack's line-truncation would drop —
the two cover each other's blind spots.

## Round 3 — Headroom (context compressor): parked, not run · 2026-06-30

Both agents — Claude (analysis) and Codex (independent review) — agreed **not** to run Round 3
on the current native pack. Reasoning:

- The native pack already distils real relay context to ~2 k tokens (1 727 proxy / 1 967 sonnet /
  2 537 opus) while preserving recent `ask`/`done`/`decision` **verbatim** + SHA-256 references, so
  Headroom would compress an **already-distilled operational view**, not the original relay — the
  remaining reducible material is small.
- **Equivalence risk rises, not falls:** the target is a *contract* pack where exact wording and
  absence-signals matter — exactly the fields that must not be semantically rewritten.
- Headroom adds ONNX + pip + a model download + the Phase-2 subprocess-runner surface **before**
  any evidence of extra value. The big wins are already captured (native pack on the relay-context
  axis, RTK on the shell-output axis).

**Parked behind a concrete use case.** Headroom may become worth testing later for: a profile that
intentionally inlines large file excerpts; large supporting-sources sections; archive / RAG
retrieval bundles; or reports exceeding the pack budget. **Hard constraint for any future Headroom
integration:** compress only the *disposable / supporting* sections, **never** the
`ask`/`done`/`decision` verbatim blocks, and only with a strict preserve-block mechanism + source
references.
