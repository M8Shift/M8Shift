# Issue lifecycle — open, decide, close (used by every agent)

M8Shift tracks every unit of work on a forge ticket, from a **structured open** to a
**structured close**, with the **decisions** recorded in between. This page is the canonical
convention; [agents-guide.md](agents-guide.md) §6 makes it mandatory for all agents.

The three artefacts, one per stage:

| Stage | Artefact | Where |
|-------|----------|-------|
| 🆕 **Open** | the **create template** (Goal · Context · Scope · Acceptance · Charter · Roles · Workflow · RFC · Decision log) | native forge templates — [`.gitea/issue_template/task.md`](../../.gitea/issue_template/task.md), [`.github/ISSUE_TEMPLATE/task.md`](../../.github/ISSUE_TEMPLATE/task.md), [`.gitlab/issue_templates/Task.md`](../../.gitlab/issue_templates/Task.md) |
| ⚖️ **Decide** | the **decision template** (Decision · Context · Options · Positions FOR/AGAINST · Divergence · Resolution · Trace) | [`docs/decisions/DECISION_TEMPLATE.md`](../../docs/decisions/DECISION_TEMPLATE.md) + the `decision` issue templates (RFC 031) |
| ✅ **Close** | the **close template** below | pasted into the closing comment |

Forges have a native *new-issue* template but **no native *close* template**, so the close
wrap-up lives here as a copy-paste convention rather than in `issue_template/` (which would
pollute the new-issue menu). It works identically on Forgejo, GitHub and GitLab (GFM tables).

## ✅ Close template

Paste this into the **closing comment** and fill every row before you close the ticket. A bare
`Closes #N` is not a close record.

```markdown
## ✅ Closed — <one-line outcome>

## 📋 Summary
| Field | Value |
|-------|-------|
| 📦 Delivered | <what shipped> |
| 🌿 Branch | `feat/…` (deleted on **both** remotes after merge) |
| 🔀 Merge | `<merge-commit>` · `Closes #N` |
| 🏷️ M8Shift version | vX.Y.Z (`m8shift.py --version`; or "unreleased — accumulates on main") |
| 🤖 Agents (models) | the model-versions that worked, e.g. `claude-opus-4-8` · `gpt-5-codex` (the `Agent-Model` trailers on the commits) |
| 🧪 Tests | <count> OK · checksums N/N |

## 🧠 Decisions taken
> Link the decision-template records + the key choices and their rationale (RFC 031).

## 🔍 Verification
> How it was verified — adversarial hunt/probe, full suite, checksums, byte-level — and what was proven.

## 🔗 Follow-ups
> Spun-off issues / deferred items (link them), or "none".
```

## Why structured both ends

An **open** that states Goal + Context + Scope + Acceptance lets any agent pick the ticket up
cold and know when it is done. A **close** that states outcome + decisions + verification lets a
future reader reconstruct *what shipped and why* without re-reading every commit. The **decision
template** in between makes a contested choice auditable — who argued what, and how it was
reconciled. Together they keep the forge a durable, tool-independent record of the work.
