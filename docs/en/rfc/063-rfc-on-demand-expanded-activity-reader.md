# RFC 063 — On-demand expanded activity reader

- **Status:** implemented (#63, 2026-07-14)
- **Scope:** the core read surface and interactive read-only dashboard.
- **Builds on:** [RFC 061](061-rfc-bounded-adaptive-activity.md).

## Decision

The dashboard uses `e` to toggle the ACTIVITY zone between its compact table and
an expanded reader. `e` is mnemonic, unassigned, and portable across supported
terminals. Expanded mode shows one activity block at a time. Up/down selects the
newer/older block by immutable turn number; left/right pages within a wrapped
done-text when it is taller than the physical activity zone.

Core adds the read-only point lookup `turn NUMBER --json`. Its
`m8shift.turn/1` response contains only the requested immutable turn number,
author, recipient, timestamp, and complete `done` field. It searches the live
journal and archive, returns rc 3 when the turn does not exist, and never changes
relay state.

## Bounded snapshot contract

The status snapshot and its 120-code-point activity projection are unchanged.
Entering expanded mode fetches only the selected turn; moving to another block
fetches only that turn. Automatic status refreshes reuse the immutable fetched
record. Archive I/O therefore occurs only after an explicit expanded-reader
selection, never in the normal snapshot path.

The complete done-text is sanitized for terminal control characters and wrapped,
not truncated. The frame keeps its physical width and height. When the wrapped
text exceeds the available rows, left/right paging makes every line readable
without opening the journal.

## Acceptance criteria

1. `status --json` retains the frozen `m8shift.status/1` shape and bounded text.
2. `turn NUMBER --json` returns the exact complete done-text from live or archived
   history; missing and negative turns fail without mutation.
3. `e` toggles modes, up/down navigates blocks, and left/right reaches all wrapped
   text pages.
4. Expanded and compact layouts preserve frame width and physical height at
   80, 120, and 160 columns.
5. Python 3.8, non-TTY fallback, checksums, and the full suite remain green.
