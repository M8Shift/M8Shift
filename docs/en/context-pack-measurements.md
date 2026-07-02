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

**Adoption:** M8Shift ships an optional RTK `shell_output_filter` adapter manifest and
runner policy, but not the RTK binary. See [rtk-shell-output-policy.md](rtk-shell-output-policy.md).

## Round 3 — Headroom (context compressor): adapter shipped, gain not claimed · 2026-07-01

Both agents — Claude (analysis) and Codex (independent review) — previously agreed **not** to run
Round 3 on the current native pack. That judgement still holds for the pack itself. In v3.39.0
M8Shift added the optional `headroom_ext` backend hook for **broad raw context records**
(`conversation`, `history`, `file`, `report`, `diff`, `large-context`). Since v3.40.0, `auto`
keeps those broad records on the builtin digest unless an operator explicitly sets
`backends.headroom_ext.auto_enabled: true` and identity-pins an adapter-compatible local
`headroom` command.

Reasoning:

- The native pack already distils real relay context to ~2 k tokens (1 727 proxy / 1 967 sonnet /
  2 537 opus) while preserving recent `ask`/`done`/`decision` **verbatim** + SHA-256 references, so
  Headroom would compress an **already-distilled operational view**, not the original relay — the
  remaining reducible material is small.
- **Equivalence risk rises, not falls:** the target is a *contract* pack where exact wording and
  absence-signals matter — exactly the fields that must not be semantically rewritten.
- Headroom adds ONNX + pip + a model download + the Phase-2 subprocess-runner surface **before**
  any evidence of extra value. The big wins are already captured (native pack on the relay-context
  axis, RTK on the shell-output axis).

**Measured footprint during v3.39.0 implementation.**

| Item | Measurement | Method / caveat |
|------|-------------|-----------------|
| `headroom-ai==0.28.0` base package + resolved wheel dependencies | **37.04 MiB** downloaded wheels | `python3 -m pip download --only-binary=:all: headroom-ai==0.28.0` on the implementation Mac |
| `headroom-ai[all]==0.28.0` / proxy / ONNX + model path | **not completed** | PyPI resolution timed out repeatedly during implementation; no size is claimed |
| Compression gain | **not claimed** | No adapter-compatible local Headroom one-shot command was available and no real-tokenizer + equivalence run was completed |

The upstream Headroom CLI is primarily documented around `wrap`, `proxy`, and `mcp` flows; the
M8Shift backend deliberately does **not** start those modes. `headroom_ext` is therefore an
optional RFC 034 adapter hook: it runs only when the operator provides and pins a local argv
subprocess that reads redacted stdin and writes compact stdout.

### Follow-up feasibility pass — library mode evaluated, wrapper not promoted · 2026-07-02

After v3.39.0, the operators asked whether M8Shift should ship a local Headroom wrapper instead
of leaving `headroom_ext` as a contract-only adapter. The feasibility result is split:

- **Library mode exists:** `headroom-ai==0.28.0` exposes `headroom.compress.compress(messages, ...)`,
  used by Headroom's own MCP/shared-context code path. It can run in-process and does not require
  the `headroom proxy` or MCP server.
- **Cold-cache risk exists:** the default Kompress path may start a background HuggingFace model
  download on first use. A M8Shift-compatible wrapper would therefore need to force offline/cache-only
  execution (`HEADROOM_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) and refuse to run
  unless the ONNX model is already installed.
- **The default decision is model-driven, not a Headroom rejection:** M8Shift's builtin compressor
  is an aggressive, lossy **digest** paired with mandatory bounded raw retrieval. That is the
  intended handoff model: send a small operational orientation, then retrieve evidence on demand.
  Headroom's library path is closer to a near-lossless conversation compressor and solves a
  different problem. A raw compact-token comparison between the two rewards builtin for dropping
  information that remains available through `retrieve`, so it is not a like-for-like quality
  benchmark.

Exploratory measurements:

| Case | Raw `o200k_base` tokens | Builtin compact | Headroom compact | Protocol note |
|------|-------------------------:|----------------:|-----------------:|---------------|
| `conversation` | 19,800 | 1,829 | 14,651 | Indicative only: builtin is a lossy digest + raw ref; Headroom keeps much more text. |
| `report` | 17,500 | 748 | 12,237 | Indicative only: same lossy-digest vs near-lossless-compressor caveat. |
| `file` | 15,200 | 474 | 15,200 | Struck from verdict: this raw blob is outside the conversation-message workload Headroom's one-function API targets. |
| `diff` | 14,599 | 1,081 | 14,599 | Struck from verdict: this raw blob is outside the conversation-message workload Headroom's one-function API targets. |

Test conditions:

- `headroom-ai==0.28.0` with the proxy/ONNX dependencies in a temporary virtualenv;
- Kompress ONNX model preloaded once, then compression run with offline/cache-only environment;
- `KompressCompressor().preload(allow_download=False)` succeeded before the measured calls;
- Headroom transforms observed: `router:text:0.70`, `router:kompress:0.73`, or `router:noop`;
- token counts: `tiktoken.get_encoding("o200k_base")`;
- no output-equivalence evaluation was completed;
- Claude/Anthropic `count_tokens` was not measured in this pass, so no Claude-token gain is claimed.

**Decision:** keep builtin as the automatic broad-context default because it matches M8Shift's
handoff contract: tiny digest + always-retrievable redacted raw evidence. Do not promote an
official Headroom wrapper until a representative conversation/report workload shows a meaningful
real-token gain **within its own quality target** and passes the equivalence check. The existing
`headroom_ext` adapter hook remains available for operator experiments, but M8Shift should not
treat a local Headroom command as the preferred broad-context backend merely because it is installed.

**Parked behind a concrete use case.** Headroom may become worth measuring for: large supporting
source sections; archive / RAG retrieval bundles; reports exceeding the pack budget; or
conversation/history/file records intentionally stored as raw compression records. **Hard
constraint:** compress only the *disposable / supporting* sections, **never** the
`ask`/`done`/`decision` verbatim blocks, and only with a strict preserve-block mechanism + source
references.

## RFC 037 backends inherit this DoD

[RFC 037](rfc/037-rfc-agent-context-compression-backends.md) formalizes the compression-backend
layer (builtin / RTK / optional Headroom, all as RFC 034 adapters). Any compression gain it claims
is held to the **same Definition of Done as this document**: real-tokenizer measurement (tiktoken
`o200k_base` for Codex, Anthropic `count_tokens` for Claude, never mixed) **plus** an
output-equivalence check (verbatim preserved, dropped content flagged and referenced by hash).
Runtime records carry only the advisory `estimated_proxy_tokens_*` (bytes/4) for policy decisions —
never presented as a measured gain. The Headroom constraint above (never compress the verbatim
`ask`/`done`/`decision` blocks) is normative for the RFC 037 `context_transform` backend.

## Round 3 — Headroom vs builtin, large-context (100k) FAIR pilot · 2026-07-02 (#84)

The first Headroom comparison ("8× worse") was struck as unfair (raw-blob input → `noop`; lossy
digest vs near-lossless compressor on token count alone). This round is a budget-scoped (~$1.35
Anthropic) **fair** re-run on the **large-context (100k) regime**, with the free rigor fixes applied.

**Setup.** One fixture: 41 RFCs concatenated + scrubbed = **99,017 o200k tokens** (sha `faab2f7c31e8`).
**11 pre-registered exact-match questions** (sha `ac8cd548`), position-verified: 3 head / **3 mid
(builtin's drop-zone)** / 3 tail / 2 **unanswerable** probes. Scored **programmatically (exact
substring match) — no LLM judge**, which removes judge bias and cost at once. Answering model:
`claude-opus-4-8`, one batched call per form, 1 run. Headroom produced by Codex in a repo-external
venv, run **offline/cache-only** (`preload(allow_download=False)`, onnx), fed as **41 RAG chunks**
(not a raw blob) — no-op check `false` (it genuinely compressed).

| Form | o200k tokens | accuracy (of 9) | head/mid/tail | hallucinations | unanswerable abstain |
|------|-------------:|:---------------:|:-------------:|:--------------:|:--------------------:|
| builtin **digest-only** | 2,112 (2.1%) | **1/9** | 0/3 · 0/3 · 1/3 | 0 | 2/2 |
| builtin **+ retrieval** | 8,472 (8.6%) | **5/9** | 2/3 · 1/3 · 2/3 | 0 | 2/2 |
| **Headroom** (aggressive, keeps 45.5%) | 45,085 | **6/9** | 2/3 · 1/3 · 3/3 | 0 | 2/2 |

**Directional findings.**
- builtin+retrieval and Headroom are **comparable on accuracy** (5/9 vs 6/9); Headroom edged it on
  the tail (3/3). But builtin+retrieval reaches it at **~1/5 the tokens** (8.5k vs 45k) —
  ~1,700 tokens/correct vs ~7,500.
- The **digest alone is near-useless for QA (1/9)**: it safely abstains but cannot answer — the
  **retrieve is essential** (empirically validates the M8Shift model: tiny digest + retrievable raw,
  not digest alone).
- **Both safe: 0 hallucinations**, both correctly abstained on the 2 unanswerable probes.

**Verdict (honest).** The builtin-default decision holds — *not* because Headroom is "worse" (it is a
legitimate near-lossless option that even edged accuracy here), but because for M8Shift's
retrieve-capable model, **digest+retrieval gets comparable answers at a fifth of the tokens**;
Headroom's marginal extra preservation costs ~5× the tokens. Consistent with keeping builtin the
`auto` default and Headroom opt-in (v3.40.0).

**Why builtin is more token-efficient here — the mechanism (this is *not* "builtin is a better
compressor").** The two tools solve different problems:
- **Headroom is a near-lossless *compressor*** — "same content, fewer tokens." It must carry the
  answer to *any* possible question inside its output (it cannot know what will be asked), so it
  pays tokens for the whole document (kept 45%).
- **builtin is a tiny lossy *digest* (~2%) + a *retrieval back-end*** — it discards ~98%, keeps a
  small "map," and fetches raw slices **only for what is actually queried**.

Analogy: Headroom photocopies a 100-page book at 45% size (you carry all 45 pages, always); builtin
keeps a 2-page index and leaves the book on the shelf, fetching only the 1–2 pages you open. For a
workload where each query touches only a **few facts**, index-and-fetch is far cheaper — you do not
pay to carry the ~96% nobody asked about. **The advantage is architectural (a retrieval back-end +
the task shape), not a smarter compression algorithm.** Headroom is a well-optimized tool doing its
own job correctly.

**When Headroom would win instead:** (a) **no retrieval** available → builtin's digest alone is
near-useless (measured: 1/9), Headroom's near-lossless 45% wins outright; (b) a task needing **most
of the content at once** (not a few facts) → the digest pays for many fetches; (c) **many rapid
facts** → each retrieval is a round-trip Headroom avoids. So the finding is workload-specific:
M8Shift's handoffs are retrieve-capable and few-facts-per-query, which is where digest+retrieval
wins; it is not a general claim that builtin out-compresses Headroom.

**Limits (this is a pilot, not a significance-grade verdict).** N=9 answerable, **1 run, 1 genre
(docs/RAG), 1 size (100k)**. The builtin+retrieval retrieval was **idealized** (slices supplied for
the queried facts) → its 5/9 is likely *understated*, so real agentic retrieval would probably
*widen* the efficiency gap in builtin's favor. Exact-match was strict (e.g. `tiered` ≠
`capability-tiered` counted as a miss for **both** forms). The full rigorous version (3 genres × 3
sizes, N≥50, ≥5 runs + bootstrap CIs + paired significance, config frontiers, blind cross-model
judge, both framings incl. Headroom-with-retrieval) is deferred behind budget (#84).

### Per-model (per-AI) results

Same fixture, questions, forms, and exact-match scoring; only the answering model changes
(+~$0.27). Codex-side (`gpt-5-codex`) is pending its env.

| AI model | Software / method | Ctx o200k | Accuracy (/9) | head·mid·tail | Halluc | Abstain | Tokens/correct |
|----------|-------------------|----------:|:-------------:|:-------------:|:------:|:-------:|---------------:|
| `claude-opus-4-8` | builtin digest-only | 2,112 | 1/9 | 0·0·1 | 0 | 2/2 | — |
| `claude-opus-4-8` | builtin + retrieval | 8,472 | 5/9 | 2·1·2 | 0 | 2/2 | ~1,700 |
| `claude-opus-4-8` | Headroom (aggressive, 45.5%) | 45,085 | **6/9** | 2·1·3 | 0 | 2/2 | ~7,500 |
| `claude-sonnet-4-6` | builtin digest-only | 2,112 | 1/9 | 0·0·1 | 0 | 2/2 | — |
| `claude-sonnet-4-6` | builtin + retrieval | 8,472 | 5/9 | 3·0·2 | 0 | 2/2 | ~1,700 |
| `claude-sonnet-4-6` | Headroom (aggressive, 45.5%) | 45,085 | **6/9** | 2·1·3 | 0 | 2/2 | ~7,500 |
| `claude-haiku-4-5` | builtin digest-only | 2,112 | 0/9 | 0·0·0 | 0 | 2/2 | — |
| `claude-haiku-4-5` | builtin + retrieval | 8,472 | 3/9 | 1·1·1 | 0 | 2/2 | ~2,800 |
| `claude-haiku-4-5` | Headroom (aggressive, 45.5%) | 45,085 | **4/9** | 1·1·2 | 0 | 2/2 | ~11,300 |
| `gpt-5-codex` | (all three) | (same) | *pending — Codex env* | | | | |

Cross-model reads: (a) digest-alone is useless for QA on **every** model; (b) builtin+retrieval is
the efficiency winner across the board; (c) **Headroom scores highest accuracy on every model**
(+1 answer over builtin+retrieval) — it is the strongest *near-lossless preservation* candidate —
but at ~5× the tokens; (d) the **cheaper model (haiku) benefits relatively more** from Headroom
(+33% vs opus +20%) — the one clear "Headroom helps" signal, relevant to cheap-model delegation.

### Accuracy vs reliability — read the table correctly

These are **two different axes**; do not conflate them:

| Column | Measures | Result |
|--------|----------|--------|
| **Accuracy** (X/9) | **completeness** — how many answerable questions the form preserved enough to answer correctly | varied (0–6) |
| **Hallucinations** | **reliability / safety** — did the model fabricate an answer it did not have? | **0 for every model and form** |
| **Abstention** (of 2) | did it correctly say "NOT PRESENT" on unanswerable probes? | **2/2 everywhere** |

So a low-accuracy form (e.g. builtin digest-only, 1/9) is **incomplete, not unreliable**: it
correctly abstained on what it lacked and never lied. On the **reliability** axis all forms tied at
**perfect**; they differed only in **completeness** (accuracy) and **token cost**. Net: **Headroom is
the best *accuracy/preservation* candidate and is fully reliable; builtin+retrieval is the best
*efficiency* candidate for M8Shift's retrieve-capable workload** — which is why builtin stays the
default and Headroom stays a reliable opt-in, not a rejected one.

### gpt-5-codex — a *different axis*: tool-assisted answer-presence (not long-context recall)

The `gpt-5-codex` cross-vendor row is **not comparable** to the Claude rows above and is kept
separate: Codex answered by **searching inside the form files** (its native agent/tool mode), not by
a pure long-context read. So it measures **whether each gold is present & findable in the form**,
not **whether a model recalls it from a single long-context pass**.

| Form | gpt-5-codex (tool-assisted) | Head | Mid | Tail | Halluc | Abstain |
|------|:---------------------------:|:----:|:---:|:----:|:------:|:-------:|
| builtin digest | 2/9 | 1/3 | 0/3 | 1/3 | 0 | 2/2 |
| builtin + retrieval | **9/9** | 3/3 | 3/3 | 3/3 | 0 | 2/2 |
| Headroom (aggressive) | **9/9** | 3/3 | 3/3 | 3/3 | 0 | 2/2 |

**Two findings this exposes:**
1. **Preservation (findability):** builtin+retrieval and Headroom **both contain all 9 golds (9/9)** —
   tied on completeness — while the digest truly drops 7. So the accuracy gap in the Claude
   long-context table (5-6/9) is a **recall limitation, not a preservation limitation**: the forms
   held more than a single-pass read recovered.
2. **For tool-assisted agents** (how M8Shift agents actually operate — they grep/read), **retrieval
   matches Headroom's completeness (9/9) at ~1/5 the tokens** — strengthening builtin+retrieval as
   the default. A strictly comparable `gpt-5-codex` *long-context-read* row (OpenAI API, no tools)
   is a follow-up (not run here; only the Anthropic key was available).
