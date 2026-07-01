<div align="center">

# M8Shift

_Different agents. Different roles. One coordinated workflow._

![M8Shift](M8Shift-logo.png)

**A free and open-source single-file relay that lets two or more AI agents — an active roster (Claude, Codex, Gemini, Vibe, …) — cooperate on the same repository through strict alternation (one writer at a time).**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#tests)
[![python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](#install)
[![single file](https://img.shields.io/badge/single%20file-m8shift.py-orange.svg)](m8shift.py)
[![no API key](https://img.shields.io/badge/API%20key-not%20required-success.svg)](#runs-anywhere--no-api-key)
[![made with M8Shift](https://img.shields.io/badge/made%20with-%E2%9D%A4%20%26%20M8Shift-ff69b4.svg)](docs/en/specification.md#11-developing-m8shift-with-m8shift-dogfooding)

</div>

## 🧭 What is M8Shift?

M8Shift is a **cooperative mutex** for AI agents. When Claude and Codex work on the
same repository, they overwrite each other. M8Shift introduces a single **pen**: at
any moment, exactly one agent is allowed to write; the others wait for their turn and
knows precisely what is expected of it.

M8Shift is **free and open source**, released under the
[Apache License 2.0](LICENSE).

The whole kit fits in **one file**: [`m8shift.py`](m8shift.py). You copy it to the
root of a project, run `init`, and the agents hand off to each other (any roster member to any other) through a
shared `M8SHIFT.md` file. The whole procedure is **embedded in the generated files**,
so the agents need **no human explanation**. *Caveat for interactive UIs* (VS Code, …):
a human still nudges each agent to *resume* between turns — `wait` blocks a process but
does not wake an agent's chat UI. See [Limitations](#limitations).

## 💡 Why

When Claude and Codex share a repository, they have no way to take turns: edits
collide and work is lost. M8Shift fixes this with a single exclusive lock (the
**pen**) and one simple rule — **acquire the pen before working** — so no two
agents ever modify the repository at the same time. The coordination state lives
in a versionable file, readable both by eye and by `grep`, and preserved over time.
No daemon, no server, no external dependency — just one Python file and the host
tools' own conventions.

There is also a human reason: different agents bring different judgments. M8Shift was
created to make that contradiction usable — Claude, Codex or another agent can review,
challenge, and hand off work without the maintainer becoming a copy/paste relay. The
human still decides the direction. See [Philosophy](docs/en/philosophy.md).

<a id="runs-anywhere--no-api-key"></a>

## 🔐 Runs anywhere — no API key

M8Shift is a **passive CLI**: the agents drive it with shell commands, so it works on
every surface where Claude Code or Codex run, and it adds **zero credentials**.

| Surface | Works? | Notes |
|---------|--------|-------|
| Terminal / CLI | ✅ | headless (`claude -p`, `codex exec`, cron) can be **fully automated** — see [`examples/headless_runner.py`](examples/headless_runner.py), which emits `M8SHIFT_RUN_ID` and `.m8shift/runtime/runs.jsonl` lifecycle events |
| Desktop app (Mac/Windows) | ✅ | interactive: a human resumes each agent between turns |
| VS Code / JetBrains (IDE) | ✅ | same as desktop |
| Web (claude.ai/code) | ✅ | anywhere the agent can run a shell and read its anchor |

**No API key. No token. No account for M8Shift itself.** `m8shift.py` makes **zero
network calls** (stdlib only, local files) — the agents use whatever subscription or
login you already have. Nothing leaves your machine, there is no per-call cost, and no
vendor lock-in.

<a id="install"></a>

## ⚙️ Install

One-line local install for macOS/Linux/WSL/Git Bash:

```bash
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.sh | bash -s -- --agents claude,codex
```

Native Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/M8Shift/M8Shift/main/install.ps1 | iex
```

These installers download `m8shift.py` plus `m8shift-worktree.py` and
`m8shift-runtime.py` into the current directory, verify the files against
`checksums.sha256`, then run
`m8shift.py init --agents claude,codex` through the detected Python 3.8+ interpreter. No `sudo`, no global PATH change,
no background service.

For a pinned release, fetch the installer from the tag and use the same ref for the
downloaded files:

```bash
curl -fsSL https://raw.githubusercontent.com/M8Shift/M8Shift/vX.Y.Z/install.sh | \
  bash -s -- --ref vX.Y.Z --agents claude,codex
```

```powershell
$env:M8SHIFT_INSTALL_REF = "vX.Y.Z"
irm https://raw.githubusercontent.com/M8Shift/M8Shift/vX.Y.Z/install.ps1 | iex
```

> [!IMPORTANT]
> Bash and PowerShell both verify downloaded files by default (`--no-verify` opts out)
> against the `checksums.sha256` manifest from the selected ref. That catches
> corruption or mismatch. For out-of-band trust against a compromised origin, pin
> reviewed digests with `--sha256 FILE:HEX` or use a signed release tag.

Manual install:

```bash
cp m8shift.py /my/project/          # the ONLY file you need
cd /my/project
python3 m8shift.py init             # project name = folder name (or --name "X")
```

`init` is idempotent (safe to re-run) and generates:

| generated file              | role |
|-----------------------------|------|
| `M8SHIFT.md`                 | **the** living file: the lock (`LOCK`) + the turn journal |
| `M8SHIFT.protocol.md`        | the full shared instruction (read once by each agent) |
| `CLAUDE.md`, `AGENTS.md`, … | each active agent's canonical anchor (the default pair shown) — a stanza is injected at the top without duplicating or overwriting existing content; the prior file is backed up to `<anchor>.m8shift.bak` |
| `AGENTS.override.md`        | if present, Codex's priority anchor; the stanza is synced there too |

The shipped `m8shift.py` is **English-only**. To generate files in another language,
build a localized single-file variant from the language packs and run that:

```bash
python3 m8shift-i18n.py --langs fr,es --into ./dist   # build EN + fr + es
./dist/m8shift.py init --lang fr                       # then --lang / $M8SHIFT_LANG select it
```

Packs available: **fr, es, it, de, pt, ja, ru, zh-cn** (non-English are machine-translated,
pending review — see [CONTRIBUTING.md](CONTRIBUTING.md)). Use `--agents a,b,c…` to choose the
**active roster** (default `claude,codex`): **all** declared agents relay — the pen holder
hands off to any other member via `--to` — still one writer at a time (degree-1).

> [!TIP]
> **On Windows?** No dependencies (stdlib only) — run via WSL, Git Bash, or the native
> PowerShell one-liner above. See [Running on Windows](docs/en/windows.md).

> [!TIP]
> **From a fork / clone?** M8Shift is one file — host it on any Git or GitLab:
> `git clone https://gitlab.example.com/you/M8Shift.git`, then
> `cp m8shift.py /my/project/` and run `init` as above.

## 🚀 Quickstart

Each agent runs the same loop: `next → work → append`. `next` is the guarded
shortcut for `wait → claim → peek`: it waits if needed, then claims and prints the
latest handoff addressed to you. `<you>` is your own agent name and `<other>` any
other roster member you hand to (the examples below use the default pair
`claude`/`codex`).

`claude` and `codex` are example roster names, not a limitation. Replace them with
`gemini`, `vibe`, or any other cooperative agent that can read its instructions,
run the CLI, and follow `claim → work → append`.

```bash
./m8shift.py status --for claude   # who holds the pen + what should claude do next?
./m8shift.py watch --for claude    # live read-only status view in a terminal
./m8shift.py next claude           # wait if needed, then claim + show the handoff
./m8shift.py wait claude --once    # rc 0 = your turn (or DONE = stop); rc 3 = not yet

# Acquire the pen BEFORE working (exclusive: only one winner):
./m8shift.py claim claude          # rc 0 = you hold the pen; otherwise not your turn

# ...work in the repository, then close your turn and hand off:
./m8shift.py append claude --to codex \
    --ask  "what you need from the other" \
    --done "what you just did" \
    --files a,b \
    --wait                         # optional: stay blocked until claude's next turn or DONE

# Not your turn? Block until it is, then retry claim:
./m8shift.py wait claude           # polls ~60s (--interval N)
```

> [!IMPORTANT]
> **Golden rule:** you only work and write **after acquiring the pen via `claim`**
> (`append` is accepted only from `WORKING_<you>`).

Before stopping, run `status --for <you>`; if the relay is not `DONE`, keep waiting,
hand off your own `WORKING_<you>` state with `append`, close it with `done`, or park an
open/no-work session with `pause`.

> [!TIP]
> For a passive live view while agents work, leave
> `./m8shift.py watch --for <you> --interval 5` running in a separate terminal; it
> never claims or changes the relay.

## 📚 Documentation

Docs follow the [Diátaxis](https://diataxis.fr/) framework. Start with the
published site, or use the repository-local docs when working from a clone.

| Category | Document |
|----------|----------|
| **Live site** | [m8shift.ai](https://m8shift.ai/) |
| **Documentation index** | [docs/en/README.md](docs/en/README.md) |
| **Getting started** | [tutorial](docs/en/tutorial.md) · [VS Code guide](docs/en/vscode-guide.md) · [Windows](docs/en/windows.md) |
| **Reference** | [protocol](docs/en/protocol.md) · [protocol reference](docs/en/protocol-reference.md) · [specification](docs/en/specification.md) · [agents guide](docs/en/agents-guide.md) |
| **Explanation** | [architecture](docs/en/architecture.md) · [philosophy](docs/en/philosophy.md) · [security audit](docs/en/security-audit.md) · [stage-2 rationale](docs/en/stage2-rationale.md) |
| **RFCs** | [RFC index](docs/en/README.md#rfcs) · [RFC directory](docs/en/rfc/) |

> [!NOTE]
> RFCs are maintained in English under `docs/en/rfc/`. **Numbers are assigned in
> creation order and are permanent** — a number never tracks *implementation* order.
> For example RFC 010 was authored 10th (2026-06-24) but its patterns shipped last, in
> v3.21–v3.27 (2026-06-26); renumbering would break cross-links, git history, and
> issue/MR references, so an RFC keeps its birth number even when implemented much
> later (or never). Dates below are the implementation date (`—` when not
> implemented).

| № | RFC | Description | Status | Implemented | How |
|----:|-----|-------------|--------|-------------|-----|
| 001 | [Roster](docs/en/rfc/001-rfc-roster.md) | Configurable agent roster (early design) | historical / superseded | v2.1.0 · 2026-06-22 | superseded by RFC 002 |
| 002 | [N agents](docs/en/rfc/002-rfc-n-agents.md) | N-agent relay with one shared pen | historical / implemented | v2.4.0 · 2026-06-23 | one-pen routing (`append --to`) |
| 003 | [I18n packs](docs/en/rfc/003-rfc-i18n-packs.md) | Build-time language packs (EN core + 8) | shipped | v3.0.0 · 2026-06-23 | AST injector `m8shift-i18n.py` |
| 004 | [Memory](docs/en/rfc/004-rfc-memory.md) | Shared append-only memory ledger | shipped | v3.2.0 · 2026-06-23 | `remember` / `recap`, pen-free |
| 005 | [Claim check](docs/en/rfc/005-rfc-claim-check.md) | Advisory pre-claim overlap check | shipped | v3.3.0 · 2026-06-23 | `claim --check`, read-only |
| 006 | [Tasks](docs/en/rfc/006-rfc-tasks.md) | Shared append-only task board | shipped | v3.4.0 · 2026-06-23 | `task` event-log, pen-free |
| 007 | [Subturn](docs/en/rfc/007-rfc-subturn.md) | Sub-turn streaming proposal | rejected | — | rejected by adversarial panel |
| 008 | [Worktree companion](docs/en/rfc/008-rfc-worktree-companion.md) | Degree-2 worktree parallelism + serialized integration | implemented v1 | v3.5.0 · 2026-06-24 | `m8shift-worktree.py`; core `LOCK` as integration pen |
| 009 | [Runtime companion](docs/en/rfc/009-rfc-runtime-companion.md) | Local presence / inbox / progress / diagnostics | implemented v1 | v3.15.0 · 2026-06-25 | `m8shift-runtime.py` companion |
| 010 | [Runtime patterns](docs/en/rfc/010-rfc-runtime-patterns.md) | Pattern filter: retained / rejected / deferred | accepted (filter) | v3.21–v3.27 · 2026-06-26 | 6 retained shipped; 13 rejected; RFC 024/025 baselined |
| 011 | [Session history](docs/en/rfc/011-rfc-session-history.md) | Session history ledger + `history` | implemented | v3.7.0 · 2026-06-24 | `M8SHIFT.sessions.jsonl` |
| 012 | [Contracts validation](docs/en/rfc/012-rfc-contracts-validation.md) | Stage-4 contracts + read-only validation | implemented | v3.13.0 · 2026-06-25 | read-only validation surface |
| 013 | [Hosted runtime control plane](docs/en/rfc/013-rfc-hosted-runtime-control-plane.md) | Future hosted / runtime control plane | future / not impl. | — | optional layer outside the passive core |
| 014 | [Provider management](docs/en/rfc/014-rfc-provider-management.md) | Local provider / adapter registry | implemented v1 | v3.16.0 · 2026-06-25 | `m8shift-runtime.py` providers |
| 015 | [Shared tree degree gt1](docs/en/rfc/015-rfc-shared-tree-degree-gt1.md) | True degree > 1 writes in one tree | rejected (research) | — | rejected for the core |
| 016 | [Cooperative turn request](docs/en/rfc/016-rfc-cooperative-turn-request.md) | Cooperative baton request + operator steering | implemented | v3.15.0 · 2026-06-25 | core baton request |
| 017 | [Stage6 integrations](docs/en/rfc/017-rfc-stage6-integrations.md) | Stage-6 closure: local integration layer | implemented | Stage 6 · 2026-06-25 | local layer; heavier integrations deferred |
| 018 | [Agent runtime architecture](docs/en/rfc/018-rfc-agent-runtime-architecture.md) | Local scaffold: roles / workflows / approvals / reports | implemented v1 | v3.16.0 · 2026-06-25 | `m8shift-runtime.py` scaffold |
| 019 | [Input neutral patterns](docs/en/rfc/019-rfc-input-neutral-patterns.md) | Neutral runtime-pattern inventory | curated input / not impl. | — | reference for future RFCs |
| 020 | [Headless runner hardening](docs/en/rfc/020-rfc-headless-runner-hardening.md) | Reference runner: validation / dry-run / timeout / audit | implemented v1 | v3.16.0 · 2026-06-25 | `examples/headless_runner.py` |
| 021 | [Pause resume](docs/en/rfc/021-rfc-pause-resume.md) | Stable `PAUSED` state for idle sessions | implemented v1 | v3.17.0 · 2026-06-25 | core `PAUSED` + `pause` / `resume` |
| 022 | [Session reports](docs/en/rfc/022-rfc-session-reports.md) | Session reports + decision ledger | implemented v1 | v3.18.3 · 2026-06-26 | `report` generated from existing turns |
| 023 | [Agent token footprint](docs/en/rfc/023-rfc-agent-token-footprint.md) | Cut the mandatory protocol read | implemented (Phase 1) | v3.19.0 · 2026-06-26 | split `protocol.md` / `protocol-reference.md` |
| 024 | [Doctor split](docs/en/rfc/024-rfc-doctor-split.md) | Split core doctor vs companion diagnostics | baseline impl. | v3.27.0 · 2026-06-26 | core doctor owns relay hygiene; runtime doctor owns sidecar diagnostics |
| 025 | [Runtime status composition](docs/en/rfc/025-rfc-status-runtime.md) | Runtime status over core + sidecars | baseline impl. | v3.27.0 · 2026-06-26 | `status-runtime [--brief] [--json]`; JSON contract remains separate |
| 026 | [Sidecar retention](docs/en/rfc/026-rfc-sidecar-retention.md) | Bound / prune runtime sidecar ledgers | shipped · hardened | v3.34.2 · 2026-07-01 | `retention prune/apply/policy show`, archive index, malformed-ledger fail-safe, traversal/symlink hardening |
| 027 | [Notifications](docs/en/rfc/027-rfc-notifications.md) | Local notifications for handoffs / stale turns | shipped | v3.32.0 · 2026-07-01 | `m8shift-runtime.py notify`, stdout/file/bell/OS/hook tiers |
| 028 | [Headless command templates](docs/en/rfc/028-rfc-headless-command-templates.md) | Safe headless command templates | shipped | v3.33.0 · 2026-07-01 | provider examples, `argv_by_platform`, strict run-plan validation |
| 029 | [Companion workboard](docs/en/rfc/029-rfc-m8shift-board.md) | Richer companion workboard outside core | draft | — | deferred from RFC 010 |
| 030 | [Tamper evidence](docs/en/rfc/030-rfc-tamper-evidence.md) | Hash-chain tamper-evidence for relay records | draft | — | detection/warning only; git remains the strong anchor |
| 031 | [Decision traceability](docs/en/rfc/031-rfc-decision-traceability.md) | Durable decision records from turn journal | shipped | v3.31.0 · 2026-07-01 | `decisions target/scaffold`, `append --stance`, ADR fallback |
| 032 | [Tiered delegation](docs/en/rfc/032-rfc-tiered-delegation.md) | Capability-tiered delegation charter | Phase 1 shipped | v3.35.0 · 2026-07-01 | `route recommend` advisory only; launch/delegate future |
| 034 | [Companion adapter interface](docs/en/rfc/034-rfc-companion-adapter-interface.md) | Context packs + optional shell-output adapters | shipped · RTK visible | v3.36.0 · 2026-07-01 | `m8shift-context.py status`, RTK ON/OFF, `M8SHIFT_RTK=on/off`, last-pack ratio |
| 037 | [Agent context compression backends](docs/en/rfc/037-rfc-agent-context-compression-backends.md) | Digest-based context compression + bounded raw references | Phase C shipped | v3.38.0 · 2026-07-01 | `m8shift-context.py compress/retrieve`, redaction-before-store, builtin + RTK backend dispatch, reference-only fail-safe |
| 039 | [Model/task routing](docs/en/rfc/039-rfc-model-task-routing.md) | Capability-first model/task routing | Phase 1 shipped | v3.35.0 · 2026-07-01 | operator manifests, no baked-in vendors/prices, no launch |

## 🔁 How it works

M8Shift stores its state in the `LOCK` block at the top of `M8SHIFT.md`. To work, an
agent must first **take the pen** with `claim` (state `WORKING_<you>`), an
**exclusive acquisition**: if several agents claim at once, only one wins. Because work
happens only while you hold the pen and `append` is accepted only from
`WORKING_<you>`, no two agents ever write the repository concurrently. This
**claim-before-work** rule is the heart of M8Shift.

```mermaid
flowchart LR
    W["wait / status"] --> Q{your turn?}
    Q -- no --> W
    Q -- "yes (IDLE or AWAITING you)" --> C["claim"]
    C --> K["work in the repo"]
    K --> A["append --to other"]
    A --> W
```

The lock fields — `holder`, `state`, `agents`, `lang`, `session`, `turn`, `since`,
`expires`, `note` — are one `key: value` per line (easy to `grep`). `holder` is the pen holder
while `WORKING_*`, the awaited baton-owner while `AWAITING_*`, or `none` while
`IDLE`, `PAUSED`, or `DONE`;
`agents` is the active roster (all declared agents, ≥2; default `claude,codex`); states
are `IDLE`, `WORKING_<X>`, `AWAITING_<X>`, `PAUSED`, `DONE` (`<X>` = an active agent, uppercased). Turns are framed by `M8SHIFT:TURN <n> <agent> BEGIN/END`
HTML comments (invisible in
Markdown rendering) and are **immutable** once closed.

Timestamps are stored in UTC (`...Z`) for stable cross-agent comparisons. Human-facing
commands (`status`, `recap`, `history`, `task show`, and `m8shift-worktree.py status`) also
print the user's local time next to UTC, prefixed by the timezone name/offset when
available (otherwise `local`); JSON output stays canonical UTC.
`status` also derives display-only `started` and `duration` lines from the session
ledger; `status --json` exposes them as `session_started_at`,
`session_duration_seconds`, and `session_duration` (`null` when unavailable).

## ✅ Guarantees

Verified by the tests and by multi-agent review:

- **Mutex over the work window** — `claim` is the exclusive acquisition of the pen
  (two simultaneous `claim`s ⇒ a single winner); `append` is accepted only from
  `WORKING_<you>`. You work only after a successful `claim`, so no two agents ever
  modify the repository at the same time. `--to` ≠ self (strict alternation).
- **Stale-lock recovery** — `claim --force` reclaims **only a stale lock** (refused
  on an active one); the holder can refresh its own lock. Long-running wrappers
  should refresh at least 5 minutes before `expires`.
- **Guardrails** — `release` / `done` are baton-owner ops (the `holder`: pen holder in WORKING / awaited agent in AWAITING); only `append` requires the pen. `--force --reason TEXT` = audited recovery.
- **Serialized concurrency** — an inter-process lock `.m8shift.lock` (`O_EXCL`, with
  an ownership token) plus atomic writes (unique temp file + `os.replace`, mode
  preserved) ⇒ two concurrent `m8shift.py` runs never corrupt the file.
- **Injection-safe** — single-line fields (line breaks and reserved markers
  rejected); turn bodies neutralized against fake markers.
- **Bounded over time** — `archive` purges old closed turns without touching the
  lock or the seed turn (turn #0).
- **Portable** — empty folder or git repo, paths with spaces/accents,
  case-sensitive or -insensitive filesystems, pre-existing anchors — without
  breakage or duplication.

<a id="limitations"></a>

## ⚠️ Limitations

> [!WARNING]
> **Waking an interactive agent UI.** `wait` blocks a *process* until your turn; it
> does **not** relaunch or wake an agent running in an interactive UI (VS Code, …).
> Between turns a human still nudges each agent (e.g. *"resume M8Shift"*). Fully
> hands-off operation needs a **headless** loop (`claude -p`, `codex exec`, cron)
> wrapping `wait → relaunch the agent → claim` — a host integration, not a change to
> the mutex. A system notification/webhook can *signal* a turn but cannot *wake* the AI
> by itself.
>
> An example runner is provided: [`examples/headless_runner.py`](examples/headless_runner.py).
> It supports `--once`, manual TTL heartbeat, `M8SHIFT_RUN_ID`, immutable local run
> plans, post-run `LOCK` verification, and local `.m8shift/runtime/runs.jsonl`
> lifecycle/finding events. The optional [`m8shift-runtime.py`](m8shift-runtime.py)
> companion adds local presence, operator inbox, progress, and runtime diagnostics
> under `.m8shift/runtime/`.
- **Cooperative, N-agent, advisory** — see the
  [specification](docs/en/specification.md) §8 (cooperative mutex, advisory lock, one
  writer at a time).

<a id="tests"></a>

## 🧪 Tests

No external Python dependency (stdlib only):

```bash
python3 -m unittest discover -s tests        # from the repo root
```

**Test suite**: unit tests (pure functions) + CLI regression tests (one per fixed
bug, referenced `NR-n`) covering the claim model, the one-pen mutex, the N-agent relay,
canonical/override anchors, the configurable roster, advisory turn fields, shared
memory, `claim --check`, the tasks board, archive, robustness, and injection safety.

## 🧩 Positioning — not an orchestrator

M8Shift is a **coordination primitive**, not an agent platform. It deliberately does
**one thing**: ensure that, of the agents already running on a shared repo, only one
writes at a time (strict turn-taking).

Full orchestrators/runtimes (agent frameworks like **LangGraph**, **AutoGen**, **CrewAI**) cover far
more — they *run* the agents: session management, tool dispatch, memory, sub-agents,
parallel **and** sequential workflows. They can take turns too; the real difference is
**scope and footprint**:

| | Orchestrator (e.g. LangGraph) | M8Shift |
|---|------------------------------|--------|
| What it is | a runtime/gateway that **drives** the agents | a single-file **lock** the agents poll |
| Install | a platform to deploy + configure (providers, auth) | `cp m8shift.py` — stdlib, no daemon, no server |
| Credentials | the agents' auth (subscription **or** API key) | **none** — M8Shift never authenticates anything |
| Scope | memory, tools, routing, parallel + sequential | only *who writes, when* |

**What M8Shift gives that a message-routing orchestrator doesn't:**

- 🔒 **A real write-lock on the repo** — exactly one agent writes at a time. An
  orchestrator routes *tasks and messages*; it does not stop two agents editing the
  same files in parallel. M8Shift does (its whole job).
- 🪶 **Zero runtime, zero credentials** — `cp m8shift.py` and go. No server to deploy, no
  provider/auth to configure, no API key, no per-call cost.
- 🤝 **Peer-to-peer, no coordinator** — the agents pass the baton themselves
  (`--to <other>`); there is no central "project-manager" agent deciding the turns.
- 📓 **Durable, readable, git-versioned coordination** — `M8SHIFT.md` *is* the record of
  who did what and what's next — by eye and by `grep`, committed alongside your code.

Reach for an orchestrator when you want a **managed agent team**. Reach for M8Shift when
you just want two agents you already run (Claude Code, Codex, …) to **stop overwriting
each other** — with nothing to install or authenticate. They are **complementary**, not
competing (M8Shift could even be the lock inside a larger setup).

## 🗺️ Roadmap

M8Shift keeps a **single-pen mutex** (one writer at a time) by design — see
[architecture §1.8](docs/en/architecture.md). The current roadmap is:

| Area | Status | Surface | Boundary |
|------|--------|---------|----------|
| N-agent roster, one pen | ✅ Shipped | `init --agents a,b,c…`, directed `append --to <agent>` | all agents can relay; still one writer at a time |
| Read/handoff observability | ✅ Shipped | `recap`, `peek`, `log`, `history`, `status --json`, `watch` | read-only views; no routing decisions |
| Session reports | ✅ Shipped | `session list/show/decisions/report`, `M8SHIFT.session-reports/` | derived Markdown memory; no lock mutation, no invented decisions |
| Decision traceability | ✅ Shipped | `decisions target`, `decisions scaffold`, `append --stance`, `docs/decisions/` | durable ADR-style exports from journal turns; markdown fallback when no tracker exists |
| Advisory pre-claim checks | ✅ Shipped | `claim --check [--files …] [--turns N]` | no pen taken; overlap is advisory |
| Shared memory and tasks | ✅ Shipped | `remember`, `task add/done/drop/list/show`, recap headlines | append-only ledgers; never enforced by the mutex |
| Stage 4 contracts | ✅ Shipped | `append --schema stage4.v1 …`, `contract validate`, `doctor --contracts` | typed metadata is validated only on explicit read-only commands |
| Operator-loop guardrails | ✅ Shipped | `next`, `append --wait`, `status --for`, `request-turn/yield-turn/decline-turn/steer-turn` | prevents lost handoffs and UI-routing deadlocks without creating a second pen |
| Pause / resume | ✅ Shipped | `pause <holder> --reason …`, `resume <agent> --reason …`, `next --resume` | stable open/no-work state: `PAUSED`, `holder=none`, explicit user-scope resume |
| Local integration layer | ✅ Shipped | installers, checksums, version surfaces, `examples/headless_runner.py`, `m8shift-runtime.py` | local convenience layer; no provider SDK in the core |
| Degree-2 parallel work | ✅ Shipped, opt-in | [`m8shift-worktree.py`](docs/en/rfc/008-rfc-worktree-companion.md) | isolated git worktrees; serialized integration pen; core remains degree-1 |
| Provider/runtime companion | ✅ Shipped v1 | `m8shift-runtime.py init/providers/roles/workflows/approve/report` | host-side config and reports; no secrets, no second routing authority |
| Local notifications | ✅ Shipped | `m8shift-runtime.py notify`, `watch` notification path | stdout/file/bell/OS/hook tiers; advisory only, no daemon, no network in M8Shift |
| `subturn` provenance ledger | ❌ Rejected | [rationale](docs/en/rfc/007-rfc-subturn.md) | redundant with advisory fields and `remember` |
| Hosted control plane / IDE integrations | 🔭 Future companion | [RFC](docs/en/rfc/013-rfc-hosted-runtime-control-plane.md) | optional layer outside the passive core |

New ideas are welcome via an RFC under `docs/en/rfc/`. RFCs are English-only;
localized documentation should link to the canonical English RFC instead of maintaining
translated copies.

> [!CAUTION]
> **Non-goals** (they would break a M8Shift quality): path-scoped *leases* for
> concurrent disjoint writes inside the shared tree (use the
> [opt-in worktree companion](docs/en/rfc/008-rfc-worktree-companion.md) instead); a
> background daemon / autonomous watcher / push-notifier; running git, builds or APIs
> (needs auth + network → an orchestrator); third-party deps or a multi-file package;
> and "smart" *derived* memory (dedup / summarize / prune) — the ledger stays a dumb,
> human-curated record.

## 📄 License

Licensed under the [Apache License 2.0](LICENSE).

## 🤝 Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) (ground
rules + how to add or improve a language pack). M8Shift is a single file by design
([`m8shift.py`](m8shift.py) is the single source of truth — `M8SHIFT.protocol.md` is
generated from it), so keep changes focused and covered by a test in `tests/`. Run
the test suite before opening a PR.

> **Made with ❤ & M8Shift.** M8Shift is improved *with M8Shift*: Claude ⇄ Codex
> coordinate every change through the relay itself — see
> [Developing M8Shift with M8Shift](docs/en/specification.md#11-developing-m8shift-with-m8shift-dogfooding).
> The dogfooding relay is promoted to each stable version after tests pass, so the coordinator
> does not silently drift behind the tool being developed.
