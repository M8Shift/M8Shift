# RFC — Agent runtime architecture companion

- **Status:** analysis RFC; proposed for a future companion, not for the passive core
- **Scope:** local runtime/scaffold layer around M8Shift for roles, workflows, runs,
  permissions, approvals, and artifacts
- **Related RFCs:** [rfc-runtime-companion.md](rfc-runtime-companion.md),
  [rfc-stage6-integrations.md](rfc-stage6-integrations.md),
  [rfc-provider-management.md](rfc-provider-management.md),
  [rfc-hosted-runtime-control-plane.md](rfc-hosted-runtime-control-plane.md),
  [rfc-contracts-validation.md](rfc-contracts-validation.md)
- **Core invariant:** `m8shift.py` remains a single-file, stdlib-only, passive
  coordination relay. It owns `LOCK`, turns, claimability, and the one-pen mutex.

## 1. Problem

The current M8Shift core is deliberately small and reliable: it records who has the
pen, who is awaited, what was done, and which advisory contract fields were attached
to a turn.

That is enough for cooperative handoff, but not enough for a full local runtime that
can answer questions such as:

- which concrete agent tool should run for this role?
- which workflow step is active?
- which artifacts were produced by a run?
- which actions require human approval before execution?
- which permission profile applies to a task?
- which runtime process is alive, stalled, or waiting?

Those are runtime questions. They should be solved by an optional companion, not by
expanding the core relay into a framework.

## 2. Decision

Create a future **agent runtime companion** as a local-first layer around the passive
core. The companion may scaffold configuration and operate local workflows, but every
write handoff still goes through:

```text
claim -> work -> append/release/done
```

The companion can add structure. It cannot become a second authority for the pen.

## 3. Design principles

### 3.1 Separate by authority and change frequency

Files should be split only when they differ in authority level, lifecycle, or safety
profile.

| Concern | Frequency | Authority | Candidate location |
|---------|-----------|-----------|--------------------|
| Core handoff state | runtime | routing authority | `M8SHIFT.md` |
| Turn contracts | per turn | advisory/review | `append --field ...` |
| Task ledger | per task | advisory | `M8SHIFT.tasks.md` |
| Session history | per run/session | audit | `M8SHIFT.sessions.jsonl` |
| Agent registry | occasional | host/runtime config | `.m8shift/agents/` |
| Roles | occasional | behavioral contract | `.m8shift/roles/` |
| Workflows | occasional | runtime sequencing | `.m8shift/workflows/` |
| Permissions/approvals | critical | safety policy | `.m8shift/policies/` |
| Runtime presence/progress | volatile | diagnostic only | `.m8shift/runtime/` |
| Run artifacts/reports | generated | audit/support | `.m8shift/runs/` |

Do not fragment by default. Fragment only when it improves clarity, safety, or
maintainability.

### 3.2 Keep generated runtime state separate

Configuration may be versioned. Runtime state should usually be gitignored.

Versioned candidates:

```text
.m8shift/project.toml
.m8shift/agents/*.toml
.m8shift/roles/*.md
.m8shift/workflows/*.yaml
.m8shift/policies/*.md
.m8shift/README.md
```

Generated / ignored candidates:

```text
.m8shift/runtime/
.m8shift/runs/
.m8shift/cache/
.m8shift/tmp/
.m8shift/.venv/
```

`M8SHIFT.md`, `M8SHIFT.tasks.md`, `M8SHIFT.memory.md`, and
`M8SHIFT.sessions.jsonl` remain the existing relay-side records owned by the core.

## 4. Proposed local layout

```text
project/
├── m8shift.py                 # passive core, copied/installed explicitly
├── M8SHIFT.md                 # core relay state + turn journal
├── M8SHIFT.tasks.md           # advisory task ledger
├── M8SHIFT.memory.md          # optional shared memory
├── M8SHIFT.sessions.jsonl     # append-only session audit
└── .m8shift/
    ├── project.toml
    ├── agents/
    │   ├── codex.toml
    │   ├── claude.toml
    │   └── gemini.toml
    ├── roles/
    │   ├── coordinator.md
    │   ├── implementer.md
    │   └── reviewer.md
    ├── workflows/
    │   └── code-review.yaml
    ├── policies/
    │   └── approvals.md
    ├── runtime/               # generated, gitignored
    └── runs/                  # generated, gitignored
```

This layout is a companion surface. A project that only wants the core relay should
not need `.m8shift/` at all.

## 5. Concepts to keep

### 5.1 Agent registry

Keep. A runtime needs a host-side mapping from roster names to concrete surfaces:
interactive UI, headless CLI, local script, or future provider adapter.

The core only knows `agents: claude,codex,gemini,vibe`. The companion may know how
to run or prompt them.

### 5.2 Role registry

Keep. Roles should be stable behavioral contracts independent from concrete agents.
An agent can be implementer in one turn and reviewer in another; the active role
must be explicit to avoid self-approval and blurred accountability.

### 5.3 Typed messages and handoff contracts

Keep, but map them to existing turn contract fields first. The shipped `append`
surface already supports advisory fields such as `relation`, `decision`, `role_from`,
`role_to`, `tests`, `commit`, and custom `x_*` keys.

Future runtime messages should reuse these fields where possible before inventing a
parallel message format.

### 5.4 Persistent run state

Keep in the companion, not in the core. The reference headless runner already writes
`.m8shift/runtime/runs.jsonl`. A future runtime can extend that into structured run
directories:

```text
.m8shift/runs/<run-id>/
  state.json
  events.jsonl
  messages/
  artifacts/
  approvals/
  reports/
```

Deleting this directory must not corrupt the core relay.

### 5.5 Human approval gates

Keep as runtime policy. Approval gates are useful for destructive file operations,
dependency changes, pushes, deployments, legal text, external messages, and networked
actions.

The core can record approval status as advisory fields. The companion can decide not
to execute a host action until approval exists.

### 5.6 Validation hooks and artifacts

Keep. Validation hooks and artifact tracking are valuable in a runtime layer:

- tests and lint commands;
- reviewer approval;
- generated reports;
- changed-file lists;
- links to produced artifacts.

The core should continue to record outcomes, not execute arbitrary validation policy.

## 6. Concepts to adapt

### 6.1 Workflow graph

Adapt. A simple linear or declarative workflow can help a runtime:

```yaml
workflow:
  id: default-code-review
  steps:
    - id: plan
      role: coordinator
      next: implement
    - id: implement
      role: implementer
      next: review
    - id: review
      role: reviewer
      next: final
    - id: final
      role: coordinator
```

Do not implement a full graph engine in the core. Complex cycles, distributed
schedulers, visual graph tooling, and transaction systems remain out of scope.

### 6.2 Agent charter files

Adapt. The idea of a stable agent charter is useful, but avoid mystical naming in the
default scaffold. Prefer explicit names:

```text
ROLE.md
CHARTER.md
POLICY.md
TOOLS.md
```

If a user creates a differently named charter, documentation must define it as a
behavioral contract only, never as consciousness, subjective identity, or memory in a
human sense.

### 6.3 Permissions

Adapt. Permissions are advisory at the M8Shift layer and enforceable only by the host
runtime/sandbox. The core cannot prevent a non-cooperative process from editing files.
The companion may enforce permissions by refusing to run a command or by requiring
approval before dispatch.

## 7. Concepts to reject for the core

Reject these as core features:

- heavy runtime dependencies;
- provider SDKs;
- cloud-first orchestration;
- hosted dashboard dependency;
- full graph engine;
- mandatory vector memory;
- autonomous provider selection by hidden scoring;
- true degree > 1 writes in one shared working tree;
- any claim that M8Shift gives agents consciousness, emotion, or persistent human-like
  identity.

These can only appear, if ever, as optional companion surfaces with clear boundaries.

## 8. Suggested companion commands

Illustrative only:

```bash
m8shift-runtime init
m8shift-runtime agents list
m8shift-runtime roles list
m8shift-runtime run <workflow> --agent codex --once
m8shift-runtime approve <run-id> <gate-id>
m8shift-runtime report <run-id>
```

Each command that writes project files must first use the normal M8Shift relay when
the project is under active multi-agent coordination.

## 9. Acceptance criteria

A first runtime companion is acceptable when:

- it can be removed without breaking `m8shift.py`;
- it never writes `M8SHIFT.md` directly;
- it maps roster names to host commands without storing secrets in tracked files;
- it records run lifecycle events locally;
- it distinguishes agent, role, task, workflow, artifact, approval, and validation;
- it uses argv arrays, not shell strings;
- it documents which files are versioned and which are ignored;
- it supports one active runtime per agent lane;
- it keeps the core's one-pen invariant intact.

## 10. Open questions

- Should the companion use TOML, JSON, or YAML for configuration?
- Should workflow files live under `.m8shift/workflows/` or beside task files?
- Should role and policy files be initialized by `m8shift.py init` or only by a
  separate `m8shift-runtime init`?
- Which approval gates should be built in first?
- Should runtime reports be a generated Markdown artifact, JSON, or both?

## 11. Recommendation

Proceed only as a future companion RFC implementation. Do not fold this runtime
architecture into the passive core.

The immediate value is to formalize the boundary: M8Shift core coordinates the pen;
the runtime companion may coordinate processes, roles, approvals, and reports around
that pen.
