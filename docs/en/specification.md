# Specification — CoWork

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

```text
IDLE ──claim X──▶ WORKING_X ──append──▶ AWAITING_Y ──claim Y──▶ WORKING_Y …
  └──────────────────────────────────────────────────────────────▶ DONE (done)
WORKING_X(stale) ──claim Y --force──▶ WORKING_Y
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
  Between turns a human nudges each agent (e.g. *"resume CoWork"*). Fully hands-off
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

- `tests/test_cowork.py` suite: **73 tests** (unit + non-regression: claim model,
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

## 11. Developing CoWork with CoWork (dogfooding)

CoWork can coordinate **its own development** — two agents editing `cowork.py` and the
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
