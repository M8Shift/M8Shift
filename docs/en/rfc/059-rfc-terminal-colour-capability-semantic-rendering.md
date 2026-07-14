# RFC 059 — Terminal colour capability and semantic rendering

- **Status:** implemented (#50, 2026-07-14)
- **Scope:** the read-only `m8shift-top.py` dashboard.
- **Builds on:** [RFC 025](025-rfc-status-runtime.md) and
  [RFC 058](058-rfc-go-forward-rfc-discipline.md).

## Decision

The dashboard has one capability detector and one tiered colour emitter for the
brand wordmark and semantic cells. It selects the first applicable tier:

1. `NO_COLOR` present or `TERM=dumb`: plain text, with no SGR escapes;
2. `COLORTERM=truecolor` or `COLORTERM=24bit`: 24-bit `38;2;R;G;B`;
3. `TERM` containing `256color`: deterministic xterm-256 `38;5;N`;
4. otherwise: semantic ANSI-16 slots.

The xterm-256 conversion searches the standard 6×6×6 cube and 24 grayscale
entries by squared RGB distance, breaking a tie by the lower palette index. The
wordmark retains the reviewed overrides M8 Orange → 208 and Shift Purple → 99;
those identity colours are not recomputed.

## Semantic contract

Truecolour cells use the GitHub Dark Dimmed terminal palette so they agree with
the recommended terminal profile. ANSI-16 uses meaning-preserving slots rather
than RGB-nearest matching: a safety green or red must not collapse into gray.

| role | truecolour | xterm-256 | ANSI-16 |
|---|---|---:|---|
| safe / idle / healthy | `#57AB5A` | 71 | green 32 |
| danger / near-limit / stale | `#F47067` | 203 | red 31 |
| elevated / holder / TTL | `#C69026` | 172 | yellow 33 |
| version / information | `#39C5CF` | 80 | cyan 36 |
| live-turn relay accent | `#B083F0` | 141 | magenta 35 |
| structural / unavailable | `#636E7B` | 242 | bright-black 90 |
| state badge | `#CDD9E5` inverse | 253 inverse | bright-white 97 inverse |

Magenta is reserved for the live/next-turn relay arrow. Activity rows and
ordinary content use the terminal foreground; the renderer does not impose a
theme foreground or background. Usage thresholds remain below 0.60 green,
0.60–below 0.85 yellow, and 0.85 or above red.

## Accessibility and compatibility boundary

Colour is redundant decoration. State badges retain their brackets and text;
usage retains labels and percentages; TTL retains its gauge, time, and
`alive`/`stale`; holder and live-turn information retain `✦`, the state name,
and the arrow. Every state therefore remains readable with `NO_COLOR`, a dumb
terminal, monochrome output, or a user-defined ANSI palette.

Styles are applied only after cells are padded. Removing SGR sequences must
leave every rendered line exactly equal to the selected frame width in both
stacked and wide layouts.

## Acceptance criteria

1. Every semantic role is pinned at truecolour, xterm-256, and ANSI-16 tiers.
2. The wordmark keeps truecolour identity and the 208/99 xterm overrides.
3. `NO_COLOR` and `TERM=dumb` emit no SGR while preserving textual/symbolic meaning.
4. Frame fidelity holds at widths 80, 100, and 120 in every tier.
5. The 0.60 and 0.85 usage thresholds and terminal-default ordinary text remain unchanged.
