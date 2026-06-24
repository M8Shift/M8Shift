# RFC — True degree > 1 writes in one shared working tree

- **Status:** research RFC; rejected for the current core
- **Scope:** concurrent writes by multiple agents in the same checkout
- **Core invariant:** the shipped M8Shift core remains degree-1

## 1. Problem

The tempting next step after an N-agent roster is to let several agents write the
same working tree at once when their file sets do not overlap. In theory:

- Claude edits `docs/`;
- Codex edits `src/parser.py`;
- Gemini edits images or prompts;
- all run concurrently in the same checkout.

This is **true degree > 1** inside one shared working tree. It is not the same as
the shipped `m8shift-worktree.py` model, which isolates each worker in a separate
git worktree and serializes integration.

## 2. Decision

Do **not** implement this in the M8Shift core.

The current answer for parallel work is the worktree companion: isolated trees,
independent commits, one serialized integration pen. Shared-tree degree > 1 is
kept as a research topic and must not weaken the core's single-pen guarantee.

## 3. Why it is tempting

Potential benefits:

- higher throughput for independent file areas;
- fewer worktrees to manage;
- simpler mental model for users who dislike branches;
- one visible checkout for all agents and the human.

The cost is that the filesystem becomes the coordination surface. A passive
single-file relay cannot reliably enforce that surface.

## 4. Hard requirements for any future experiment

A real shared-tree degree > 1 system would need all of the following:

| Requirement | Why |
|-------------|-----|
| Path leases | each writer owns explicit file/path ranges |
| Filesystem monitoring | detect edits outside leased paths |
| Dirty-state snapshots | know what changed before/after each writer |
| Conflict detection | catch overlapping writes, generated files, renames, deletes |
| Merge policy | define how concurrent changes are accepted or rolled back |
| Test ownership | know which checks validate which path lease |
| Human override | resolve ambiguous or policy-heavy conflicts |
| Crash recovery | release or quarantine abandoned path leases |

That is no longer a tiny mutex. It is a local orchestrator and filesystem monitor.

## 5. Risks

### 5.1 Hidden overlap

Two tasks can touch different files but still conflict:

- code + generated docs;
- schema + migration;
- package file + lock file;
- rename + import update;
- formatter touching the whole tree.

### 5.2 Tool behavior

Agent tools and formatters may edit files outside the intended scope. A passive
script cannot stop that.

### 5.3 Rollback ambiguity

If two agents edit the same checkout and one crashes, reverting only that agent's
work is hard unless every write was tracked at filesystem level.

### 5.4 False safety

An advisory path lease can look like enforcement. That would be worse than the
current honest single-pen model.

## 6. Rejected core design: path-scoped leases

Rejected shape:

```text
claim codex --paths src/parser.py,tests/test_parser.py
claim gemini --paths assets/
```

Why rejected for the core:

- it allows multiple writers in the same checkout;
- it requires the core to reason about file paths, globs, generated artifacts,
  deletes, renames, and formatters;
- it turns advisory metadata into routing authority;
- it breaks the "copy one file and operate by discipline" property.

## 7. Accepted alternative: isolated worktrees

The accepted model is already documented in
[rfc-worktree-companion.md](rfc-worktree-companion.md):

```text
main checkout          → serialized integration only
worktree feat-a        → agent A works
worktree feat-b        → agent B works
worktree feat-c        → agent C works
```

This gives real parallelism without two agents writing the same checkout at the
same time.

## 8. Possible future non-core experiment

A separate experimental companion could attempt shared-tree degree > 1 if it is
honest about being a different product surface.

Minimum properties:

- explicit `--experimental-shared-tree` opt-in;
- path leases stored outside the core `LOCK`;
- filesystem watcher;
- pre/post snapshots;
- automatic quarantine on unexpected writes;
- no interaction with core `claim` beyond integration handoff;
- strong warnings that this is not the default safety model.

## 9. Acceptance bar for reconsideration

This topic should not be reconsidered for the core unless a prototype proves:

- unexpected writes are detected;
- formatter-wide changes are handled;
- renames/deletes are safe;
- crash rollback is reliable;
- human override is audited;
- no path lease can bypass `append` provenance;
- tests cover simultaneous writers and conflict recovery.

Until then, the core remains degree-1 and the worktree companion remains the
parallelism story.

## 10. Final stance

This RFC documents the idea so it is not repeatedly rediscovered. The current
decision is:

- **core:** rejected;
- **companion:** use isolated worktrees;
- **research:** possible only as a separate experimental orchestrator.
