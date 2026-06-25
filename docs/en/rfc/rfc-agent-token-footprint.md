# RFC — Reducing the per-session agent token footprint

- **Status:** proposed
- **Scope:** cut the tokens M8Shift makes each agent read per session, without
  changing the one-pen mutex, the turn journal, or any command semantics.
- **Core invariant:** this is a *packaging/footprint* change only. The protocol
  meaning, the LOCK, the append-only journal, and every command behavior stay
  byte-for-byte identical. No information is deleted — only relocated to on-demand
  reference.

## Problem

Every agent that joins a relay pays a fixed token cost just to *know how to
participate*, before doing any work. Measured on the live dogfooding relay
(engine v3.18.3):

| Surface | Bytes | ~tokens | Read cadence |
|---------|------:|--------:|--------------|
| `M8SHIFT.protocol.md` | 19370 | ~4842 | once per session (dominant) |
| `M8SHIFT.md` | 5580 | ~1395 | ~every turn (grows with turns) |
| `CLAUDE.md` | 2830 | ~707 | once per session |
| `recap` output | 2134 | ~533 | per turn when called |
| `status` output | 580 | ~145 | ~every turn |
| `log` output | 493 | ~123 | per turn when called |

The protocol document dominates. Broken down by section:

| Protocol section | ~tokens | Needed to *operate* a session? |
|------------------|--------:|--------------------------------|
| §0 TL;DR — the self-contained loop | ~908 | yes (essential) |
| §8 Adoption by any project (portability) | ~898 | no — one-time *adoption*, not per-session |
| §7 The `m8shift.py` tool (full reference) | ~813 | no — discoverable via `--help` |
| §2 The LOCK block | ~584 | yes |
| §4 Work cycle | ~457 | yes |
| §5 Anti-deadlock (stale lock) | ~309 | yes |
| §1 Mental model | ~271 | partly |
| §3 Format of a turn | ~222 | yes |
| §6 Keeping it bounded over time | ~142 | partly |

About **54% of the protocol (~2619 tokens: §0 partial + §7 + §8)** is adoption or
full-command reference that an agent *operating an existing relay* does not need
in front of it every session. The genuinely operational core (loop + LOCK + turn
format + work cycle + anti-deadlock) is **~1800 tokens**.

The recurring per-turn cost is `status` (~145) plus re-reading the growing
`M8SHIFT.md` (~1395 and climbing); `archive` already bounds the latter but cadence
is undocumented.

## Decision

Split the protocol the relay *bundles for agents* from the protocol the *repo
documents for humans/adopters*, and inject only the operational core.

1. **Operational core** — a compact stanza (target **≤ 2000 tokens**) containing
   only what an agent needs to participate: the self-contained loop, the LOCK
   block, the turn format, the work cycle, and the stale-lock rule. `init` injects
   this core into the project's `M8SHIFT.protocol.md` (or keeps a one-line pointer
   to it), instead of the full ~4842-token document.
2. **Reference appendix** — portability/adoption (§8) and the full `m8shift.py`
   command reference (§7) move to repo docs (`docs/en/protocol-reference.md`),
   read on demand. The tool's own `--help` already covers the command reference at
   zero standing cost.
3. **Optional `--brief` output** — a compact mode for `status`/`recap` that drops
   decorative framing, for agents that poll frequently.
4. **Documented archive cadence** — a one-line guideline (e.g. `archive` when the
   living journal exceeds N turns) so `M8SHIFT.md` re-read cost stays bounded.

Source of truth stays `PROTOCOL["en"]` in `m8shift.py`; the core/reference split is
expressed there, and `gen_docs.py` regenerates both the bundled core and the
reference doc, so they can never drift (the existing in-sync test extends to cover
the split).

## Non-goals

- No change to mutex semantics, LOCK format, turn journal, or any command behavior.
- No deletion of protocol content — the full text stays available as reference.
- No LLM/lossy summarization; the core is a hand-authored subset, deterministic.
- No new network, daemon, or second authority.
- Not a docs-prettiness change; success is measured in tokens, not aesthetics.

## Acceptance criteria

- The bundled operational core is **≤ 2000 tokens** and contains the loop, LOCK,
  turn format, work cycle, and stale-lock rule.
- The full reference (portability + command reference) remains discoverable from
  the core via an explicit pointer and lives in repo docs.
- `init` injects the core, not the full document; a fresh relay's
  `M8SHIFT.protocol.md` measures ≤ 2000 tokens.
- Protocol *meaning* is unchanged: an agent following only the core can still run
  the full `claim → work → append`, handle a stale lock, and stay bounded.
- A size-budget test asserts the core stays under budget and the in-sync test
  covers core ↔ reference regeneration.
- `--brief` output (if adopted) is a strict subset of the full output; default
  output is unchanged.

## Measurement method (for re-analysis)

Token figures use `bytes / 4` as a portable proxy. Re-run with the engine pointed
at the relay root (`M8SHIFT_ROOT=<relay> python3 m8shift.py status|recap|log`) and
`wc -c` on `M8SHIFT.protocol.md` / `M8SHIFT.md`. The post-implementation re-analysis
should report the new per-session core size and confirm the ≤ 2000-token budget.
