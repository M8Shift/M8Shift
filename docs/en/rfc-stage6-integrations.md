# RFC — Stage 6 integrations: remaining work and value

- **Status:** partially implemented; remaining work tracked below
- **Scope:** integrations around M8Shift: packaging, IDE surfaces, MCP, headless
  runners, provider adapters, local notifications, and optional runtime/control
  planes
- **Core invariant:** integrations must not replace the single-file passive core;
  `m8shift.py` remains the authority for `LOCK`, turn order, and the one-pen mutex

## 1. Goal

Stage 6 is the integration layer around an already usable relay. The question is no
longer "can M8Shift coordinate agents?" It can. The question is:

> Which integrations make M8Shift easier to adopt and safer to operate without
> turning it into a hosted agent runtime?

This RFC evaluates the remaining Stage 6 candidates, their value, their risk, and the
recommended implementation order.

## 2. Current baseline

Already shipped or available today:

- `m8shift.py` core relay: one pen, N-agent roster, directed handoffs, history,
  memory, task ledger, doctor, `status --json`, `watch`, Stage-4 contract
  validation, and loop guardrails;
- `m8shift-worktree.py`: optional isolated worktree companion for parallel feature
  work with serialized integration;
- `examples/headless_runner.py`: reference pattern for headless loops and heartbeat;
- documentation and website pages for quickstart, VS Code-style UI operation,
  Linux/macOS/Windows, worktree toolbox, limitations, roadmap, and security notes;
- RFCs for runtime companion, hosted/runtime control plane, provider management, and
  shared-tree degree > 1 research.

Stage 6 therefore should focus on adoption, operator visibility, and host integration,
not on changing the core mutex.

## 3. Decision summary

| Candidate | Value | Effort | Risk | Decision |
|-----------|-------|--------|------|----------|
| Release artifacts and install recipes | High | Low | Low | Mostly shipped; tag/public release remains |
| Local watch/status UX improvements | High | Low | Low | Shipped; continue incrementally |
| Headless runner hardening | High | Medium | Medium | Do next |
| Provider registry | High | Medium | Medium | Do after runner contract |
| IDE status panel / task integration | Medium | Medium | Medium | Do as thin local integration |
| Local notifications | Medium | Low/Medium | Medium | Do only as opt-in companion |
| MCP adapter | Medium/High | Medium | High | Design carefully, read-only first |
| Orchestrator integration | Medium | Medium/High | High | Keep as recipes/adapters, not core |
| Hosted/runtime control plane | High for teams | High | High | Defer until local companion proves value |
| Package distribution | Medium | Medium | Medium | Useful, but keep single-file install first |
| True degree > 1 in one shared working tree | Low/Research | High | High | Keep rejected for the core |

## 4. Priority plan

### 6A — Release artifacts and install recipes

**Status:** mostly shipped.

**What remains:**

- public release artifacts generated from a signed/reviewed tag.

**Already shipped:**

- downloadable tracked scripts;
- `checksums.sha256`;
- Linux/macOS shell installer;
- Windows PowerShell installer;
- worktree toolbox install/copy recipes;
- version surfaces on all distributed scripts.

**Value added:**

- removes ambiguity for new users;
- makes "which file should agents use?" explicit;
- reduces broken setups caused by copying a stale script from the repo.

**Boundary:**

- no installer daemon;
- no package manager required for normal use;
- release artifacts are convenience copies of tracked scripts.

### 6B — Local operator UX

**Status:** shipped as a local read-only core command.

**What remains:**

- provide recommended terminal layouts for multi-agent sessions;
- add example shell aliases:

```bash
alias m8s='python3 m8shift.py status --for'
alias m8w='python3 m8shift.py watch --interval 5 --for'
```

**Value added:**

- reduces the repeated "is it my turn?" manual loop;
- makes interactive UI operation less fragile;
- improves trust without changing relay semantics.

**Boundary:**

- `watch` remains read-only;
- no notification or auto-recovery inside the core.

### 6C — Headless runner hardening

**What remains:**

- turn `examples/headless_runner.py` from reference example into a supported companion
  or documented recipe;
- define a stable run-plan format;
- record run ids in advisory turn fields such as `x_run_id`;
- improve failure modes: claimed-but-no-append, repeated heartbeat without progress,
  interrupted process, and stale lane;
- add tests around runner behavior without invoking real provider CLIs.

**Value added:**

- enables reliable unattended or semi-attended loops;
- reduces the need for humans to manually resume each agent UI;
- creates the foundation for provider management and local notifications.

**Boundary:**

- runner must still call `m8shift.py claim` and `append`;
- no hidden route decisions;
- no provider credentials in M8Shift files.

### 6D — Provider registry

**What remains:**

- implement or prototype a gitignored provider config, as specified by
  [rfc-provider-management.md](rfc-provider-management.md);
- map roster identities to commands and capabilities;
- distinguish `interactive`, `headless`, and `hybrid` surfaces;
- render commands as argv arrays, never shell strings;
- validate missing credentials and unsupported capabilities with clear host-side
  errors.

**Value added:**

- makes `claude`, `codex`, `gemini`, `vibe`, and other roster names operationally
  meaningful to a host runner;
- prevents hard-coded assumptions about provider CLIs;
- gives humans a visible capability model before dispatching work.

**Boundary:**

- no provider SDK in `m8shift.py`;
- no automatic provider selection by hidden scoring;
- core claimability never depends on provider metadata.

### 6E — IDE status panel / task integration

**What remains:**

- start with lightweight recipes before a full extension:
  - VS Code tasks that run `status`, `watch`, `next`, and `append --wait`;
  - terminal panel layout guidance;
  - optional problem matcher for stale locks;
- later, a thin extension may read `status --json` and show current holder / next
  action.

**Value added:**

- puts M8Shift state where users already operate agents;
- reduces the mismatch between a terminal wait process and an interactive chat UI;
- helps avoid the "Claude is awaited, but the user is talking to Codex" deadlock.

**Boundary:**

- IDE integration should display and prompt; it must not bypass the core commands;
- extension state must not become a second source of truth.

### 6F — Local notifications

**What remains:**

- optional companion command that watches `status --json`;
- notification on:
  - "you are awaited";
  - stale `WORKING_*`;
  - repeated heartbeat without append;
  - request for cooperative turn transfer, if that RFC ships;
- platform-specific backends kept optional.

**Value added:**

- useful for humans supervising several agent panes;
- reduces missed handoffs.

**Boundary:**

- notification means "look at this", not "the agent has been woken";
- no auto-claim or auto-force.

### 6G — MCP adapter

**What remains:**

- read-only MCP tools first:
  - `status`;
  - `history`;
  - `peek`;
  - `task list`;
  - `watch`/subscription-like status snapshots if the host supports it;
- mutating tools later, only if they expose the same explicit commands:
  - `claim`;
  - `append`;
  - `release`;
  - `done`;
  - `task add/done/drop`;
- clear approval requirements for every mutating action.

**Value added:**

- lets host agents inspect relay state through a structured tool instead of shell
  parsing;
- can reduce prompt drift and manual command mistakes.

**Boundary:**

- MCP must not interpret the turn content to route work;
- no tool should silently write the repository;
- mutating tools must preserve exact M8Shift semantics and auditability.

### 6H — Orchestrator integration

**What remains:**

- recipes for using M8Shift from external orchestrators;
- strict adapter contract: one M8Shift turn in, one M8Shift turn out;
- post-run verification against `status --json`;
- no automatic merge/deploy/publish without host approval.

**Value added:**

- lets M8Shift complement full agent runtimes instead of competing with them;
- keeps repository ownership explicit even when a runtime launches the agents.

**Boundary:**

- orchestrator routing must not replace the core baton;
- M8Shift remains the repo-level coordination layer.

### 6I — Hosted/runtime control plane

**What remains:**

- implement only after local companion patterns prove useful;
- define sidecar retention, auth, audit, lane ownership, and notification semantics;
- decide whether it belongs in this repository or a separate package/project.

**Value added:**

- high for teams running many sessions or long-running headless workflows;
- enables dashboards, lanes, operator inboxes, and persistent progress views.

**Boundary:**

- must be optional;
- deleting runtime sidecars must leave the core relay usable;
- never store provider secrets in `M8SHIFT.md`.

## 5. Recommended order

1. **Release/install discipline**: artifacts, checksums, copy/upgrade recipes.
2. **Site/docs sync**: expose `watch`, Stage 4 status, and Stage 6 boundaries clearly.
3. **Headless runner hardening**: stable local runner contract and failure handling.
4. **Provider registry prototype**: map roster names to safe argv templates.
5. **IDE/task recipes**: no extension required yet; use tasks and terminals first.
6. **Read-only MCP adapter**: structured inspection before mutation.
7. **Optional local notifications**: companion-only, no wake guarantee.
8. **Hosted/runtime control plane**: defer until the local model has real usage data.

## 6. Non-goals

Stage 6 must not introduce:

- provider credentials in core files;
- a required daemon;
- a required hosted service;
- model/provider brokering inside `m8shift.py`;
- hidden automatic agent selection;
- automatic filesystem writes without a successful `claim`;
- auto-force recovery of a still-valid `WORKING_*`;
- package distribution that makes `cp m8shift.py` second-class.

## 7. Acceptance criteria

Stage 6 is healthy when:

- a new user can install or copy the correct scripts without reading the source tree;
- an operator can watch a relay without repeatedly running `status`;
- a headless run can execute one turn and prove it did not bypass the core baton;
- a provider registry can launch or describe agents without editing `m8shift.py`;
- an IDE or MCP integration can inspect state without creating a second authority;
- every mutating integration action is auditable as a normal M8Shift command;
- the core still works offline, with Python stdlib only, as one file.

## 8. Relationship to existing RFCs

This RFC is an umbrella for Stage 6. It does not replace:

- [rfc-runtime-companion.md](rfc-runtime-companion.md): local runtime/presence ideas;
- [rfc-hosted-runtime-control-plane.md](rfc-hosted-runtime-control-plane.md): broader
  hosted/runtime control-plane boundary;
- [rfc-provider-management.md](rfc-provider-management.md): provider adapter registry;
- [rfc-cooperative-turn-request.md](rfc-cooperative-turn-request.md): cooperative baton
  negotiation for interactive UI deadlocks.

Stage 6 should implement these pieces incrementally, starting with low-risk local
adoption improvements before any hosted or provider-running surface.
