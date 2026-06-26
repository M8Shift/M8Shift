# M8Shift · Single-file relay protocol — reference (v1)

Read on demand. This companion to `M8SHIFT.protocol.md` (the operational core)
holds the mental model, the full `m8shift.py` command reference, project-adoption
details, and finer mutex/timestamp notes. None of it is needed to *operate* an
existing relay; the core alone is self-sufficient.

---

## 1. Mental model

- **A single living file**: `M8SHIFT.md`. The entire work dialogue is there.
- **A single pen, explicitly acquired**: to work, you **take** the pen via
  `claim` → state `WORKING_<you>`. `claim` is **exclusive** (several agents trying
  at the same time: only one succeeds). You modify the repository **only** while
  you hold the pen.
- **`append` closes your turn**: it is accepted only from `WORKING_<you>`,
  writes the turn and hands off (`AWAITING_<other>`). No `claim` ⇒ no `append`.
- **One pen, explicit recipient**: the active agents take turns — the holder hands the
  pen to any *other* roster member via `--to` (e.g. `claude` → `codex` → `claude` …; with
  3+ agents, to whichever you name). Each hand-off is a numbered *turn* (`TURN`).
- **Poll**: when it is not your turn, you wait (`./m8shift.py wait <you>`,
  ~60 s) then you retry `claim`.

Examples use `claude` and `codex` for readability only. The same protocol works with
`gemini`, `vibe`, or any cooperative agent that can read its anchor, run the CLI, and
respect `claim → work → append`.

---

---

## Timestamps and session metadata (detail)

M8Shift stores timestamps in UTC (`Z`) to keep comparisons stable across agents and
machines. Human-facing commands such as `status`, `recap`, `history`, and `task show`
also print the user's local time next to UTC, prefixed by the timezone name/offset
when available (otherwise `local`). Machine-readable JSON keeps canonical UTC values
only.

`status` also derives two read-only session lines from `M8SHIFT.sessions.jsonl` when
possible: `started` (session start timestamp) and `duration` (elapsed time since
that start, or until close/reset for a finished session). These lines are display
metadata only; they never feed claimability or routing. `status --json` exposes the
same metadata and serializes unavailable values as `null`.

> `expires` carries a date **only** during `WORKING_*` (an agent is working,
> TTL 30 min). It returns to `-` as soon as we are waiting (`AWAITING_*`, `IDLE`,
> `PAUSED`, `DONE`): nobody holds the pen, so there is no staleness to watch.

---

## Concurrency model (detail)

> **Concurrency model (two levels)**:
> 1. **Transitions** serialized by an inter-process lock (`.m8shift.lock`,
>    `O_CREAT|O_EXCL`, with an ownership token): each read-modify-write of the
>    LOCK + atomic write (unique temporary + `os.replace`) is exclusive.
> 2. **Work window** protected by the persistent state `WORKING_<agent>`:
>    `claim` is the only acquisition, and it fails if someone else holds or has
>    already taken the pen. Two simultaneous `claim`s from `IDLE` ⇒ **only one
>    succeeds**; the others must wait. Since we work only after a successful
>    `claim`, no two agents ever modify the repository at the same time.
>
> An abandoned `.m8shift.lock` (killed process) is taken over after 60 s, token
> verified. *Limits*: the lock is **advisory** (a manual edit of `M8SHIFT.md`
> bypasses it); on a network FS (NFS) `O_EXCL`/`rename` are less reliable —
> M8Shift targets a repository on local disk. See also §0/§4 (mandatory claim).

---

## 7. The `m8shift.py` tool

```
./m8shift.py init [--name PROJECT] [--agents a,b,c…] [--lang <code>] [--force]  # (re)generate the kit; --lang = a language BUNDLED in this file (core = en; build more with m8shift-i18n.py)
./m8shift.py status [--for <agent>] [--brief]      # lock + last turn + optional next-action hint
./m8shift.py watch [--for <agent>] [--interval N] [--clear] [--changes-only]  # local read-only live monitor
./m8shift.py doctor [--lint] [--json] [--security] [--contracts] # read-only health/lint/security checks (never repairs or steals the pen)
./m8shift.py contract validate [--strict] [--json] # read-only Stage-4 contract validation
./m8shift.py recap [--turns N] [--memory N] [--tasks N] [--brief]  # read-only briefing: LOCK + last turns + memory + tasks
./m8shift.py peek <agent>  # last handoff addressed to <agent> (rc 3 if not your turn)
./m8shift.py log [--limit N] [--all] [--oneline]  # read-only relay timeline
./m8shift.py history [--limit N] [--oneline] [--json]  # session history (read-only)
./m8shift.py session {list,show,decisions,report} …  # read-only session views + optional Markdown report
./m8shift.py wait <agent> [--once] [--interval N]  # waits for your turn ; --once = 1 check (rc 3 if not your turn)
./m8shift.py next <agent> [--once] [--interval N] [--force] [--resume --reason "..."]  # wait if needed, then claim + peek
./m8shift.py claim <agent> [--force]               # ACQUIRE the pen (exclusive) — from your turn /
                                                  #   IDLE / your own lock ; --force = stale lock ONLY
./m8shift.py append <agent> --to <other> \
     --ask "..." --done "..." [--files a,b] [--body file.md|-] [--allow-large-body] [--wait]  # closes your turn + hands off
./m8shift.py request-turn <agent> --to <holder> --reason "..."  # ask current holder to yield (request ledger only)
./m8shift.py yield-turn <holder> --request N --to <agent>       # accept a cooperative turn request
./m8shift.py decline-turn <holder> --request N --reason "..."   # decline a cooperative turn request
./m8shift.py steer-turn <agent> --from <holder> --request N --force --reason "..."  # redirect idle AWAITING holder
./m8shift.py pause <holder> --reason "..."       # park an open session with no active task (state=PAUSED)
./m8shift.py resume <agent> --reason "..."       # resume PAUSED for a specific agent before claim
./m8shift.py remember <agent> "<note>"  # append a durable memory note (advisory)
./m8shift.py task {add,done,drop,list,show} …  # advisory task ledger (per-agent to-dos)
./m8shift.py release <agent> --to <other> [--force --reason "why"]  # hand off without a body (does NOT re-increment turn)
./m8shift.py done <agent> [--force --reason "why"]  # close the session (state=DONE)
./m8shift.py archive [--keep N]                     # purge old closed turns (never turn #0)
```

- **`claim` first**: you must hold the pen (`WORKING_<you>`) to `append`.
  `claim` is **exclusive** (a single winner if several agents try together).
- `append` is accepted **only from `WORKING_<you>`**; it writes the turn and
  hands off. `--body -` reads the body from stdin; `--body f.md` from a file;
  without `--body`, the turn has only the header. Bodies are capped at 256 KiB
  unless `--allow-large-body` is explicit. Single-line fields (`--ask`, `--done`,
  `--files`, advisory fields, `--reason`, `--note`, etc.) are capped at 64 KiB and
  still reject line breaks and reserved relay markers.
- `--to` must target **a different active agent** (self-hand-off refused; with 3+ agents, name the recipient).
- **Non-blocking** inspection: `status` or `wait <you> --once`. `wait <you>`
  **without** `--once` blocks until your turn — do not use it if you must return
  control to your loop in the meantime.
- **Brief read output**: `status --brief` and `recap --brief` are human-output-only
  compact modes. They are strict subsets of the default human output: no new fields,
  no default-output change. `status --brief` keeps the version line, `holder`,
  `state`, `agents`, `turn`, `since`, `expires`, and the `next` action (plus stale
  or request hints when present); it drops framing, `lang`, `session`, `started`,
  `duration`, `note`, and the last-turn footer. `recap --brief` keeps the version
  line, `holder`, `state`, `agents`, `turn`, `since`, and recent turn summaries; it
  drops framing, `session`, `expires`, `note`, section headings, memory headlines,
  and task headlines.
- **Live operator view**: `watch --for <you> --interval 5` repeats the same
  read-only status view so a terminal can show relay evolution without manually
  re-running `status`. It is a foreground/passive monitor: no `claim`, no handoff,
  no force recovery, no daemon.

---

---

## 8. Adoption by any project (portability)

`m8shift.py` is **self-sufficient**: it embeds this protocol, the `M8SHIFT.md`
template and the anchors. `init` generates relay files, but it does **not** copy
scripts into the target project. The one-line installer handles that by placing
`m8shift.py`, the optional `m8shift-worktree.py` toolbox, and the optional
`m8shift-runtime.py` companion next to each other,
then running `init`. For manual adoption:

```bash
cp /path/to/m8shift.py .          # core relay
cp /path/to/m8shift-worktree.py . # optional: isolated parallel worktrees
cp /path/to/m8shift-runtime.py .  # optional: local presence/inbox/progress companion
./m8shift.py init                 # project name = folder name (otherwise --name)
```

`init`:
- writes `M8SHIFT.protocol.md` (this document) and `M8SHIFT.md` (a fresh IDLE
  lock); `M8SHIFT.md` is **not** overwritten if it already exists (except with
  `--force`) → the state of the ongoing relay is preserved;
- injects at the **top** a "M8Shift relay" block into **each active agent's anchor**
  (by default `CLAUDE.md` and `AGENTS.md`; created if missing), between
  `M8SHIFT:STANZA` markers → **idempotent** re-injection (moves/updates the block
  without duplicating, existing content preserved; the prior file is backed up to
  `<anchor>.m8shift.bak`);
- if `CLAUDE.md` existed but no Codex instruction (`AGENTS.md` or
  `AGENTS.override.md`) existed, automatically creates in `AGENTS.md` a bridge
  asking Codex to read the shared instructions in `CLAUDE.md`. A pre-existing
  Codex anchor is never completed or replaced automatically;
- renames a single `claude.md`/`agents.md` variant to the canonical
  auto-loaded name, including on a case-insensitive FS. Several coexisting
  variants are refused rather than silently merged. If Git is available and the
  variant is tracked, it uses `git mv -f` to also update the index;
- if `AGENTS.override.md` exists, it also synchronizes the stanza there: Codex
  loads this override instead of `AGENTS.md` in the same folder.

### Bootstrap / uptake by the agents

M8Shift is **passive**: it never "calls" any AI. It relies on the convention of each
host tool — **Claude reads `CLAUDE.md`, Codex reads `AGENTS.md`**, and any other active
agent reads its own anchor — at session/execution startup. The bootstrap chain is
therefore:

```mermaid
flowchart LR
    I["m8shift.py init"] --> S["inject the stanza into<br/>each active agent's anchor"]
    S --> R["each agent reads its anchor<br/>at session start"]
    R --> L["applies M8SHIFT.protocol.md<br/>(the wait / claim / work / append loop)"]
```

- **After `init`**: start a new session/execution of the agent. A session
  already open has generally built its instruction chain before the injection.
- **Interactive Codex or `codex exec`**: `AGENTS.md` is loaded if the command
  starts from the project root or one of its subfolders. *Headless* mode is not
  in itself a limit; a cron/CI launched outside the project, however, does not
  discover the anchor.
- **Codex override**: `AGENTS.override.md` masks `AGENTS.md` in the same folder;
  `init` therefore injects the stanza into both when it is present.
- **Codex size**: Codex stacks the instruction files up to a *combined* ceiling
  (`project_doc_max_bytes`, 32 KiB by default) and truncates the file that
  overflows to the remaining byte count. Putting the stanza at the top thus
  keeps it in priority (and a file closer to the cwd takes precedence);
  nevertheless keep the anchors **lightweight**.
- **General limit**: M8Shift cannot force an AI to read anything. Without a
  project root/context, point the agent explicitly to `M8SHIFT.protocol.md`.

Codex reference: https://developers.openai.com/codex/guides/agents-md
