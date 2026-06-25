# RFC — `claim --check` (advisory file-overlap probe)

**Status:** SHIPPED (v3.3.0) · roadmap item "🧭 `claim --check`" · design validated by an
adversarial panel (3 angles → skeptical synthesis)

## Goal

A **read-only, advisory** pre-claim probe: before you take the pen, see whether the files you
are about to touch were recently changed by the other agent, so you review/integrate first
instead of clobbering work. It **never takes the pen and never mutates anything** — it does not
grant a concurrent work window (that would be the degree-2 lease, an explicit non-goal).

## Non-goals (carried from the README)

No lease, no enforcement, no daemon. `--check` does not block or alter a real `claim`; it is a
heads-up over data M8Shift already stores (the `files:` field of past turns). No new authority:
overlap NEVER feeds the mutex/routing — it is printed, nothing more.

## Surface

- `m8shift.py claim <agent> --check [--files a,b,c]` — read-only. Prints:
  1. **claim-readiness** (mirrors `wait --once`: it's your turn / free / DONE / not yet), and
  2. a **file-overlap advisory** — which of your `--files` appear in recent turns' `files:`
     fields, naming the turn # and author.
- Without `--files`: a "what's hot" briefing — the distinct files touched across the window.

## Rules

- `--check` returns **before any LOCK read-for-write / mutation**: it calls `load_or_die()`
  (read), computes the report, prints, and returns. It is provably incapable of taking the pen
  (no `set_lock`, no state change). Combining `--check` with `--force` is a no-op (still read-only).
- Overlap source: each recent turn's `files:` CSV (via `parse_turns`), excluding `—`/empty.
- `<agent>` is `need_agent`-validated; `--files` passes `clean_field` (single line, injection-safe).
- Output is advisory; the file ledger/journal is never modified.

## Resolved by the panel

1. **rc → readiness only** (`0` = you may claim, `3` = not yet), byte-identical to `wait --once`;
   hard errors (bad agent / bad LOCK / bad `--files`) are `1`. **Overlap NEVER changes the rc.**
   A distinct "overlap" rc would make overlap a second signal scripts branch on — the first step
   toward enforcement/lease (overlap feeding control flow), an explicit non-goal. Reusing `wait
   --once`'s two codes keeps existing claim-gate wrappers working unchanged.
2. **Window → since your last authored turn** (what others touched since you last worked), with a
   `--turns N` override (last N). Scanning all turns would re-flag your own files and turns you
   already integrated; first-timer (no prior turn) → all unarchived. Living file only (no ARCHIVE).
3. **`--files` optional.** Without it, a "what's hot" briefing of files touched in the window; with
   it, a targeted overlap report. At handoff you often don't have a file list yet.
4. **Matching → case-sensitive exact** on trimmed CSV tokens (no basename/path-prefix/glob). The
   `files:` field is free text; clever normalization over-reports (`src/u.py` vs `test/u.py`) and
   turns the probe into a path-inference engine (creeping authority). Exact match under-reports
   (a cheap false *negative*) rather than over-reports (a costly false *positive* that erodes trust).
   The `—` placeholder and empty tokens are dropped on both sides.
5. **Form → `--check` flag on `claim`** dispatching to a separate read-only `cmd_claim_check`
   (early return, before `file_lock`), not a new subcommand.

**No-pen guarantee (provable by control flow):** the `--check` dispatch is the *first* statement
of `cmd_claim`, so the mutating `with file_lock()` body is unreachable; `cmd_claim_check` never
names `file_lock`/`set_lock`/`write` and never reads `--force`; `--files` is a display filter,
never persisted. Overlap is computed, printed, discarded.

**Rejected:** an overlap rc; sharing a deeper `if` inside `cmd_claim`; basename/glob normalization;
requiring `--files`; an `--all`/ARCHIVE window; any lease/TTL/marker written by `--check`.
