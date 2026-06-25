# RFC input — Neutral runtime patterns inventory

- **Status:** curated input for future RFCs; not an implementation plan by itself
- **Scope:** reusable agent-orchestration patterns that can inform M8Shift companions
- **Core invariant:** patterns listed here must not weaken the passive core or the
  one-pen handoff model

## 1. Context

This document replaces raw architecture notes with a neutral inventory aligned with
the current M8Shift codebase.

M8Shift already ships a working core:

- one-writer mutex through `claim -> work -> append`;
- N-agent roster;
- directed handoffs;
- task ledger;
- memory;
- session history;
- local time display;
- `watch`;
- Stage-4 contract validation;
- reference headless runner;
- worktree companion for isolated parallel work.

The patterns below are therefore not "MVP core" work. Most belong to a future
runtime companion, provider manager, or control plane.

## 2. Retain now: already aligned with the shipped core

| Pattern | Current M8Shift surface | Keep because |
|---------|-------------------------|--------------|
| Durable handoff record | `M8SHIFT.md` turns | coordination remains readable, grep-able, and versionable |
| Explicit handoff contract | `append --ask/--done/--files` + advisory fields | reduces vague delegation |
| One active writer | core `LOCK` | avoids shared-tree write races |
| Session history | `M8SHIFT.sessions.jsonl` + `history` | makes sessions auditable |
| Task ledger | `M8SHIFT.tasks.md` | tracks work without becoming a scheduler |
| Validation metadata | Stage-4 contract fields and `doctor --contracts` | supports review without making the core a policy engine |
| Local watch/status UX | `watch`, `status --json` | reduces missed handoffs |
| Isolated parallel work | `m8shift-worktree.py` | gives parallelism without multiple writers in one checkout |

These are not future patterns. They are shipped baseline.

## 3. Retain for a future runtime companion

### 3.1 Persistent run state

Keep under generated sidecars, not in the core:

```text
.m8shift/runs/<run-id>/
  state.json
  events.jsonl
  artifacts/
  approvals/
  reports/
```

Value: resume, audit, reports, failure diagnosis.

Boundary: deleting run sidecars must not corrupt `M8SHIFT.md`.

### 3.2 Agent registry

Keep in host/runtime configuration:

```toml
[[agents]]
name = "codex"
mode = "headless"
anchor = "AGENTS.md"
argv = ["codex", "exec", "$M8SHIFT_PROMPT"]
capabilities = ["read_repo", "write_repo", "run_tests"]
```

Value: maps roster names to real tools without provider coupling in the core.

Boundary: secrets and account metadata stay outside tracked files.

### 3.3 Role registry

Keep as versioned behavioral contracts:

```text
.m8shift/roles/coordinator.md
.m8shift/roles/implementer.md
.m8shift/roles/reviewer.md
```

Value: separates "which tool runs" from "which responsibility is active".

Boundary: one agent turn should carry one active role; self-approval remains invalid
unless explicitly waived by a human.

### 3.4 Permission and approval model

Keep in a companion/policy layer:

```yaml
approval_gates:
  - id: approve-push
    before: ["git_push"]
    required_by: ["human"]
```

Value: prevents host runners from performing sensitive actions silently.

Boundary: the core may record approval metadata, but it does not become an
authorization server.

### 3.5 Artifact tracking and run reports

Keep as generated artifacts:

```markdown
# Run Report

## Workflow
code-review

## Status
approved

## Changed files
- src/parser.py

## Checks
- tests: passed
```

Value: makes review and handoff easier.

Boundary: reports are evidence, not routing authority.

## 4. Adapt before implementing

| Pattern | Adaptation required |
|---------|---------------------|
| Workflow graphs | start with linear/declarative workflows; no full graph engine in core |
| Typed messages | reuse existing turn fields and `x_*` advisory fields first |
| Human operator messages | use runtime inbox sidecars; do not mix arbitrary UI chat into source-of-truth state |
| Flow vs collaborative mode | document as runtime modes; core still only enforces the pen |
| Observability | local JSONL sidecars and reports first; no mandatory dashboard |
| Agent charters | prefer explicit `ROLE.md` / `CHARTER.md` naming in defaults; avoid anthropomorphic claims |

## 5. Delay or reject

| Pattern | Decision | Reason |
|---------|----------|--------|
| Heavy graph runtime dependency | reject for core | breaks single-file/stdlib property |
| Cloud-first orchestration | reject for core | local operation must remain normal path |
| Mandatory web UI | reject | terminal/file workflow must remain complete |
| Mandatory vector memory | reject | memory should stay simple and inspectable unless an optional companion proves value |
| Autonomous provider selection | reject | hidden scoring is not auditable enough for a coordination tool |
| Self-approval | reject by default | implementer and reviewer responsibilities must be distinct |
| Unstructured chat logs as source of truth | reject | source of truth must be structured enough to parse and audit |
| True degree > 1 writes in one shared checkout | reject for core | use isolated worktrees and serialized integration instead |

## 6. Candidate future RFCs

The useful follow-up RFCs are:

1. **Runtime companion configuration schema** — `.m8shift/project.toml`,
   `.m8shift/agents/`, `.m8shift/roles/`, `.m8shift/workflows/`.
2. **Permission and approval gates** — host-side policy model, approval records,
   sensitive-action taxonomy.
3. **Runtime run state and reports** — run directories, events, artifacts, summaries,
   failure recovery.
4. **Operator inbox and progress channel** — structured human interventions and
   progress events for UI/headless sessions.
5. **Provider registry integration** — argv-safe adapter config and capability
   declarations.

## 7. Recommendation

Use these patterns to design optional companions, not to expand `m8shift.py`.

The practical path is:

1. keep the core passive and stable;
2. implement runtime state as generated sidecars;
3. keep provider and approval policy outside tracked relay files;
4. require every write-producing runtime action to go through `claim -> work -> append`;
5. treat dashboards, hosted control planes, and richer workflows as later layers.
