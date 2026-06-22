# Tutorial — Run your first M8Shift relay

This is a hands-on tutorial. By the end you will have run a complete M8Shift
relay from start to finish in a throwaway folder: you will play one turn as
`claude`, hand off, play one turn as `codex`, watch the strict alternation
happen, then close the session.

You do not need to understand the whole protocol yet. Just follow the steps in
order and compare each console output with the **Expected result** block below
it. If something looks different, read the **If you see something else** note.

> Tip: the `m8shift.py` tool prints its own messages in French. That is normal —
> the words you type (commands, flags, states) are the same everywhere, and
> this tutorial explains every line in English. You are reading the output
> exactly as a real run produces it.

**What you need:** a terminal, Python 3, and the single file `m8shift.py`.
**Time:** about 10 minutes.

---

## Step 1 — Create a toy folder

We will work in a temporary folder so nothing on your machine is touched. M8Shift
is a single self-contained file, so a toy project is just an empty directory.

```bash
mkdir /tmp/cowork-toy
cd /tmp/cowork-toy
```

**Expected result:** no output. You now have an empty folder and your terminal
is inside it.

---

## Step 2 — Copy `m8shift.py` into the folder

M8Shift ships as one file. To adopt it in any project you copy that one file in.

```bash
cp /path/to/m8shift.py .
chmod +x m8shift.py
```

Replace `/path/to/m8shift.py` with the real location on your machine.

**Expected result:** no output. `ls` should now show a single `m8shift.py`.

**If you see `No such file or directory`:** the source path is wrong. Find the
file first with `find ~ -name m8shift.py 2>/dev/null` and use the path it
prints.

---

## Step 3 — Initialize the relay with `init`

The `init` command generates everything M8Shift needs in this folder: the shared
work file `M8SHIFT.md`, the protocol reference `M8SHIFT.protocol.md`, and the
anchor files (`CLAUDE.md`, `AGENTS.md`) that let each agent bootstrap itself.

```bash
./m8shift.py init --name hello-cowork
```

**Expected result:**

```text
✓ cowork init — projet « hello-cowork » dans /tmp/cowork-toy
  • M8SHIFT.protocol.md: écrit
  • M8SHIFT.md: écrit (projet « hello-cowork », verrou IDLE)
  • CLAUDE.md: fichier créé
  • AGENTS.md: fichier créé
Démarrer : ./m8shift.py claim claude  (puis travaille, puis ./m8shift.py append claude --to codex --ask "…" --done "…")
Amorçage : démarre une nouvelle session/exécution de Claude et Codex pour recharger les ancrages.
```

In English: the protocol was written, `M8SHIFT.md` was created with a brand-new
lock in state `IDLE`, and the two anchor files were created. The lock starts at
`IDLE` because nobody holds the pen yet.

**If you see `M8SHIFT.md: préservé`:** you already ran `init` here before, so the
existing relay state was kept (this is on purpose). For this tutorial, start
clean with `./m8shift.py init --name hello-cowork --force`.

---

## Step 4 — Look at the lock inside `M8SHIFT.md`

The heart of M8Shift is one block called the **LOCK** at the top of `M8SHIFT.md`.
It is a cooperative mutex: a few `field: value` lines that say who, if anyone,
holds the pen. Open `M8SHIFT.md` in any editor, or print the top of it:

```bash
head -20 M8SHIFT.md
```

**Expected result (the lock part):**

```text
<!-- M8SHIFT:LOCK:BEGIN -->
holder:   none
state:    IDLE
turn:     0
since:    2026-06-21T13:14:37Z
expires:  -
note:     session initialisée, aucun tour ouvert
<!-- M8SHIFT:LOCK:END -->
```

What each field means:

- `holder` — who holds the pen right now. `none` means nobody does.
- `state` — the current state. `IDLE` means the relay is free to start.
- `turn` — the number of the last closed turn. `0` is the seed turn.
- `since` — when this state began (ISO-8601 UTC).
- `expires` — the stale-lock deadline. It only carries a date while someone is
  `WORKING_*`; otherwise it is `-`.
- `note` — a short human-readable memo.

You never edit this block by hand — the `m8shift.py` commands rewrite it for you.
The markers `M8SHIFT:LOCK:BEGIN` and `M8SHIFT:LOCK:END` are how the tool finds it.

---

## Step 5 — Check the status with `status`

`status` is the read-only way to ask "what is the lock saying?". It never
blocks and never changes anything, so it is always safe to run.

```bash
./m8shift.py status
```

**Expected result:**

```text
── LOCK ───────────────────────────────
  holder   none
  state    IDLE
  turn     0
  since    2026-06-21T13:14:37Z
  expires  -
  note     session initialisée, aucun tour ouvert
── dernier tour: #0 par system
```

The last line confirms the only turn so far is the seed turn `#0`, posted by
`system`. Nobody has played yet. Good — it is time for `claude` to go first.

---

## Step 6 — As `claude`, confirm it is your turn with `wait --once`

Before taking the pen, an agent checks whether it is allowed to. `wait <agent>
--once` does exactly one non-blocking check and exits. Return code `0` means
"go ahead"; return code `3` means "not yet".

```bash
./m8shift.py wait claude --once
```

**Expected result:**

```text
✓ libre (IDLE) — `./m8shift.py claim claude` pour acquérir le stylo.
```

In English: the relay is free (`IDLE`), so `claude` may now acquire the pen.

**If you see `… pas ton tour`:** that is the return-code-3 case — it is not your
turn. At this point in the tutorial it should say `IDLE`. If it does not, you
probably already played a turn; re-run `init --force` (Step 3) to reset.

---

## Step 7 — As `claude`, take the pen with `claim`

`claim` acquires the pen exclusively. After this, the state becomes
`WORKING_CLAUDE` and you — and only you — may modify the project. If two agents
ran `claim` at the same moment, only one would win; the other would be told it
is not its turn.

```bash
./m8shift.py claim claude
```

**Expected result:**

```text
✓ verrou pris par claude (expire 2026-06-21T13:44:37Z).
```

In English: the pen is now held by `claude`. Notice the `expires` time — it is
set 30 minutes ahead. That is the guardrail: if `claude` ever crashed holding
the pen, the lock would become stale after that deadline and could be reclaimed.

---

## Step 8 — As `claude`, do some real work

Now that you hold the pen, you do the actual work in the project. For this
tutorial, make a tiny dummy change:

```bash
echo "hello from claude" > hello.txt
```

**Expected result:** no output. You created `hello.txt`. In a real project this
is where you would write code, edit files, run tests — anything. The rule is
simply: **only work while you hold the pen.**

---

## Step 9 — As `claude`, record your turn and hand off with `append`

`append` closes your turn: it writes a numbered turn block into `M8SHIFT.md` and
hands the pen to the other agent. `append` is only accepted while you hold the
pen, which is what guarantees that the work window itself was exclusive — not
just the journal write.

```bash
./m8shift.py append claude --to codex \
    --ask "review my note" \
    --done "added hello.txt" \
    --files hello.txt
```

- `--to codex` — hand off to the other agent (handing off to yourself is
  refused: strict alternation).
- `--ask` — what you want `codex` to do next, written so it is actionable.
- `--done` — what you just did.
- `--files` — files you touched.

**Expected result:**

```text
✓ tour 1 ecrit par claude, main passee a codex.
```

In English: turn 1 was written by `claude`, and the pen was handed to `codex`.

---

## Step 10 — See the alternation in `status`

Look at the lock again. It should now point at `codex`.

```bash
./m8shift.py status
```

**Expected result:**

```text
── LOCK ───────────────────────────────
  holder   codex
  state    AWAITING_CODEX
  turn     1
  since    2026-06-21T13:14:37Z
  expires  -
  note     tour 1 pose par claude, en attente de codex
── dernier tour: #1 par claude
```

What changed: `holder` is now `codex`, `state` is `AWAITING_CODEX` (it is
codex's turn), `turn` advanced to `1`, and `expires` went back to `-` because
nobody is actively working — the relay is waiting. This is the strict
alternation in action: claude played, so now it is codex's turn, never claude's
again until codex hands back.

---

## Step 11 — As `codex`, check and take the pen

Now switch roles and play as `codex`. Same loop: check, then claim.

```bash
./m8shift.py wait codex --once
./m8shift.py claim codex
```

**Expected result:**

```text
✓ à toi (AWAITING_CODEX) — `./m8shift.py claim codex` pour acquérir le stylo.
✓ verrou pris par codex (expire 2026-06-21T13:44:37Z).
```

In English: the first line says it is codex's turn; the second confirms codex
now holds the pen (state `WORKING_CODEX`).

---

## Step 12 — As `codex`, record a turn and hand back

`codex` does its work (we will skip a dummy edit this time) and then hands the
pen back to `claude`. When you have nothing to ask, set `--ask "—"`.

```bash
./m8shift.py append codex --to claude \
    --ask "—" \
    --done "reviewed, looks good" \
    --files hello.txt
```

**Expected result:**

```text
✓ tour 2 ecrit par codex, main passee a claude.
```

In English: turn 2 was written by `codex`, and the pen went back to `claude`.
You have now seen a full round trip: claude → codex → claude.

---

## Step 13 — Inspect the full alternation

Check the status one more time to confirm the hand-back.

```bash
./m8shift.py status
```

**Expected result:**

```text
── LOCK ───────────────────────────────
  holder   claude
  state    AWAITING_CLAUDE
  turn     2
  since    2026-06-21T13:14:37Z
  expires  -
  note     tour 2 pose par codex, en attente de claude
── dernier tour: #2 par codex
```

The state is back to `AWAITING_CLAUDE`: it is claude's turn again. Each hand-off
incremented `turn` (now `2`), and each turn was recorded as an immutable block
in `M8SHIFT.md`. Open `M8SHIFT.md` and scroll down — you will see three turn
blocks: `#0 system`, `#1 claude`, `#2 codex`, each wrapped between
`M8SHIFT:TURN <n> <agent> BEGIN` and `END` markers.

---

## Step 14 — Try `archive` to keep `M8SHIFT.md` short

Over a long session `M8SHIFT.md` would grow. `archive` moves old, already-closed
turns out to `M8SHIFT.archive.md`, keeping the most recent ones (and always the
seed turn `#0`) in the live file.

```bash
./m8shift.py archive --keep 6
```

**Expected result:**

```text
rien a archiver (2 tour(s) archivable(s), keep=6).
```

In English: nothing to archive — you only have 2 archivable turns and you asked
to keep 6. That is exactly right; archiving only kicks in once the live file has
more turns than `--keep`. You have now seen the command and know it is safe.

---

## Step 15 — Close the session with `done`

When the relay is finished, the holder closes it with `done`. The pen is
released and the state becomes `DONE`. You currently hold the pen as `claude`
(from Step 13), so you can close directly:

```bash
./m8shift.py claim claude
./m8shift.py done claude
```

**Expected result:**

```text
✓ verrou pris par claude (expire 2026-06-21T13:44:37Z).
✓ session DONE.
```

Check the final status:

```bash
./m8shift.py status
```

**Expected result:**

```text
── LOCK ───────────────────────────────
  holder   none
  state    DONE
  turn     2
  since    2026-06-21T13:14:38Z
  expires  -
  note     session close par claude
── dernier tour: #2 par codex
```

The relay is closed. `state` is `DONE` and `holder` is `none`. No more turns are
expected. You can delete the toy folder whenever you like:

```bash
cd ..
rm -rf /tmp/cowork-toy
```

Congratulations — you ran a complete M8Shift relay end to end.

---

## What you learned

- **The pen is a cooperative mutex.** Only one agent holds it at a time; you
  work only while you hold it.
- **The LOCK block is the single source of truth.** Its `holder`, `state`,
  `turn`, `since`, `expires`, and `note` fields tell you whose turn it is.
- **The core loop is `status` → `wait --once` → `claim` → work → `append`.**
  `claim` takes the pen exclusively; `append` records your turn and hands off.
- **Strict alternation is enforced.** claude → codex → claude …, one numbered
  turn at a time, and a closed turn is immutable.
- **States you saw:** `IDLE` (free), `WORKING_CLAUDE` / `WORKING_CODEX` (someone
  is working), `AWAITING_CLAUDE` / `AWAITING_CODEX` (waiting for that agent),
  `DONE` (session closed).
- **Housekeeping:** `archive` keeps `M8SHIFT.md` short; `done` closes the relay.

---

## Next steps

Now that the mechanics make sense, go deeper:

- **How-to guides** — task-focused recipes (recover a stale lock with
  `claim --force`, write a turn body with `--body`, hand off without a turn
  using `release`, adopt M8Shift in an existing project). See the how-to docs
  alongside this file.
- **Reference** — the full protocol and command reference:
  [`M8SHIFT.protocol.md`](../../M8SHIFT.protocol.md) for the protocol, and the
  reference doc for every command, flag, lock field, and state.
- **Read the protocol once.** Before you run M8Shift with real agents, read
  `M8SHIFT.protocol.md` §0 (the copy-paste loop) so each agent can operate on its
  own.
