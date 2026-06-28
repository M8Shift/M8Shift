# RFC — Context economy & agent handoff protocol

**Status:** draft · **Builds on:** [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md) (runtime sidecars / roles), [012-rfc-contracts-validation.md](012-rfc-contracts-validation.md) (turn contracts), [018-rfc-agent-runtime-architecture.md](018-rfc-agent-runtime-architecture.md) (roles), [022-rfc-session-reports.md](022-rfc-session-reports.md) (reports / decision ledger), [031-rfc-decision-traceability.md](031-rfc-decision-traceability.md) (decision records), [032-rfc-tiered-delegation.md](032-rfc-tiered-delegation.md) (sub-agent delegation) · **Origin:** reworked from a Codex draft (companion scoping, cross-references to existing RFCs instead of duplication, advisory budgets, an explicit economy-vs-verification reconciliation, scrubbed header).

## 1. Purpose

Define a **context economy** and **handoff protocol** for M8Shift agents: cut token use and
cost, improve reliability, and stop uncontrolled context expansion in multi-agent work.

> **Agents do not share context. Agents exchange contracts.** Context stays local; handoffs
> stay compact.

This is a **companion + agents-guide discipline**, **not a core change**: the degree-1 mutex,
the single-file `m8shift.py`, and the append-only journal are unchanged.

## 2. Problem

Multi-agent sessions get expensive and unreliable when agents receive huge context windows,
subagents are spawned reflexively, sessions accumulate irrelevant history, and raw logs / file
contents / prior reasoning are passed between agents. The core issue is **uncontrolled context
transfer between agents**, not just the initial prompt size.

## 3. Three context layers (mapped onto M8Shift)

| Layer | What it holds | Where it lives in M8Shift | Forwarded? |
|-------|---------------|---------------------------|------------|
| **Local** | raw tool output, exploration, temp reasoning, debug logs, intermediate failures | the agent's own session (never a relay file) | **No** by default — disposable |
| **Shared working memory** | current goal, locked decisions, active constraints, key architecture facts, current plan, last verified state | the append-only `M8SHIFT.md` journal (+ `M8SHIFT.memory.md`, `M8SHIFT.tasks.md`) | Yes, compact |
| **Archive / evidence** | logs, long reports, test output, file snapshots, run reports | `.m8shift/runtime/` + session reports (RFC 022) + the runs ledger | By **reference**, not pasted |

Shared working memory is short and actively maintained (advisory target ~2k–8k tokens); it must
not become a project archive.

## 4. A handoff is a contract, not a copied conversation

M8Shift already carries a compact handoff in the turn contract:
`append --ask "…" --done "…" --files a,b` (RFC 012). This RFC adds a richer **Task Packet** for
delegation — an *extension* of that contract, not a parallel format.

A **Task Packet** carries only: **Objective**; **Scope** (files / modules the agent may inspect
or change); **Inputs** (only the facts required); **Constraints**; **Known decisions** (not
reopened unless explicitly requested — see RFC 031); **Unknowns / risks**; **Expected output
format**; **Token budget**. It **must not** include full conversation history, raw logs, full
file contents, prior agent reasoning, or broad background — **references over pasted content**.

## 5. Context gatekeeper (a companion role)

An optional **context-gatekeeper** role (RFC 018) prepares the Task Packet before a handoff:
extract the objective, drop irrelevant history, turn prior work into decisions / constraints /
open issues, replace raw logs with conclusions, keep only the exact snippets needed, and
**refuse a delegation whose scope is too broad**. It compresses and transmits; it does **not**
solve the task, make architecture decisions, expand scope, or add speculation. It is advisory
and never holds the core pen.

## 6. Subagent & delegation policy (the economy layer for RFC 032)

[032-rfc-tiered-delegation.md](032-rfc-tiered-delegation.md) defines the *structure* of
sub-agent delegation; this section is its *economy / policy*.

Spawn a subagent only when the task is self-contained, summarizable compactly, needs little of
the parent context, would otherwise pollute the main context, and is verifiable. Do **not**
spawn for continuous-shared-state work, discussion / decision-making, when the parent already
has the context, or when the result must be pasted back in full.

Advisory default policy (a companion config — not core-enforced):

```yaml
delegation:
  default_subagent_model: cheap        # capability tier, see RFC 032
  expensive_only_for: [architecture_decision, complex_debugging, final_review, security_sensitive_change]
  require_subagent_justification: true
  max_parallel_subagents: 3
  max_subagent_depth: 1
```

## 7. Agent result format

Agents return a compact, structured result (an `append --done` body; see RFC 022): **Status**
(done / blocked / partial / failed); **Summary** (≤ 5 bullets); **Changes** (files / sections);
**Evidence** (checks, tests, builds run); **Risks** (≤ 3); **Decisions needed** (only if
blocked); **Suggested next Task Packet** (only if the work continues). It must **not** return
full logs, full file contents, long reasoning transcripts, repeated input, or generic advice.

## 8. Budgets are advisory, not enforced

M8Shift is **tokenizer-less** (stdlib-only), so token counts are an approximation (proxy
`bytes / 4`). **Token budgets are therefore advisory targets**, surfaced by a companion check —
**not hard-enforced by the core**. **Line-based limits are exact** and preferred where a hard
cap matters:

```yaml
context_policy:                 # token figures are advisory estimates; line figures are exact
  parent_context_target: 12000
  shared_memory_target: 4000
  task_packet_target: 1500
  subagent_output_target: 800
  raw_log_inline_limit: 80      # lines — enforceable
  code_snippet_inline_limit: 120  # lines — enforceable
```

## 9. Economy never starves verification (the hard constraint)

Context economy is **subordinate to correctness**. Compression must **never** amputate the
context an agent needs to *verify* its own work, or that a reviewer needs to *catch an error*
(see the agents-guide *Verification honesty* and RFC 032's *verify-before-integrate*).

- A cheaper-tier model is **more** error-prone, so a tight Task Packet pairs with **mandatory
  verification** of its output against ground truth before integration — never delegation +
  blind trust.
- A packet so narrow that the agent cannot verify, or a reviewer cannot independently check, is
  a **failure, not a saving**.
- The correct response to insufficient context is **not** to guess: return *a request for a
  narrower, better-scoped Task Packet* (or escalate) — never silently expand and never silently
  proceed.
- The honest rule: **transmit the minimum the next agent needs to do the work *and prove it
  correct*** — not the minimum to merely produce output.

## 10. Session hygiene & preflight

Compact context at clear phase boundaries (after exploration, after plan approval, after
implementation, after tests, after review, before switching tasks, before spawning agents).
When switching task, default to clearing context unless a formal handoff summary exists.

A **preflight** before a multi-agent task: identify the task type and required context sources,
exclude irrelevant ones, build a compact brief, decide whether subagents are justified, assign a
model tier per agent (RFC 032), set input / output budgets, and define the expected result
format.

## 11. Global agent instruction (for the agents-guide / curated AGENTS.md)

> **Context budget discipline.** Minimize context transfer between agents. Never forward raw
> conversation history, raw logs, large file contents, or prior agent reasoning unless required.
> Before delegating, build a compact Task Packet (objective, scope, required facts, locked
> decisions, constraints, references, expected output, budget). When receiving a task, work
> within the provided scope; if blocked or unable to **verify**, return a request for a narrower
> Task Packet rather than expanding context. When returning, give status, a concise summary,
> files touched, verification performed, risks / blockers, and the next action — never the full
> logs, full files, or hidden reasoning. Prefer references over pasted content. **Economy never
> overrides correctness: keep enough context to prove the work, not just to produce it.**

## 12. Charter constraints

1. **Companion + discipline, not core.** The degree-1 mutex, the single-file core, and the
   append-only journal are unchanged; the gatekeeper / budgets / preflight live in the runtime
   companion (RFC 009) and the agents-guide.
2. **Advisory.** Budgets and policies are advisory targets + companion checks; nothing blocks a
   legal core transition.
3. **Economy is subordinate to verification** (§9).
4. **Stdlib-only.** No tokenizer dependency; token figures are approximations, line limits are
   exact.

## 13. Expected benefits

Lower token use and long-session cost; less subagent amplification, context pollution, and
duplicated reasoning; fewer failures from irrelevant information. Clearer delegation, better
agent isolation, traceability, reviewability, and cost predictability.

## Open questions (flagged for review)

1. Is the Task Packet a **new** artifact, or strictly an extension of the `append` contract +
   the RFC 012 schema?
2. Should the gatekeeper be a runtime-companion command, a role (RFC 018), or — at first — only
   an agents-guide discipline?
3. How to surface the advisory token *approximation* honestly (label estimates as estimates)
   without implying enforcement the tokenizer-less core cannot provide?
4. Default compaction triggers — automatic at phase boundaries, or operator-invoked?
