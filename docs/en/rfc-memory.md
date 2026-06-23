# RFC — Shared memory (`M8SHIFT.memory.md` + `remember`)

**Status:** SHIPPED (v3.2.0) · roadmap item "🧠 Shared memory *(next)*" · design validated by an
adversarial panel (3 angles → skeptical synthesis)

## Goal

A durable, append-only note ledger the agents curate by hand, so an agent resumes across
sessions. The turn journal records *what was done*; **memory records what to keep in mind** —
decisions, gotchas, conventions — that outlive a single turn and a single session.

## Non-goals (carried from the README)

No *derived* memory: no dedup, summarize, prune, or ranking. The ledger stays a **dumb,
human-curated record**. No daemon, no second coordination authority — memory is read-only
briefing data and **NEVER feeds the mutex / routing logic** (exactly like the turn journal).

## Surface

- `m8shift.py remember <agent> "<note>"` — append one note. *(write)*
- `recap` gains a **memory headlines** section: the last N notes. *(read)*
- The file is plain markdown — agents may also read it directly. No other read command.

## File — `M8SHIFT.memory.md`

- A sibling artifact (like `M8SHIFT.archive.md`), **gitignored**, created **lazily** on the
  first `remember` (with a one-line header). Absent file ⇒ `recap` skips the section.
- Append-only. One note per line: `- <iso8601Z> <agent>: <note>`.

## Rules

- `remember` runs under `file_lock` (atomic append) but does **NOT** require the pen
  (`claim`): note-taking is passive curation, not the exclusive work window. Any roster agent
  may remember at any time; `file_lock` serializes the append.
- `<agent>` must be in the roster (`need_agent`); `<note>` passes `clean_field` (single line,
  no reserved marker, no `str.splitlines()` boundary — injection-safe).
- `parse_memory(text)` (read-only, mirrors `parse_turns`) → `[{ts, agent, note}]`; `recap`
  shows the last N. Malformed lines are ignored, never crash.

## Backward compatibility

Additive. No memory file ⇒ no change to `recap` or anything else. No LOCK / journal format
change. No new reserved marker (memory lines are plain list items, not `M8SHIFT:*`).

## Resolved by the panel

1. **Pen-gating → NO pen.** `remember` runs under `file_lock` only. The pen gates `M8SHIFT.md`
   (the LOCK + journal: the exclusive *work window* on the shared repo); memory is a different
   file, so the O_EXCL `file_lock` is the right and only mutex. Pen-gating would block notes from
   IDLE/DONE and from the non-holder, and invent a second reason to hold the pen — a second
   coordination authority (non-goal). Provable by construction: `cmd_remember` never calls
   `set_lock`, so memory can never feed routing.
2. **Entry granularity → single line, `clean_field`.** One note per line. A multi-line body would
   need `clean_body` (which allows newlines) and break the one-note-per-line parse; `clean_field`
   forbids every `str.splitlines()` boundary, so a note can never forge a second line.
3. **Agent → required**, positional, `need_agent`-validated against the roster (same gate as
   append/claim). Attribution is the point of a resume ledger; the caller always knows its name.
4. **`recap` → chronological tail** (newest *last*, like the turn recap), default **5** via a new
   `--memory N` knob (`<=0` = all, mirroring `--turns`). A distinct `note(s)` label + per-line
   timestamps disambiguate from the turns section. Newest-first was rejected as a presentation
   inconsistency.
5. **Tags → flat ledger, no `--tag`.** Typed tags beget filter/group/rank — a query layer over the
   dumb record (non-goal). Categories, if wanted, are a free-text `convention:` prefix inside the
   note (plain `clean_field` text, no schema).

**Read surface:** `recap` tail + direct file reads only — no dedicated `memory`/`log` subcommand
(it would duplicate `cat` and invite query/dedup features). `recap` keeps its `load_or_die`
precondition (one entry point); the durable resume path without a relay is reading the file.

**Rejected:** pen-gating; multi-line body; `--tag`; a memory subcommand; seeding at `init`;
special-casing `recap` when `M8SHIFT.md` is absent; a new `M8SHIFT:MEMORY` reserved marker; any
sort/dedup/prune/auto-archive of memory (all import forbidden *derived*-memory logic).
