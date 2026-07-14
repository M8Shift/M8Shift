# RFC 065 — Ticketed, committed, and pushed delivery

- **Status:** draft / design only (#72)
- **Date:** 2026-07-14
- **Scope:** repository contribution and delivery discipline for every agent;
  documentation and advisory local checks only, with no network authority in the core.
- **Builds on:** [RFC 006](006-rfc-tasks.md),
  [RFC 031](031-rfc-decision-traceability.md),
  [RFC 048](048-rfc-adoption-discipline-pack-update-health.md),
  [RFC 053](053-rfc-shared-rules-governed-habits.md), and
  [RFC 058](058-rfc-go-forward-rfc-discipline.md).

## 0. Proposal summary

Every intentional version-controlled change destined for integration has one
structured forge ticket and reaches review as committed, pushed Git history. A local
edit, local commit, opened issue, branch, or draft PR is not delivered by itself.

The normal order is:

```text
forge ticket -> linked branch -> edit + validate -> commit -> push -> review/PR -> merge -> structured ticket close
```

An agent whose sandbox cannot reach the project forge uses a named **forge gateway**.
That agent still validates and commits locally, then hands the exact branch and commit
SHA to the gateway. The gateway reviews the immutable handoff, creates/reconciles the
ticket, pushes that exact history, opens the PR, and records the remote evidence. This
is a transport exception, not a ticket or push waiver.

For the current project topology, Codex is the network-isolated author and Claude is
the forge gateway. The contract is role-based so another project can assign different
agents without changing the policy.

## 1. Why the existing rules are insufficient

The agent guide and issue-lifecycle page already say that every work unit uses a forge
ticket. RFC 058 requires a same-PR RFC for substantive changes. The agent pack says an
issue, branch, or PR alone is not done. Three gaps remain:

1. the temporary relay-task fallback does not say when reconciliation is mandatory;
2. a local commit can be reported complete without a recoverable remote copy;
3. a network-isolated author cannot self-push even when another relay agent can safely
   transport the exact commit.

This RFC makes the delivery boundary explicit and gives offline work a governed path.

## 2. Normative delivery contract

### 2.1 Change unit

A **change unit** is one coherent, intentional modification to version-controlled
source, tests, documentation, configuration, workflows, hooks, assets, or release
metadata meant to enter the repository. A requested revision is another checkpoint of
the same ticket unless scope or acceptance materially diverges; then it receives a new
linked ticket.

Exploratory reads/tests with no intended diff, generated relay state, ignored scratch
files, caches, worktree metadata, and server-generated merge refs are not independent
change units. This exclusion does not authorize committing relay artefacts or bypassing
the pen; repository writes still require active relay write authority.

### 2.2 Ticket before implementation

Normally the structured forge ticket exists before the first implementation edit. It
uses the established create template and defines goal, scope, acceptance, roles,
workflow, RFC impact, provenance, and decision log. The branch and PR link the ticket;
decisions and verification are recorded as work progresses; merge is followed by the
structured close template.

A relay task is intake evidence, not a substitute for the forge record. If the forge is
unavailable, the task may temporarily hold intent, but it must be reconciled before the
first remote publication or integration. An outage never permits an untracked merge.

### 2.3 Commit every completed checkpoint

Before handing a coherent change to another agent for review or transport, the author:

1. validates it in proportion to risk;
2. commits all intended files and no unrelated work;
3. records the local branch and full commit SHA in the handoff;
4. reports any remaining dirty state explicitly.

This does not require a commit per keystroke or a knowingly broken snapshot. It makes
every claimed checkpoint, including a review correction, durable and unambiguous. A
gateway does not silently amend, squash, or rebase the handed-off commit; a coordinated
rewrite produces a replacement SHA and a new handoff.

### 2.4 Push every delivered checkpoint

In a network-capable lane, the author pushes the branch head before requesting remote
review and reports the remote branch plus exact SHA. Every correction is committed and
pushed before it becomes the new review head.

Delivery is incomplete until the forge contains the structured ticket, handed-off
history on a remote branch, a ticket-linked PR/MR when integration is requested, and
the required decision/verification record. The branch may later be merged and deleted;
the ticket and PR retain the durable trace.

## 3. Direct and gateway flows

### 3.1 Direct flow

```text
open ticket -> linked branch -> implement -> validate -> commit
            -> push exact SHA -> open/update PR -> independent review
            -> merge -> structured close -> delete merged branches
```

The author appends the relay handoff after push, reporting ticket, branch, SHA, test
evidence, and the precise review ask.

### 3.2 Forge-gateway flow

When policy or sandboxing blocks the author's forge network access:

1. **Author:** works in an isolated branch, validates, commits, and checks worktree
   state.
2. **Author:** hands off the relay task, branch, full local SHA, files, verification,
   named gateway, and requested remote action. It labels delivery **gateway pending**,
   not remotely delivered.
3. **Gateway:** claims and reads the pending turn, then reviews that exact commit. If
   changes are needed it returns a bounded ask; the author makes a new commit and
   repeats the handoff.
4. **Gateway:** creates or reconciles the structured forge ticket before first push,
   linking the relay task and local SHA without copying sensitive relay output.
5. **Gateway:** pushes the reviewed history without rewriting it, opens/updates the
   linked PR, and records remote branch and SHA.
6. **Gateway:** merges only after normal validation/review, closes the ticket with the
   structured template, and reports remote evidence through the relay.

The gateway owns remote transport and forge records; it does not become code author by
pushing. Commit authorship and agent/model trailers remain unchanged. If transport
fails, the local commit stays pending and nobody claims it was pushed or delivered.

## 4. Evidence and completion language

| Evidence | Direct author | Network-isolated author | Gateway |
|---|---|---|---|
| Forge ticket | id/URL | relay task + `gateway pending` | create/reconcile id/URL |
| Branch | local + remote | local branch | remote branch |
| Commit | full SHA | full local SHA | same pushed SHA |
| Validation | commands/results | commands/results | review + independent checks |
| PR and close | create/update/close | not claimed | create/update/close |

Terms remain precise:

- **locally committed**: Git contains the intended checkpoint locally;
- **pushed**: the authoritative forge has the SHA on the named remote branch;
- **reviewed**: an independent agent assessed that exact SHA;
- **delivered**: ticket, pushed history, and linked integration record exist;
- **done**: the accepted change is implemented, verified, committed, pushed, reviewed,
  integrated/closed as scoped, and the ticket is closed cleanly.

An agent does not infer remote state from a local remote-tracking ref alone. Forge URLs,
branch names, and SHAs are references; copied status pages and summaries are not proof.

## 5. Documentation and advisory reminders

Acceptance would amend these surfaces in the implementation PR:

- `M8SHIFT.agent-pack.md`: every change needs a forge ticket and every completed
  checkpoint is committed/pushed; define gateway-pending language.
- `docs/en/agents-guide.md` and `docs/en/issue-lifecycle.md`: require reconciliation
  before publication and document the gateway flow.
- RFC 058: add ticketed, commit-and-push delivery beside same-PR RFC discipline.
- RFC 053: clarify that a directly approved repository policy does not await learned-
  rule evidence or companion promotion.

Local tooling remains advisory and offline:

1. **Pre-commit reminder:** for a non-empty staged repository change, print one stable
   reminder to confirm its forge ticket and push the completed checkpoint before
   delivery; an isolated author instead names the gateway-pending handoff. It does not
   contact a forge, mutate relay state, or block humans.
2. **Doctor upstream advisory:** in a Git checkout, a bounded read-only check may report
   `delivery.no_upstream` for a non-default branch without an upstream and
   `delivery.unpushed` when `HEAD` is ahead of its local upstream ref. It labels this
   local evidence and never claims the remote is current.

Ticket existence is reviewed on the forge. A local heuristic based on `#123`, branch
names, or commit prose would confuse relay tasks, issues, and PRs, so v1 does not
pretend to verify it. No core command receives credentials or network access.

## 6. Safety and failure handling

- Ticket/push discipline never bypasses `claim -> work -> append`; Git/forge access
  does not grant the relay pen.
- The gateway is named. No agent silently assumes another agent's credentials or
  remote authority.
- No credential, private forge transcript, LAN address, or foreign project identity is
  persisted in project artefacts.
- Pushes are non-destructive. Force-push, rebase of handed-off history, or deletion of
  an unmerged branch still needs explicit coordination and tool authorization.
- Forge outage leaves the change committed and pending, not delivered or merged.
- Emergency fixes still receive ticket and remote trace before merge; urgency may
  shorten review but does not erase provenance.

## 7. Implementation phases

1. **Policy:** accept this RFC; amend RFCs 053/058, the agent pack, guide, and issue
   lifecycle with direct/gateway contracts.
2. **Reminders:** add the stable pre-commit reminder and bounded doctor findings,
   advisory and no-network.
3. **Verification:** cover staged/no-change reminders; upstream absent, ahead, equal,
   detached, and non-Git cases; fail-open behavior; generated-pack parity; Python 3.8;
   and existing checksum/pen-guard ordering.
4. **Dogfood:** run one direct and one author/gateway change, proving ticket-to-SHA
   trace without rewriting or overstating remote evidence.

## 8. Acceptance criteria

1. Every intentional repository change maps to one structured forge ticket before
   remote publication or integration.
2. Every handoff checkpoint is validated and committed; every remotely delivered
   checkpoint exists on the forge at the reported SHA.
3. A network-isolated author uses gateway-pending and never calls a local commit pushed.
4. The gateway reviews the exact SHA, creates/reconciles the ticket before first push,
   preserves history, and reports remote evidence.
5. Relay tasks are temporary intake only and are reconciled before publication.
6. The agent pack, guide, lifecycle, RFC 053, and RFC 058 agree on the contract.
7. Local findings are stable, advisory, credential-free, and honest about limits.
8. “Done” is not reported for an issue, local-only commit, unpushed branch, draft PR,
   or unclosed integration record by itself.

## 9. Non-goals

- forge credentials/network access in the core relay;
- automatic ticket creation, push, PR, merge, or close;
- local refs or hooks presented as proof of forge state;
- commits for transient relay state or each editor save;
- replacement of independent review or the structured issue lifecycle;
- hard-coding Claude/Codex into the portable policy.
