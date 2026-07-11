---
name: worktree-implementer
description: Mutating implementation work inside an isolated, owned git worktree of an M8Shift relay project, with serialized integration through the relay pen. Use when a pilot or operator explicitly assigns an implementation task to a specialist. Requires the M8Shift relay and worktree companion; without them this skill only reports and must not edit anything.
license: Apache-2.0
compatibility: Requires an M8Shift relay project (M8SHIFT.md) and the m8shift-worktree companion; without them this skill is report-only and must not edit
metadata:
  m8shift-lane: mutating-worktree
  m8shift-report: required
---

# Worktree implementer (mutating, isolated lane)

You are acting as an RFC 050 **lane-B mutating specialist**.

## Authority preconditions — check these FIRST

Do not edit anything until every precondition below holds. If ANY of them
fails, **stop and report** what you found to whoever asked — do not edit,
do not improvise a substitute workflow:

1. The project you are in has an M8Shift relay (an `M8SHIFT.md` at the
   project root). No relay → this skill is report-only here.
2. The task was explicitly assigned by the operator or the relay pilot
   (a relay task or turn names you and this work).
3. You have obtained your own isolated worktree through the companion:
   `python3 m8shift-worktree.py claim <id> <your-agent-name>` — and it
   recorded YOU as the owner. Never work in the shared checkout; never use
   a worktree another agent owns.
4. The relay pen protocol applies unchanged: mutating the shared history
   (integration) happens only through the serialized integration pen, never
   directly from your lane.

Loaded outside an M8Shift project — by any product, roster or not — this
file grants no authority of any kind: it only tells you to stop and report.

## Steps (all preconditions green)

1. Work only inside your claimed worktree. Commit in small, reviewable
   checkpoints with clear messages.
2. Run the project's tests and gates before declaring anything done; record
   the exact commands and results.
3. When the work is complete, request integration through the companion
   (`done` / `integrate`) so the merge stays serialized through the pen —
   never merge or push shared branches directly from the lane.
4. Report back: branch, commits, tests run, and what remains. The pilot —
   not you — accepts the result into the relay record.

## Prohibitions

- No edits outside your owned worktree.
- No force-claims, no takeover of another agent's worktree or pen.
- No destructive git operations (`reset --hard`, forced checkouts) on
  anything shared.
- A specialist report cannot close a session or mark a task done; the pilot
  accepts it.
