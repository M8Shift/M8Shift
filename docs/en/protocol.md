# M8Shift · Single-file relay protocol (v1)

Shared instruction for the **active agents** — a roster of two or more (by default
**Claude** and **Codex**) — to cooperate through a single
`M8SHIFT.md` file, in strict alternation (mutex), with periodic polling. Portable:
this protocol is identical in every project; only the title of `M8SHIFT.md`
changes.

Read it **once at the start of a session** as soon as you see a `M8SHIFT.md` at
the root of a project. You are **one of the active agents** declared in the
`agents:` field of `M8SHIFT.md` (by default `claude` and `codex`) — identify yourself
by your anchor file.

---

## 0. TL;DR — the self-contained loop

You have just arrived in the project and you see a `M8SHIFT.md`: here is the
complete, copy-pasteable loop, **no other instruction is required**. `<you>` is your
own agent name and `<other>` is the agent you hand the pen to — any *other* member of
the `agents:` roster (with the default `claude`/`codex` pair, simply the other one).

```bash
# Recommended single-step resumption: waits if needed, then claims + prints the
# latest handoff addressed to you.
./m8shift.py next <you>

# 1. Am I expected? (NON-blocking commands)
./m8shift.py status --for <you>     # read the `state` field + your next action
./m8shift.py wait <you> --once      # rc 0 = your turn (or DONE = stop) ; rc 3 = not yet

# 2. ACQUIRE the pen BEFORE working (EXCLUSIVE acquisition: when several agents
#    try at the same time, only one succeeds):
./m8shift.py claim <you>           # rc 0 = you hold the pen ; rc != 0 = not your turn
#    • If claim SUCCEEDS: read the `ask:` that <other> left you in the last
#      turn (at IDLE startup / turn 0, nothing to honour), do the work in the
#      repository, THEN record your turn and hand off:
./m8shift.py append <you> --to <other> \
    --ask "what you expect from the other" \
    --done "what you just did" \
    --files file1,file2
# Optional guardrail: add `--wait` to stay in the loop until your next turn or DONE.
#    • If claim FAILS: it is not (or no longer) your turn → go back to waiting.

# 3. Not your turn: touch NOTHING. Block until your turn, then resume at 2:
./m8shift.py wait <you>             # poll every ~60 s (--interval N)
```

Golden rule: **you work and write only if you have acquired the pen via
`claim`.** `claim` is exclusive; `append` is accepted only if you hold the
pen. Everything else in this document is just the detail of this loop.

Loop guardrail: do **not** stop with the relay still active. Before ending your
agent turn, run `status --for <you>` (or keep using `next <you>`). If the state is
not `DONE`, either finish your own `WORKING_<you>` state with `append`/`done`, or
keep waiting for your next turn.

> The protocol makes you self-sufficient *once you are running*. In an interactive UI
> (VS Code, …) a human still resumes you between turns — `wait` blocks a process, it
> does not wake your chat UI. Fully hands-off relays need a headless runner, not a
> change to this protocol.

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

## 2. The LOCK block (the mutex)

Delimited by `<!-- M8SHIFT:LOCK:BEGIN -->` … `<!-- M8SHIFT:LOCK:END -->`.
Fields (one `key: value` per line, easy to `grep`):

| field     | values | meaning |
|-----------|---------|------|
| `holder`  | an active agent \| `none` | **pen holder** while `WORKING_*`; **awaited (baton-owner)** agent while `AWAITING_*` |
| `state`   | `IDLE` \| `WORKING_<X>` \| `AWAITING_<X>` \| `DONE` | current state (`<X>` = an active agent, uppercased) |
| `agents`  | CSV, e.g. `claude,codex` | the active roster (all declared agents, ≥2); default `claude,codex` |
| `lang`    | language tag | language of generated files / runtime messages when available |
| `session` | session id | current session id, also recorded in `M8SHIFT.sessions.jsonl` |
| `turn`    | integer | number of the last closed turn |
| `since`   | ISO-8601 UTC | since when this state has lasted |
| `expires` | ISO-8601 UTC \| `-` | anti-deadlock takeover deadline (TTL 30 min) |
| `note`    | short text | readable memo |

M8Shift stores timestamps in UTC (`Z`) to keep comparisons stable across agents and
machines. Human-facing commands such as `status`, `recap`, `history`, and `task show`
also print the user's local time next to UTC. Machine-readable JSON keeps canonical
UTC values only.

> `expires` carries a date **only** during `WORKING_*` (an agent is working,
> TTL 30 min). It returns to `-` as soon as we are waiting (`AWAITING_*`, `IDLE`,
> `DONE`): nobody holds the pen, so there is no staleness to watch.

**Reading the states** (`<X>` is an active agent — by default `claude`/`codex`):
- `AWAITING_<X>` → it is `<X>`'s turn to play (the other agents wait).
- `WORKING_<X>` → `<X>` holds the pen and is working (the others wait, touch nothing).
- `IDLE` → nobody has the hand, the first who has something to say starts.
- `DONE` → session closed, no further relay expected.

---

## 3. Format of a turn

```
<!-- M8SHIFT:TURN <n> <agent> BEGIN -->
- from:    <agent>           # an active agent
- to:      <agent|none>      # to whom you hand off
- ask:     <what you expect from the recipient, precise and actionable>
- done:    <what you just did>
- files:   <files touched, comma-separated>
- handoff: <agent|none>      # = to ; deliberate redundancy, grep-friendly
<blank line>
<free body: explanations, questions, code blocks, lists>
<!-- M8SHIFT:TURN <n> <agent> END -->
```

Rules:
- A **closed** turn (`END` set) is **immutable**. To react, you open the next
  turn. Never retroactive rewriting.
- `ask` must be actionable: the recipient must be able to start without asking
  you again. If you expect nothing (just an FYI), put `ask: —`.
- Keep a turn **bounded**: if it exceeds ~150 lines or several topics, split it
  into several successive turns (one topic = one turn).

---

## 4. Work cycle (each agent's loop)

```
loop:
  1. read LOCK (status / wait)
  2. if state == AWAITING_<me> or IDLE:
       a. CLAIM  : ./m8shift.py claim <me>   → state=WORKING_<ME>, expires=now+30min
                   EXCLUSIVE: if someone else has taken the pen in the meantime,
                   claim FAILS → go to 3.
       b. WORK in the repository (while you hold the pen, you alone)
       c. APPEND  : ./m8shift.py append <me> --to <other>
                   writes my turn <turn+1>, state=AWAITING_<OTHER>
  3. else (WORKING_<other> or AWAITING_<other>):
       wait ~60 s (wait), go back to 1
  4. if state == DONE: exit
```

In practice: `claim` **acquires** the pen (exclusive), `append` **closes** your
turn and hands off, `wait` waits for your turn. The explicit acquisition before
working is what guarantees that a single agent modifies the repository at a time.

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

## 5. Anti-deadlock (stale lock)

If an agent crashes while holding the pen, the lock would stay stuck.
Guardrail:
- on CLAIM, we set `expires = now + 30 min`;
- if you see `state == WORKING_<other>` **and** `now > expires`, the lock is
  **stale**: take it over with `./m8shift.py claim <you> --force`, then open a
  turn noting the takeover (`done: takeover after stale lock from <other>`);
- **the tool enforces the rule**: `--force` is **refused** on a still-valid
  lock. You therefore cannot steal the pen from an active agent (this is
  intentional);
- you can **refresh your own** lock before it expires: `./m8shift.py claim
  <you>` when you already hold it resets `expires` to +30 min. For a long-running
  wrapper/agent turn, use a manual heartbeat at least **5 minutes before**
  expiration (with the default TTL, refresh when 25 minutes have elapsed);
- `release` and `done` are **baton-owner** admin ops: they act if you are the `holder`
  (pen holder while `WORKING_*`, or the awaited agent while `AWAITING_*`) or if nobody
  holds it — they do **not** require an active `claim`, unlike `append` (the only *work*
  write, which needs `WORKING_<you>`); `--force` overrides, reserved for recovery.

---

## 6. Keeping it bounded over time (bounded length)

`M8SHIFT.md` must not grow indefinitely:
- keep in `M8SHIFT.md` the `LOCK` block + the **~6 last turns**;
- `./m8shift.py archive --keep 6` moves the older turns (already closed) to
  `M8SHIFT.archive.md` (append), without ever touching the lock or the last open
  turn.
- The archive can be consulted but is **never** re-read by the loop: only the
  living part of `M8SHIFT.md` drives the relay.
- Session starts/closes are recorded separately in `M8SHIFT.sessions.jsonl`; this
  ledger is append-only and is folded by `history`, never by the mutex/routing loop.

---

## 7. The `m8shift.py` tool

```
./m8shift.py init [--name PROJECT] [--agents a,b,c…] [--lang <code>] [--force]  # (re)generate the kit; --lang = a language BUNDLED in this file (core = en; build more with m8shift-i18n.py)
./m8shift.py status [--for <agent>]                # lock + last turn + optional next-action hint
./m8shift.py watch [--for <agent>] [--interval N] [--clear] [--changes-only]  # local read-only live monitor
./m8shift.py doctor [--lint] [--json]              # read-only health/lint checks (never repairs or steals the pen)
./m8shift.py history [--limit N] [--oneline] [--json]  # session history (read-only)
./m8shift.py wait <agent> [--once] [--interval N]  # waits for your turn ; --once = 1 check (rc 3 if not your turn)
./m8shift.py next <agent> [--once] [--interval N] [--force]  # wait if needed, then claim + peek
./m8shift.py claim <agent> [--force]               # ACQUIRE the pen (exclusive) — from your turn /
                                                  #   IDLE / your own lock ; --force = stale lock ONLY
./m8shift.py append <agent> --to <other> \
     --ask "..." --done "..." [--files a,b] [--body file.md|-] [--wait]  # closes your turn + hands off
./m8shift.py release <agent> --to <other> [--force]  # hand off without a body (does NOT re-increment turn)
./m8shift.py done <agent> [--force]                 # close the session (state=DONE)
./m8shift.py archive [--keep N]                     # purge old closed turns (never turn #0)
```

- **`claim` first**: you must hold the pen (`WORKING_<you>`) to `append`.
  `claim` is **exclusive** (a single winner if several agents try together).
- `append` is accepted **only from `WORKING_<you>`**; it writes the turn and
  hands off. `--body -` reads the body from stdin; `--body f.md` from a file;
  without `--body`, the turn has only the header.
- `--to` must target **a different active agent** (self-hand-off refused; with 3+ agents, name the recipient).
- **Non-blocking** inspection: `status` or `wait <you> --once`. `wait <you>`
  **without** `--once` blocks until your turn — do not use it if you must return
  control to your loop in the meantime.
- **Live operator view**: `watch --for <you> --interval 5` repeats the same
  read-only status view so a terminal can show relay evolution without manually
  re-running `status`. It is a foreground/passive monitor: no `claim`, no handoff,
  no force recovery, no daemon.

---

## 8. Adoption by any project (portability)

`m8shift.py` is **self-sufficient**: it embeds this protocol, the `M8SHIFT.md`
template and the anchors. To adopt the relay in a project:

```bash
cp /path/to/m8shift.py .          # copy the only file needed
./m8shift.py init                 # project name = folder name (otherwise --name)
```

`init`:
- writes `M8SHIFT.protocol.md` (this document) and `M8SHIFT.md` (a fresh IDLE
  lock); `M8SHIFT.md` is **not** overwritten if it already exists (except with
  `--force`) → the state of the ongoing relay is preserved;
- injects at the **top** a "Co-work relay" block into **each active agent's anchor**
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
