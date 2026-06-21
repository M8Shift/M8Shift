![CoWork](CoWork-logo.png)

# CoWork

**A single-file relay that lets two AI agents — a configurable pair from a roster (Claude, Codex, Gemini, Le Chat, …) — cooperate on the same repository through strict alternation.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-73%20passing-brightgreen.svg)](#tests)
[![python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](#install)
[![single file](https://img.shields.io/badge/single%20file-cowork.py-orange.svg)](cowork.py)
[![made with CoWork](https://img.shields.io/badge/made%20with-%E2%9D%A4%20%26%20CoWork-ff69b4.svg)](docs/en/specification.md#11-developing-cowork-with-cowork-dogfooding)

English | [Français](README_fr.md)

---

## What is CoWork?

CoWork is a **cooperative mutex** for AI agents. When Claude and Codex work on the
same repository, they overwrite each other. CoWork introduces a single **pen**: at
any moment, exactly one agent is allowed to write; the other waits for its turn and
knows precisely what is expected of it.

The whole kit fits in **one file**: [`cowork.py`](cowork.py). You copy it to the
root of a project, run `init`, and the two agents hand off to each other through a
shared `COWORK.md` file. The whole procedure is **embedded in the generated files**,
so the agents need **no human explanation**. *Caveat for interactive UIs* (VS Code, …):
a human still nudges each agent to *resume* between turns — `wait` blocks a process but
does not wake an agent's chat UI. See [Limitations](#limitations).

## Why

When Claude and Codex share a repository, they have no way to take turns: edits
collide and work is lost. CoWork fixes this with a single exclusive lock (the
**pen**) and one simple rule — **acquire the pen before working** — so the two
agents never modify the repository at the same time. The coordination state lives
in a versionable file, readable both by eye and by `grep`, and preserved over time.
No daemon, no server, no external dependency — just one Python file and the host
tools' own conventions.

## Install

```bash
cp cowork.py /my/project/          # the ONLY file you need
cd /my/project
python3 cowork.py init             # project name = folder name (or --name "X")
```

`init` is idempotent (safe to re-run) and generates:

| generated file              | role |
|-----------------------------|------|
| `COWORK.md`                 | **the** living file: the lock (`LOCK`) + the turn journal |
| `COWORK.protocol.md`        | the full shared instruction (read once by each agent) |
| `CLAUDE.md`, `AGENTS.md`, … | each active agent's canonical anchor (the default pair shown) — a stanza is injected at the top without duplicating or overwriting existing content; the prior file is backed up to `<anchor>.cowork.bak` |
| `AGENTS.override.md`        | if present, Codex's priority anchor; the stanza is synced there too |

Use `--lang en|fr` to pick the language of the generated files (**English by
default**). Use `--agents a,b` to choose the relaying pair from the roster (default
`claude,codex`; the **first two** names are active, extra names are stored for the
future N-agent mode).

**On Windows?** No dependencies (stdlib only) — run via WSL, Git Bash, or
`python cowork.py <cmd>` in PowerShell. See [Running on Windows](docs/en/windows.md).

**From a fork / clone?** CoWork is one file — host it on any Git or GitLab:
`git clone https://gitlab.example.com/you/CoWork.git`, then `cp cowork.py /my/project/`
and run `init` as above.

## Quickstart

Each agent runs the same loop: `wait → claim → work → append`. `<you>` is your own
agent name and `<other>` the other active agent (the examples below use the default
pair `claude`/`codex`).

```bash
./cowork.py status                # who holds the pen? (non-blocking)
./cowork.py wait claude --once    # rc 0 = you may acquire; rc 3 = not yet

# Acquire the pen BEFORE working (exclusive: only one winner):
./cowork.py claim claude          # rc 0 = you hold the pen; otherwise not your turn

# ...work in the repository, then close your turn and hand off:
./cowork.py append claude --to codex \
    --ask  "what you need from the other" \
    --done "what you just did" \
    --files a,b

# Not your turn? Block until it is, then retry claim:
./cowork.py wait claude           # polls ~60s (--interval N)
```

**Golden rule:** you only work and write **after acquiring the pen via `claim`**
(`append` is accepted only from `WORKING_<you>`).

## Documentation

Docs follow the [Diátaxis](https://diataxis.fr/) framework:

- **Tutorial** — [docs/en/tutorial.md](docs/en/tutorial.md) — learn the relay step by step.
- **How-to (VS Code)** — [docs/en/vscode-guide.md](docs/en/vscode-guide.md) — run the relay with Claude + Codex.
- **How-to (Windows)** — [docs/en/windows.md](docs/en/windows.md) — run on Windows (WSL / Git Bash / native).
- **Reference (protocol)** — [docs/en/protocol.md](docs/en/protocol.md) — the shared protocol, states and rules.
- **Reference (spec)** — [docs/en/specification.md](docs/en/specification.md) — the full specification.
- **Explanation (architecture)** — [docs/en/architecture.md](docs/en/architecture.md) — design and operation.

## How it works

CoWork stores its state in the `LOCK` block at the top of `COWORK.md`. To work, an
agent must first **take the pen** with `claim` (state `WORKING_<you>`), an
**exclusive acquisition**: if two agents claim at once, only one wins. Because work
happens only while you hold the pen and `append` is accepted only from
`WORKING_<you>`, the two agents never write the repository concurrently. This
**claim-before-work** rule is the heart of CoWork.

The lock fields — `holder`, `state`, `agents`, `turn`, `since`, `expires`, `note`,
`lang` — are one `key: value` per line (easy to `grep`). `holder` is an active agent
or `none`; `agents` is the relaying pair (the first two declared, default
`claude,codex`); states are `IDLE`, `WORKING_<X>`, `AWAITING_<X>`, `DONE` (`<X>` = an
active agent, uppercased). Turns are framed by `COWORK:TURN <n> <agent> BEGIN/END`
HTML comments (invisible in
Markdown rendering) and are **immutable** once closed.

## Guarantees

Verified by the tests and by multi-agent review:

- **Mutex over the work window** — `claim` is the exclusive acquisition of the pen
  (two simultaneous `claim`s ⇒ a single winner); `append` is accepted only from
  `WORKING_<you>`. You work only after a successful `claim`, so two agents never
  modify the repository at the same time. `--to` ≠ self (strict alternation).
- **Stale-lock recovery** — `claim --force` reclaims **only a stale lock** (refused
  on an active one); the holder can refresh its own lock.
- **Guardrails** — `release` / `done` require holding the pen (`--force` = recovery).
- **Serialized concurrency** — an inter-process lock `.cowork.lock` (`O_EXCL`, with
  an ownership token) plus atomic writes (unique temp file + `os.replace`, mode
  preserved) ⇒ two concurrent `cowork.py` runs never corrupt the file.
- **Injection-safe** — single-line fields (line breaks and reserved markers
  rejected); turn bodies neutralized against fake markers.
- **Bounded over time** — `archive` purges old closed turns without touching the
  lock or the seed turn (turn #0).
- **Portable** — empty folder or git repo, paths with spaces/accents,
  case-sensitive or -insensitive filesystems, pre-existing anchors — without
  breakage or duplication.

## Limitations

- **Waking an interactive agent UI.** `wait` blocks a *process* until your turn; it
  does **not** relaunch or wake an agent running in an interactive UI (VS Code, …).
  Between turns a human still nudges each agent (e.g. *"resume CoWork"*). Fully
  hands-off operation needs a **headless** loop (`claude -p`, `codex exec`, cron)
  wrapping `wait → relaunch the agent → claim` — a host integration, not a change to
  the mutex. A system notification/webhook can *signal* a turn but cannot *wake* the AI
  by itself.
- **Cooperative, two-agent, advisory** — see the
  [specification](docs/en/specification.md) §8 (cooperative mutex, advisory lock, two
  simultaneous agents).

## Tests

No external Python dependency (stdlib only):

```bash
python3 -m unittest discover -s tests        # from the repo root
```

**73 tests**: unit tests (pure functions) + CLI regression tests (one per fixed
bug, referenced `NR-n`) covering the claim model, mutex, claude/codex concurrency,
canonical/override anchors, the configurable roster, archive, robustness, and
injection safety.

## Roadmap

CoWork keeps a **single-pen mutex** (one writer at a time) by design — see
[architecture §1.8](docs/en/architecture.md). Two staged steps:

1. **Configurable pair (shipped)** — choose the two relaying agents from an
   **extensible roster** via `cowork.py init --agents a,b`; the first two relay,
   extra names are stored for later. Still **2 simultaneous** (degree-1). See
   [RFC — configurable agent pair](docs/en/rfc-roster.md).
2. **N simultaneous agents** — true multi-agent (degree > 1); a separate, larger
   step with its own future RFC.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Contributing

Issues and pull requests are welcome. CoWork is a single file by design
([`cowork.py`](cowork.py) is the single source of truth — `COWORK.protocol.md` is
generated from it), so keep changes focused and covered by a test in `tests/`. Run
the test suite before opening a PR.

> **Made with ❤ & CoWork.** CoWork is improved *with CoWork*: Claude ⇄ Codex
> coordinate every change through the relay itself — see
> [Developing CoWork with CoWork](docs/en/specification.md#11-developing-cowork-with-cowork-dogfooding).
