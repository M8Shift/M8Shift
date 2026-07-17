# RFC 062 — Listening ends only at DONE

- **Status:** implemented (#73, 2026-07-14)
- **Scope:** the coordination protocol's listening/liveness contract, binding
  every agent in every project (generated `M8SHIFT.protocol.md`, the injected
  `CLAUDE.md`/`AGENTS.md` floor, and `M8SHIFT.agent-pack.md`).
- **Builds on:** [RFC 047](047-rfc-headless-liveness-final-state.md),
  [RFC 049](049-rfc-holder-liveness-stale-claim.md),
  [RFC 055](055-rfc-wait-on-operator-holder-state.md), and
  [RFC 058](058-rfc-go-forward-rfc-discipline.md).

## Problem

The prior **Listening invariant** was conditioned on *"if not `DONE` and you
**lack the pen**"*. That phrasing left three halts uncovered:

1. an agent that **stops while holding the pen** (`WORKING_<me>`) — outside the
   "lack the pen" clause, so nothing told it to keep a waiter armed;
2. a **deliberate or forced stop** mid-shift — a denied action, a blocker, an
   operator "stop" — none of which is `DONE`;
3. `PAUSED`, whose definition said "work suspended, resume on new user scope"
   but never stated that **listening continues** while paused.

Observed incident (2026-07-14): after an action was denied, an agent holding the
pen announced it would "stop and wait" and went passive — conflating *stopping
work* with *stopping listening*. The protocol did not forbid this because the
invariant's precondition excluded pen-holders.

## Decision

Listening ends **only** at `DONE`. Every other halt — finishing a turn, `IDLE`,
`PAUSED`, an interruption, a denied action, a blocker, or **holding the pen with
nothing to do** — suspends *acting*, never *listening*. Whenever an agent halts
while the state is not `DONE`, **including while it holds the pen**, it keeps a
waiter armed (`wait` / `next` / `append --wait` / a headless runner); if it
genuinely cannot host a waiter, it must say so explicitly so a human reactivates
it. A stop is a stop of *acting*, never of *listening*.

`PAUSED` follows the same rule — work is suspended, listening is not. The compact
protocol core and floor stanza carry the invariant within their strict byte
budgets; the fuller enumeration (paused, interrupted, a denied action, holding
the pen) lives in `M8SHIFT.agent-pack.md`, which the pack section already binds.
`DONE` remains the sole state that ends the relay and ends listening.

A bounded or expiring waiter counts as coverage only while that process remains
blocked; it does not become a persistent producer after it returns. Long
off-relay work therefore needs a supervised persistent listener/watcher, and at
every halt an agent with no such supervisor re-arms its waiter. An invoker may
reactivate an agent, a notifier can only alert a human, a foreground watch exists
only while its process is alive, and absent/unknown evidence proves no wake-up
path. A detector never invokes an agent. A notify-only listener is durable
notification coverage but still requires human reactivation.

## Where it binds

The rule is authored once in the embedded protocol templates so that every
`init` regenerates it for every agent and project:

- `PROTOCOL["en"]` — the Listening invariant, with its "lack the pen"
  precondition removed so it covers pen-holders ("even holding the pen").
- the compact floor stanza (`CLAUDE.md` / `AGENTS.md` anchor), rule 3, keeping
  "even holding the pen" and "`DONE` alone ends listening".
- `M8SHIFT.agent-pack.md` — the "Keep listening / idle is not done" section, which
  enumerates every halt (paused, interrupted, a denied action, holding the pen)
  and drops the "do not hold the pen" precondition.
- `docs/en/protocol.md` — the human-readable mirror kept in sync.

## Verification

`test_keep_listening_and_unread_release_guardrails_documented` asserts the
strengthened contract: `PROTOCOL["en"]` contains "ends **only** at `DONE`" and
the floor stanza contains "even holding the pen", alongside the pre-existing
substrings the suite already pins. The core stays within its proxy-token budget
and the stanza within its byte ceiling (`test_protocol_core_within_budget`,
`test_stanza_byte_count_under_hard_ceiling`).

## Advisory enforcement

Runtime and status companions classify `AWAITING_<agent>` attention after the
existing 300-second strict-`>` boundary: invoker coverage is `covered`;
notifier/fresh foreground evidence is `human_resume_needed`; absent evidence is
`stranded`. These verdicts are advisory and never alter routing or claim authority.
