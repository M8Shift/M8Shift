# User guide — operating the M8Shift relay in VS Code

> **Note Claude —** Operational guide: how to actually launch a Claude ⇄ Codex
> relay from the VS Code extensions. For kit installation (`cp m8shift.py` +
> `init`), see the [README](../../README.md); for the protocol itself, see
> [`M8SHIFT.protocol.md`](../M8SHIFT.protocol.md).

In VS Code, **the Claude and Codex panels *are* the agents**. The whole job comes
down to two gestures: pointing them at the **right project root**, and **starting
fresh conversations** after `init`.

This guide is task-first. Do the steps in order; each one tells you what you
should see before moving on.

---

## What you need first

- `m8shift.py` deployed at the project root, and `python3 m8shift.py init` already
  run (this generates `M8SHIFT.md`, `M8SHIFT.protocol.md`, `CLAUDE.md`, and
  `AGENTS.md`).
- Both VS Code extensions installed: **Claude Code** and **Codex**.

If you have not run `init` yet, do that first — see the
[README](../../README.md). The steps below assume the four files exist.

---

## Step 1 — Open one VS Code window per repository

The nested instruction files (`CLAUDE.md` / `AGENTS.md`) only load reliably when
the window is opened **exactly on the repository root**. A window opened too high
in the tree (for example `/home/user/Documents/Code`) does **not** guarantee
they load.

To open **Example Project**:

1. Choose `File → New Window`.
2. Choose `File → Open Folder…`.
3. Open exactly this path:

   ```text
   /home/user/Documents/Code/Books and Journals/Example Project
   ```

**Expected result:** a VS Code window whose root is the repository itself, with
`M8SHIFT.md`, `CLAUDE.md`, and `AGENTS.md` visible at the top level of the
Explorer.

Open **a separate window** for each other repository (for example GSE), each on
its own root. The rule is: one repository = one window.

> **If `M8SHIFT.md` is not at the top of the Explorer, then** you opened a parent
> folder. Close the window and reopen the folder on the exact repository root.

---

## Step 2 — Reload after `m8shift.py init`

A session that was already open knows nothing about the anchors that `init` just
injected. So, right after you run `init`:

1. Press `Cmd+Shift+P` to open the Command Palette.
2. Run `Developer: Reload Window`.
3. Start a **new conversation** in each UI (do not reuse an old thread).

**Expected result:** both panels reload, and the next conversation you open in
each one reads its anchor file fresh.

> **Why this matters:** Codex loads `AGENTS.md` when a **new thread** starts;
> Claude loads `CLAUDE.md` at the start of **each session**. *Merely opening a
> file does not necessarily reload the instructions.*
>
> Refs: [Codex — AGENTS.md](https://developers.openai.com/codex/guides/agents-md) ·
> [Claude Code — memory](https://code.claude.com/docs/en/memory)

---

## Step 3 — Open both UIs in the same window

Work inside the **same window** (here, Example Project):

1. Open the **Claude Code** panel (the ✱ icon).
2. Open the **Codex** panel.
3. Place the panels side by side if you like.
4. For **Codex**, use **Agent mode** so it can read, edit, and run commands
   inside the work window
   ([Codex IDE extension docs](https://developers.openai.com/codex/ide)).
5. For **Claude**, the normal mode will ask you to approve actions; **auto-accept
   mode** lets the relay run more autonomously.

**Expected result:** two live panels in one window, each ready to take a prompt.

---

## Step 4 — Bootstrap Claude first

In the **Claude** UI, paste the prompt below, replacing `[MISSION]` with your
actual task:

```text
Read CLAUDE.md and M8SHIFT.protocol.md.

You are the claude agent of the M8Shift relay. Take the pen before making any
change, and carry out this mission:

[MISSION]

After your append to codex, do not end the loop: wait for your turn again with
`python3 m8shift.py wait claude`, then keep following the protocol until DONE,
or until you hit a blocker that needs my input.
```

**Expected result:** Claude takes the pen (the seed turn / bootstrap), and its
transcript shows the tool's confirmation line, which reads:

```text
✓ verrou pris par claude (...)
```

This is the literal output of `m8shift.py claim claude`: it confirms Claude now
holds the pen and the lock state is `WORKING_CLAUDE`.

> **If that confirmation line never appears, then** Claude did not acquire the
> pen. Check `python3 m8shift.py status` in a terminal at the repository root to
> see the `holder`, `state`, and `turn`, then re-send the prompt above.

---

## Step 5 — Start Codex

In a **new Codex conversation**, paste:

```text
Read AGENTS.md and M8SHIFT.protocol.md.

You are the codex agent of the M8Shift relay. Run
`python3 m8shift.py wait codex`, then take the pen when your turn arrives.
Handle the latest ask, hand back to claude, then keep waiting.
Never modify the repository without a successful claim. Continue until DONE
or a blocker.
```

The extension's Agent mode lets Codex read, edit, and run commands inside the
work window.

**Expected result:** Codex blocks on `wait codex` until the turn passes to it,
then takes the pen (state `WORKING_CODEX`), processes the ask, hands back to
`claude`, and returns to waiting. Strict alternation between the two agents is
now running.

> **If Codex starts editing without waiting, then** it skipped the `wait`/`claim`
> sequence. Stop it and re-send the prompt above — it must never touch the
> repository without a successful claim.

---

## Limits & troubleshooting

- **A finished UI conversation does not wake itself up** when `M8SHIFT.md`
  changes. That is exactly why both prompts (Steps 4 and 5) explicitly tell each
  agent to **stay in the loop** with `wait`.

- **If a panel stops anyway**, just send it:

  ```text
  Resume the M8Shift loop from `python3 m8shift.py status`.
  ```

- **Check the relay state at any time** from a terminal at the repository root:

  ```text
  python3 m8shift.py status
  ```

  This is non-blocking and shows who holds the pen (`holder`), the last `turn`,
  and whether the lock is stale (an expired lock left behind by an agent that
  crashed while holding the pen).

> **If `status` shows a stale lock, then** the previous holder never released it.
> Recover with `python3 m8shift.py claim <agent> --force`, which reclaims only an
> expired lock — it cannot steal the pen from an agent whose lock is still valid.
