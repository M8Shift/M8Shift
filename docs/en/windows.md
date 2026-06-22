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
cp cowork.py /your/project/
cd /your/project
python3 cowork.py init
python3 cowork.py status
```

WSL gives a true POSIX filesystem (real `O_EXCL`, `chmod`, atomic `rename`), so
behavior is identical to Linux.

## Option B — Git Bash

Install **Git for Windows** (ships Git Bash + git). In Git Bash:

```bash
cd /c/Users/you/project
python cowork.py init        # use `python`, not ./cowork.py
python cowork.py status
```

- Call the script as `python cowork.py <cmd>` — Git Bash may not honor the
  `#!/usr/bin/env python3` shebang reliably.
- `git mv` for anchor canonicalization works because git is present.

## Option C — Native PowerShell / cmd

```powershell
python cowork.py init
python cowork.py claim claude
python cowork.py append claude --to codex --ask "..." --done "..."
```

- Always invoke via `python cowork.py <cmd>` — `./cowork.py` is a Unix idiom and will
  not run directly.
- If `python` is not found, use the launcher: `py cowork.py <cmd>`.

## Line endings

M8Shift writes `COWORK.md` with LF (`\n`); the turn/lock markers are HTML comments and
the parser is newline-tolerant, so CRLF will not break detection. If you commit
`cowork.py` from Windows, keep it LF (`* text=auto eol=lf` in `.gitattributes`, or
`git config core.autocrlf input`). In *this* source repo `COWORK.md` is gitignored, so its endings never reach a
commit; a project that just copies `cowork.py` should add `COWORK.md` to its own
`.gitignore` (or keep it LF) to avoid CRLF noise.

## What works the same as on Linux/macOS

Empty folder or git repo, paths with spaces/accents, the inter-process lock
(`.cowork.lock`, `O_EXCL` + ownership token), atomic writes, the full relay loop
(`wait → claim → work → append`), the configurable roster (`--agents`), and bilingual
output (`--lang en|fr`). Codex's `AGENTS.md` discovery / override follow the Codex
tool's own Windows rules.
