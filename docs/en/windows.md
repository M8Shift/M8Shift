# How-to — Run M8Shift on Windows

M8Shift is **pure Python 3.8+ standard library** — there is **nothing to `pip
install`**. It runs on Windows three ways: WSL (closest to Linux/macOS), Git Bash, or
native PowerShell/cmd.

## Prerequisites

- **Python 3.8+** — install from [python.org](https://www.python.org/downloads/)
  (tick *"Add python.exe to PATH"*), or `winget install Python.Python.3.12`, or the
  Microsoft Store. Verify: `python --version` (or `py --version`).
- **No dependencies** — M8Shift is stdlib-only, so there is nothing else to install.
- *(Optional)* **Git for Windows** — only needed for anchor case-renaming via
  `git mv`. Without it, M8Shift still works (it skips the Git step).

## Option A — WSL (recommended: closest to Linux/macOS)

```powershell
wsl --install            # once; reboot if prompted
```

Then, inside the WSL shell (Ubuntu, …):

```bash
cd /your/project
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
python3 m8shift.py status
```

The installer downloads `m8shift.py` plus the optional `m8shift-worktree.py`
toolbox, verifies them against `checksums.sha256`, then runs `init`.

WSL gives a true POSIX filesystem (real `O_EXCL`, `chmod`, atomic `rename`), so
behavior is identical to Linux.

## Option B — Git Bash

Install **Git for Windows** (ships Git Bash + git). In Git Bash:

```bash
cd /c/Users/you/project
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --verify --agents claude,codex
python m8shift.py status
```

- Call the script as `python m8shift.py <cmd>` — Git Bash may not honor the
  `#!/usr/bin/env python3` shebang reliably.
- `git mv` for anchor canonicalization works because git is present.

## Option C — Native PowerShell / cmd

```powershell
python m8shift.py init
python m8shift.py claim claude
python m8shift.py append claude --to codex --ask "..." --done "..."
```

Native PowerShell does not run the Bash installer. Download or copy
`m8shift.py` into the project first; copy `m8shift-worktree.py` next to it only
if you need isolated parallel worktrees.

`claude` and `codex` are example roster names. Replace them with `gemini`, `vibe`,
or any cooperative agent that follows the relay protocol.

- Always invoke via `python m8shift.py <cmd>` — `./m8shift.py` is a Unix idiom and will
  not run directly.
- If `python` is not found, use the launcher: `py m8shift.py <cmd>`.

## Line endings

M8Shift writes `M8SHIFT.md` with LF (`\n`); the turn/lock markers are HTML comments and
the parser is newline-tolerant, so CRLF will not break detection. If you commit
`m8shift.py` from Windows, keep it LF (`* text=auto eol=lf` in `.gitattributes`, or
`git config core.autocrlf input`). In *this* source repo `M8SHIFT.md` is gitignored, so its endings never reach a
commit; a project that just copies `m8shift.py` should add `M8SHIFT.md` to its own
`.gitignore` (or keep it LF) to avoid CRLF noise.

## What works the same as on Linux/macOS

Empty folder or git repo, paths with spaces/accents, the inter-process lock
(`.m8shift.lock`, `O_EXCL` + ownership token), atomic writes, the full relay loop
(`wait → claim → work → append`), and the configurable active roster (`--agents`).
The repository core is English-only (`--lang en`); localized single-file variants
built with `m8shift-i18n.py` can bundle additional `--lang <code>` choices. Codex's
`AGENTS.md` discovery / override follow the Codex tool's own Windows rules.
