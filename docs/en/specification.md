# Specification — M8Shift

> **Status**: `Validated` · **Version**: protocol v1 · **Last reviewed**: 2026-06-21

---

## 1. Object

`cowork` lets **two AI agents** (Claude and Codex) work on the same repository
**without stepping on each other**, coordinating through a **single shared
file** `COWORK.md`, in strict alternation (cooperative mutex). The system must be
**portable to any project** and **usable by the agents without a human having to
explain the protocol** (it is self-contained). *Limit*: in interactive agent UIs a
human still nudges each agent to resume between turns — see §8.

## 2. Scope

| Included | Excluded |
|----------|----------|
| Single-file lock, turn journal, control CLI | Network / multi-machine orchestration |
| Idempotent self-install (`init`) into any project | More than two simultaneous agents |
| Anti-deadlock via TTL, bounded archiving | Resident daemon, persistent queue |
| `CLAUDE.md` / `AGENTS.md` anchors | Authentication / encryption of the state file |

## 3. Actors

| Actor | Role |
|-------|------|
| **active agent ×2** | the configured relaying pair (default `claude` → `CLAUDE.md`, `codex` → `AGENTS.md`); each AI agent reads its own anchor and operates the relay on its side |
| **maintainer** | Human; deploys the kit, arbitrates, reads the journal |

## 4. Functional requirements

| ID | Requirement | Verified by |
|----|-------------|-------------|
| EF-1 | **`claim` mandatory and exclusive before working**: it acquires `WORKING_<self>` from `IDLE`/`AWAITING_<self>`; two simultaneous `claim` calls (claude/codex) ⇒ only one succeeds, the other is excluded. | `test_claim_exclusive_sequential`, `test_concurrent_claim_claude_vs_codex_single_winner` |
| EF-1b | `append` is accepted **only from `WORKING_<self>`** (hence after `claim`) → guarantees exclusivity of the **work window** in the repository, not just of the journal. | `test_append_requires_claim_from_idle`, `test_append_requires_claim_from_awaiting` |
| EF-2 | `append` writes the next turn **and** hands off (`AWAITING_<other>`) in one atomic operation; `turn` is incremented. | `test_handoff_increments_and_alternates` |
| EF-3 | A closed turn (`END`) is immutable (by convention: the tool never rewrites it). | (review) |
| EF-4 | `--to` must target the other agent (self-handoff forbidden). | `test_self_handoff_refused` |
| EF-5 | `wait <agent>` waits for the agent's turn; `--once` performs a single check (rc 0 = its turn, rc 3 otherwise). | `test_wait_once_return_codes` |
| EF-6 | `claim --force` reclaims **only a stale lock**; refused on an active lock. | `test_force_refused_on_fresh_lock`, `test_force_accepted_on_stale_lock` |
| EF-7 | The holder can reclaim its own lock (refresh the TTL). | `test_reclaim_own_lock_refreshes` |
| EF-8 | `release` / `done` act only if the caller holds the pen (or nobody does); `--force` overrides. | `test_release_done_require_holder`, `test_release_done_force_overrides` |
| EF-9 | `archive --keep N` purges old closed turns without ever moving the bootstrap turn `#0` or touching the lock. | `test_archive_preserves_system_turn0` |
| EF-10 | `init` generates `COWORK.md`, `COWORK.protocol.md` and injects the anchors; idempotent (stanza not duplicated, existing content preserved, `COWORK.md` not overwritten except with `--force`). | `test_reinit_idempotent_preserves_content`, `test_init_force_resets_lock` |
| EF-11 | Auto-loadable anchors on a case-sensitive or case-insensitive FS: a unique variant is renamed to `CLAUDE.md`/`AGENTS.md`, including in the index if Git is available and tracks it; ambiguous variants are refused. | `test_anchor_case_insensitive_no_duplicate`, `test_codex_anchor_is_canonical_on_case_sensitive_fs`, `test_tracked_anchor_case_rename_updates_git_index`, `test_ambiguous_anchor_variants_refused` |
| EF-12 | The stanza is idempotent and placed at the head of the anchors; if `AGENTS.override.md` exists, it is synchronized in the override and in `AGENTS.md`. | `test_stanza_is_moved_to_anchor_start`, `test_codex_override_also_receives_stanza` |
| EF-13 | If the project had `CLAUDE.md` but no Codex instructions, `init` creates in the new `AGENTS.md` a bridge to the common instructions in `CLAUDE.md`; a pre-existing Codex anchor stays autonomous. | `test_missing_agents_bridges_existing_claude_instructions`, `test_existing_agents_does_not_receive_claude_bridge` |

## 5. Non-functional requirements

| ID | Requirement |
|----|-------------|
| ENF-1 **Portability** | Works on an empty folder or a git repository, paths with spaces/accents, case-sensitive or case-insensitive FS. Python 3.8+, **stdlib only**, no third-party package. Runs on **Linux, macOS and Windows** (WSL, Git Bash, or native `python cowork.py`; see the Windows how-to). |
| ENF-2 **Atomicity** | Every write (including the archive) goes through a **unique** temporary file + `os.replace`, **preserving the mode** of the target file; serialized by an inter-process lock (`.cowork.lock`, `O_EXCL`, ownership token). |
| ENF-3 **Agent autonomy** | The whole procedure is embedded: `COWORK.protocol.md` (§0 quickstart) + the anchors' stanza. No human explanation required. |
| ENF-4 **Robustness** | Invalid inputs (unknown agent, missing `--body`, missing `COWORK.md`, **LOCK with invalid schema**: `state`/`turn`/`holder`) → clean `sys.exit` exit, never a traceback, never a corrupted state. |
| ENF-5 **Endurance over time** | `COWORK.md` stays bounded via `archive`; the archive is never re-read by the loop. |
| ENF-6 **Readability** | State and turns readable by eye and with `grep`; markers in HTML comments invisible in the Markdown rendering; versionable in plain text. |
| ENF-7 **Bootstrap** | Anchor names follow the auto-loaded conventions; the stanza takes priority in the file and the Codex discovery limits (override, root, size cap, per-session reload) are documented. |
| ENF-8 **Internationalization (i18n)** | Generated files and CLI messages are bilingual (en/fr), **English by default**. `init --lang en\|fr` selects the language of the generated artifacts (recorded in the LOCK `lang` field); `$COWORK_LANG` overrides the runtime message language. |
| ENF-9 **Zero credentials / any surface** | `cowork.py` makes **no network call** and needs **no API key, token or account**; it relies entirely on the host agents' own auth. It runs on every Claude Code / Codex surface (terminal/CLI, desktop app, IDE/VS Code, web) — interactive UIs need a human nudge between turns, a headless CLI loop automates fully. |

> **i18n authoring (note).** At runtime M8Shift stays a **single file**: the `en`/`fr`
> catalogs live inline in `cowork.py` (`MESSAGES` + the template dicts), so adding a
> language is just another dict entry. If you want a *translator-friendly* workflow
> (editing locale files without touching Python), use a **build step**: author
> per-locale files (`i18n/fr.json`, …) and *assemble* them into the single shipped
> `cowork.py` (a `build/` scaffold — `assemble.py`, `i18n_logic.py` — exists for this).
> Runtime = one file; authoring = optional build pipeline. Recommendation: stay inline
> unless several languages are planned.

## 6. Data model — the `LOCK` block

At the head of `COWORK.md`, between `<!-- COWORK:LOCK:BEGIN -->` and `:END`:

| field | type | values |
|-------|------|--------|
| `holder` | enum | an active agent \| `none` (default `claude`/`codex`) |
| `state` | enum | `IDLE` \| `WORKING_<X>` \| `AWAITING_<X>` \| `DONE` (one per active agent) |
| `agents` | CSV \| absent | declared roster; the **first two** are the active relaying pair (extra names reserved for the future N-agent mode) |
| `turn` | integer | number of the last closed turn |
| `since` | ISO-8601 UTC | how long the state has lasted |
| `expires` | ISO-8601 UTC \| `-` | anti-deadlock TTL; date **only** during `WORKING_*` |
| `note` | text | readable memo |
| `lang` | enum \| absent | `en` \| `fr` — language of generated files / runtime messages |

**State machine** (legitimate transitions):

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> WORKING_X: X claims
    WORKING_X --> AWAITING_Y: X appends to Y
    AWAITING_Y --> WORKING_Y: Y claims
    WORKING_X --> WORKING_X: X re-claims (refresh TTL)
    WORKING_X --> WORKING_Y: Y force-claims (X stale)
    WORKING_X --> DONE: done
    DONE --> [*]
```

## 7. Command-line interface

`init [--agents a,b] [--lang en|fr]` · `status` · `wait <agent> [--once] [--interval N]` · `claim <agent> [--force]` ·
`append <agent> --to <other> --ask … --done … [--files …] [--body f|-]` ·
`release <agent> --to <other> [--force]` · `done <agent> [--force]` · `archive [--keep N]`

Return codes: `0` success · `1` refusal/error (state, guardrail, invalid input) ·
`2` argparse usage · `3` `wait --once` when it is not the agent's turn.

## 8. Constraints & known limits

- **Waking an interactive agent UI**: `wait` blocks a *process* until your turn, but it
  does **not** relaunch or wake an agent running in an interactive UI (VS Code, …).
  Between turns a human nudges each agent (e.g. *"resume M8Shift"*). Fully hands-off
  operation needs a **headless** loop (`claude -p`, `codex exec`, cron) wrapping
  `wait → relaunch the agent → claim` — a host integration, not a change to the mutex. A
  notification/webhook can *signal* a turn but cannot *wake* the AI by itself.
- **Work-window exclusivity**: guaranteed by `claim` (exclusive acquisition of
  `WORKING_<self>`) + `append` restricted to `WORKING_<self>`. It relies on the
  **discipline** claim→work→append; cowork cannot lock the file system, so an
  agent that edits the repository **without** having claimed is not prevented by
  the tool (but will not be able to `append`).
- **Exclusivity by identity, not by instance**: `claim` excludes the **other**
  agent (claude vs codex), but several processes of the **same** agent all succeed
  in their `claim` (treated as a TTL refresh). cowork does not distinguish two
  instances of `claude`; the model assumes one instance per identity.
- **Cooperative, not enforced, mutex**: a malicious agent can, with `--force`,
  override `release`/`done`. The model assumes two cooperative agents.
- **Concurrency serialized by an advisory lock**: `.cowork.lock`
  (`O_CREAT|O_EXCL`, ownership token) serializes the read-modify-write + atomic
  write. *Advisory* lock: a manual edit of `COWORK.md` bypasses it; on a network
  FS (NFS) `O_EXCL`/`rename` are less reliable (cowork targets a local disk).
- **Immutability by convention**: the tool never rewrites a closed turn, but
  nothing at the file-system level prevents it (manual edit).
- **Two simultaneous agents (current)**: the protocol is binary by design — a
  **degree-1 mutex**. **Roadmap (two stages)**: (1) the relaying **pair is
  configurable** from an extensible roster via `init --agents a,b` — the first two
  names are the active pair, extra names are stored for later (**implemented,
  stage 1**; see [RFC — configurable agent pair](rfc-roster.md)); (2) **N
  simultaneous agents** (degree > 1), a separate future step. The current version
  stays limited to two simultaneous agents.
- **Anchor loading**: it depends on the host tool. Codex builds its instruction
  chain once per execution, gives priority to `AGENTS.override.md` in a folder
  and applies a size cap (32 KiB by default), truncating the last file to the
  remaining budget. `init` covers the local override and places the stanza at the
  head, but can neither reload an open session nor compensate for a global
  configuration that already consumes the entire cap.

## 9. Acceptance / validation

- `tests/test_cowork.py` suite: **74 tests** (unit + non-regression: claim model,
  mutex, claude/codex concurrency, canonical/override anchors, configurable roster,
  archive, robustness, anti-injection),
  `python3 -m unittest discover -s tests`, with no external Python dependency (the
  Git integration test is skipped if Git is absent).
- Multi-agent adversarial verification + 3 successive Codex reviews, each finding
  reproduced then fixed then re-tested.
- Documentary non-regression test: `docs/en/protocol.md` and `docs/fr/protocole.md`
  must stay byte-identical to `cowork.PROTOCOL[lang]` (`test_protocol_docs_in_sync`).

## 10. Versioning

Protocol **v1**. Any **breaking** change to the `LOCK`/`TURN` format or to the
markers increments the protocol version and must preserve the reading of existing
`COWORK.md` files or provide a migration.

The roster `agents:` field (RFC stage 1) is a **backward-compatible optional
addition** within v1, not a breaking change: a roster-unaware reader ignores it and
keeps working **for the default `claude,codex` pair**. A *custom* roster, however,
requires a roster-aware script — an old script would treat it as `claude,codex` and
could corrupt it. The markers and the one-`key: value`-per-line format are unchanged.

## 11. Developing M8Shift with M8Shift (dogfooding)

M8Shift can coordinate **its own development** — two agents editing `cowork.py` and the
repo through the relay. One precaution is decisive: here the **tool is also the
artifact**. Every `cowork.py <cmd>` reloads the file from disk, so a transient syntax
error in the source under edit would break the relay itself.

**Pattern — decouple the engine from the source under edit.** Run the relay from a
**frozen copy** of `cowork.py` in a **separate working directory** outside the repo.
Because the lock, journal and anchors are created next to the engine
(`HERE = __file__`), all relay state lives there and the repo's working tree stays
clean:

```text
Code/
├── cowork/                 ← the repo (edited here — the real work)
│   └── cowork.py           ← source under modification
└── cowork-relay/           ← relay working directory (outside the repo)
    ├── cowork.py           ← FROZEN copy = the engine
    ├── COWORK.md           ← coordination journal + LOCK
    ├── COWORK.protocol.md · CLAUDE.md · AGENTS.md
    └── .cowork.lock
```

- The engine updates **only** on an explicit `cp` — a momentarily broken `cowork.py`
  in the repo never affects coordination.
- The anchors live in the relay directory, not the repo root, so **auto-bootstrap does
  not fire**: each agent is pointed manually at the relay's `COWORK.protocol.md` (the
  documented "no project root" case). Discipline is unchanged — an agent edits the repo
  **only** while holding the pen, and keeps `cowork/cowork.py` importable (`ast.parse`)
  before each `append`.

This is exactly how the roster work (RFC stage 1) was reviewed: Claude implemented,
then handed off to Codex for an adversarial review through a frozen relay in
`cowork-relay/`. A **git worktree** of the repo would *not* decouple the engine (it
tracks the same branch, so its `cowork.py` changes on edit) — use a frozen copy.

## 12. Planned features & non-goals

Every planned feature stays within M8Shift's qualities (single-file, passive,
zero-credential, file-based & versioned): it is **append-only or read-only over data
M8Shift already stores** — never a daemon, an integration, or a second source of truth.
(Vetted by an adversarial design review that rejected anything breaking a quality.)

### 12.1 Retained (roadmap)

| Feature | Priority | What | Why it preserves the qualities |
|---------|----------|------|--------------------------------|
| **Shared memory + recap** | next | `cowork.py remember <agent> --key <slug> --note "…"` appends a `COWORK:MEM` block to a sibling `COWORK.memory.md` (atomic write under `file_lock()`, gated on `WORKING_<agent>`); `cowork.py recap` is a read-only briefing (current LOCK + last N turns + memory headlines). | One append-only block guarded by the SAME pen / `WORKING_<agent>` gate as `append`; recap re-renders markers M8Shift already writes. M8Shift never reads the ledger back into coordination logic — it still decides only *who writes, when*. |
| **Structured handoff + peek** | next | Optional write-only turn fields (`branch` / `commit` / `tests` / `next`, default `-`) + `cowork.py peek <agent>` to read the last handoff's fields (rc 0 your turn, rc 3 otherwise). | Header lines are never parsed back by the engine (only the LOCK block + markers are); peek is read-only over data `append` already wrote. |
| **Timeline + JSON status** | next | `cowork.py log [--limit N] [--agent X] [--all] [--oneline]` (relay timeline from existing turn markers; `--all` walks the archive) + `status --json`. | Pure read-only formatters over existing data; only stdlib `json` added. |
| **`claim --check <globs>`** | later | Advisory, read-only file-overlap probe against the other agent's last `files:` field (stdlib `fnmatch`). | Advisory only — grants no path lease and opens no concurrent work window, so it stays degree-1. |
| **`subturn`** | later | Record an agent's own sub-agent fan-out as a `COWORK:SUBTURN <n>.<k>` annotation under its open turn (accepted only from `WORKING_<agent>`). | Append-only; never touches the LOCK / turn counter / baton; sub-agents never hold the pen. |
| **Tasks board / block-on** | maybe | Append-only `COWORK.tasks.md` partition (`tasks claim/done`); `block`/`unblock` name an external dependency as an explicit `blocked_on` wait reason. | Serialized by the same `O_EXCL` lock; never executes a task, polls, or auto-routes the baton. |

### 12.2 Non-goals (rejected — they would break a quality)

| Rejected | Quality broken | Why |
|----------|----------------|-----|
| **Path-scoped *leases*** (concurrent disjoint writes) | degree-1 mutex / minimal | Puts two agents in a working state at once — that is the **stage-2 degree-2** lock, not today's single pen. `claim --check` delivers the safe, advisory 80%. |
| **Background daemon / watcher / push-notifier** | passive | M8Shift has no resident process; the recipient polls on its own next turn. A notification can *signal* a turn, never *wake* the AI. |
| **Running git / builds / APIs / executing `--next`** | passive + zero-credential | Acting on a tool needs auth + network and turns M8Shift into an orchestrator; handoff fields stay write-only advisory the receiving agent interprets with its own auth. |
| **Third-party deps / multi-file package** | single file | Every item is scoped to stdlib (`json`, `fnmatch`, `re`); a DB / queue / server would split the tool — no more `cp cowork.py`. |
| **"Smart" *derived* memory** (dedup / summarize / search / prune) | minimal / file-based | The ledger is a dumb append-only record; any digest is verbatim agent passthrough. The instant M8Shift curates content it owns a knowledge base with policy — a second source of truth. |
