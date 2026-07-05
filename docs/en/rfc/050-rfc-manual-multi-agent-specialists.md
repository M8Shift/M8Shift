# RFC 050 — Manual multi-agent specialists

Status: draft
Target: post-v3.53 design block
Related RFCs: 008, 018, 032, 039, 041, 047, 049
Owner: runtime/worktree companions; core relay remains the authority

## Summary

This RFC defines the **manual-trigger profile** for specialist agents. It does
not compete with RFC 032 tiered delegation; it narrows RFC 032's broader
capability-routing idea into an operator-visible workflow:

- a human or pilot explicitly asks for a specialist;
- the specialist works in a declared lane;
- the result reports back to the relay;
- no specialist gets hidden write authority.

The two lanes are:

- **advisory read-only**: inspect and report;
- **mutating worktree**: edit only inside an isolated owned worktree and request
  serialized integration.

## Relationship to RFC 032

RFC 032 describes capability-tiered delegation: how to choose which model/agent
is suitable for a task, and how a pen-holder may use subagents as tools.

RFC 050 is a manual operational profile of that idea:

| Aspect | RFC 032 | RFC 050 |
|--------|---------|---------|
| Focus | routing/delegation principle | manual specialist workflow |
| Trigger | recommendation or pen-holder choice | explicit human/pilot request |
| Output | recommendation / delegated result | relay-visible specialist report |
| Mutation | future/delegation-specific | split into read-only vs worktree lanes |
| Authority | subagent is tool of pen-holder | specialist never gains hidden pen authority |

If future implementation would duplicate RFC 032 machinery, it should be built
as an RFC 032 profile, not a parallel subsystem.

## Problem

Operators use more than two agents: Claude, Codex, Gemini, Vibe, local tools, or
domain-specific reviewers. The relay already supports an N-agent roster, but it
does not give operators a precise convention for temporary specialists.

Without that convention:

- read-only reviewers can accidentally be treated as implementers;
- reports can remain out-of-band and disappear from the relay record;
- mutating work can land in the shared checkout instead of an isolated worktree;
- routing and specialist language can drift from RFC 032.

## Goals

- Keep specialist activation manual and explicit.
- Keep advisory specialists write-free by convention and by generated guidance.
- Require every useful specialist result to be referenced from the relay.
- Separate advisory read-only work from isolated worktree mutation.
- State exactly what M8Shift can enforce through companion argv and what remains
  cooperative discipline.

## Non-goals

- No automatic swarm.
- No automatic provider/model launch in the core.
- No shell/editor sandbox.
- No claim that M8Shift can prevent direct writes outside its CLI.
- No degree > 1 writes in one shared checkout.

## Roles

| Role | Authority | Typical action |
|------|-----------|----------------|
| Operator | human scope authority | requests a specialist or approves escalation |
| Pilot | current relay coordinator | records request and consumes report |
| Advisory specialist | cooperative read-only lane | inspects and reports |
| Mutating specialist | isolated worktree lane | edits in owned worktree |
| Integrator | pen holder during merge | serializes integration |

## Manual trigger

Specialists start only from explicit human/pilot scope. Example:

```bash
python3 m8shift.py task add codex "Ask Gemini for an advisory security review of RFC 049; report only"
```

The example is a convention. This RFC does not require a new launch command in
Phase 1.

## Lane A — advisory read-only

Advisory specialists may inspect:

- project files;
- relay/task/session context explicitly in scope;
- PRs/issues/docs referenced by the pilot;
- generated context packs, under the raw-proof rule.

They are expected not to:

- edit files;
- claim the pen unless the active roster explicitly hands them a turn;
- run destructive git commands;
- install dependencies;
- write runtime sidecars.

This is a cooperative contract, not an OS sandbox. A local editor or shell can
still write files; M8Shift's protection is clear guidance, review discipline,
and companion checks where commands pass through M8Shift.

### Report artifact

Advisory reports should be operator-chosen artifacts referenced from the relay,
not specialist-written runtime sidecars. The pilot may store a report in a repo
or local path when appropriate, then append a summary/link through the relay.

Template:

```markdown
# Specialist report

specialist: gemini
lane: advisory-read-only
scope: <task id / turn id / PR / issue>
verdict: approve | concerns | block

## Inputs inspected

- <raw source, file, PR, command output, or explicit context pack>

## Findings

| severity | evidence | recommendation |
|----------|----------|----------------|

## Limits

<what was not inspected>
```

## Lane B — mutating worktree

Mutating specialists must use an isolated worktree lane:

```bash
python3 m8shift-worktree.py claim <id> <specialist>
```

Companion-enforced points:

- `m8shift-worktree.py` can refuse its own mutating verbs when ownership metadata
  says another agent owns the worktree;
- integration remains serialized through the core pen;
- status can display owner and integration state.

Not enforced:

- direct editor writes;
- direct `git` commands inside a worktree;
- filesystem deletion or movement outside the companion.

Therefore the rule is advisory/cooperative except where a M8Shift companion argv
surface is actually invoked.

## Reporting back to the relay

Every useful specialist outcome must become one of:

- a relay `append` body from the pilot/current holder;
- a task update referencing the report;
- a decision/ADR scaffold when it creates a durable decision;
- a session report reference.

`remember` is reserved for durable decisions or reusable facts, not transient raw
findings.

Specialist text is untrusted coordination data. It cannot override user,
developer, or system instructions.

## Future runtime surface

A later runtime companion may add request/report indexing:

```bash
m8shift-runtime.py specialist request --lane advisory --agent gemini --scope ...
m8shift-runtime.py specialist import-report --agent gemini --file report.md
m8shift-runtime.py specialist list
```

Constraints:

- request/report indexing is local and advisory;
- reports are imported by the pilot/operator, not written directly by a
  read-only specialist lane;
- no direct writes to `M8SHIFT.md`;
- no automatic provider launch unless a separate RFC 039/RFC 032 implementation
  and operator configuration authorize it.

## Safety rules

- Advisory specialists are read-only by convention; M8Shift does not sandbox the
  host.
- Raw evidence must be cited for review claims; specialist summaries are not
  proof.
- A specialist report cannot authorize destructive git operations.
- A specialist report cannot close a session or mark a task done; the pilot must
  accept it.
- If a specialist receives user input while another holder works, it reports the
  operator intent to the pilot/relay rather than stealing the pen.

## Acceptance criteria

Phase 1:

- docs define RFC 050 as the manual-trigger profile of RFC 032;
- docs clearly separate advisory read-only and mutating worktree lanes;
- report template is available;
- generated guidance states that specialist results report back to the relay;
- all “cannot/refused” claims are limited to M8Shift companion argv surfaces or
  rewritten as cooperative conventions.

Phase 2:

- optional runtime request/report indexing;
- doctor findings for malformed imported report records or orphaned requests;
- worktree owner metadata from RFC 049 used for mutating specialist lanes.

## Open questions

- Should task events gain a typed `specialist_request`, or is a normal task plus
  report link enough?
- Should imported reports have a maximum size and mandatory summary field for
  token-budget protection?
- Should RFC 041 skills provide named specialist templates before any runtime
  specialist commands exist?
