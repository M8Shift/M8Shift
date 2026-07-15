# RFC 072 — Exact-identity fleet bootstrap and launch automation

- **Status:** implemented (#85); slices 1–6 shipped
- **Scope:** declarative fleet planning, exact per-agent identity bootstrap,
  holder-attributed enrollment, and batch listener lifecycle.
- **Builds on:** [RFC 067](067-rfc-detached-vendor-neutral-cli-orchestration.md),
  [RFC 070](070-rfc-provider-pinned-model-launch.md), and
  [RFC 071](071-rfc-live-roster-add.md).

## Decisions

The operator accepted O1–O6 as recommended:

1. A new lane fails closed until a git-ignored, per-agent instruction artifact
   is loaded by its adapter at developer/system precedence and the exact roster
   identity is observable in conformance. A shared identity-neutral anchor and
   prompt-only identity claim are insufficient.
2. Fleet specs select a curated provider template and an explicit model. They
   cannot introduce arbitrary launch argv or inherit a global CLI model.
3. Applying membership is attributed to the current holder and delegates each
   addition to the core `roster add` command. The runtime has no standing pen.
4. Stopping a lane leaves roster membership intact. Offline is an observed
   runtime condition, not a relay membership mutation.
5. Scheduled work uses explicit immutable job specs and verification recipes;
   provider exit alone is never completion.
6. A relay-designated integrator owns merge, handoff, and worktree removal.
   Parallel producers never integrate themselves into the shared target.

## Slices 1–3

`m8shift.fleet.spec.v1` is a portable, operator-authored JSON document:

```json
{
  "schema": "m8shift.fleet.spec.v1",
  "agents": [
    {
      "name": "codex-2",
      "template": "codex",
      "model": "operator-selected-model-id",
      "desired": "running"
    }
  ]
}
```

`fleet plan` and `fleet health` are pure: they validate the schema and compare
the desired roster, provider row, identity artifact, and listener state without
writing. Missing templates, `UNSET`/implicit models, duplicate identities, or
invalid desired states fail before a plan is emitted.

`fleet apply --by HOLDER` materializes only a curated template, writes the exact
identity artifact below `.m8shift/runtime/identities/`, and delegates live
membership to `m8shift.py roster add NAME --by HOLDER`. Reapplying the same spec
is a no-op. Adapter launch compilation refuses a missing or mismatched identity
artifact and injects it at the provider's developer/system instruction tier.

`fleet reconcile` converges listener lifecycle for every row after bootstrap.
`fleet stop` and `fleet resume` are batch lifecycle intents; stop never removes
membership. All process work remains in the existing listener implementation,
including process-group termination, retry limits, usage holds, relay-only
completion, and restart diagnostics.

## Slices 4–6

`m8shift.fleet.jobs.v1` declares an ordered batch, its relay-designated
integrator, target branch, concurrency cap, and explicit producer jobs. Each job
fixes its objective, done criteria, producer, isolated branch, and shell-free
verification argv. `fleet jobs submit` creates immutable records; conflicting
retries fail closed. Attempts are sequential and append-only. The provider exit
is recorded first, but a job reaches `verified` only when its recipe exits zero
inside the assigned worktree.

`fleet jobs assign` is holder- and integrator-gated. It delegates worktree
creation to the RFC 008 companion, never places a producer on the shared target,
allows at most two active producer worktrees, and gives one active mutating lane
to any producer identity.

`fleet jobs integrate` requires verified evidence and the exact designated
integrator. It delegates the serialized merge and relay handoff to
`m8shift-worktree.py`, then drops the clean producer worktree through the same
companion. A producer cannot self-integrate. Runtime doctor checks missing or
orphaned worktrees, incomplete attempts, owner mismatch, concurrency overflow,
and incomplete drops without gaining any core authority.

These runtime sidecars add no authority to the passive core and do not weaken
O1–O6.

## Acceptance gates

1. Plan/health are byte-for-byte read-only for relay and provider state.
2. Template and explicit model are mandatory; arbitrary argv is not accepted.
3. A provider launch cannot proceed without the exact identity artifact.
4. Apply is holder-attributed, uses the core command, and is idempotent.
5. Batch stop leaves the roster, session, turn, and journal unchanged.
6. Reconciliation never launches an unbootstrapped or ambiguous identity.
7. Provider exit zero without recipe success is not completion.
8. Only the live designated integrator assigns isolated worktrees; concurrency
   never exceeds two and a producer owns at most one active mutating lane.
9. Only the designated integrator can merge, hand off, and drop a verified job.

## Acceptance proof

The deterministic scratch acceptance uses a fresh repository and three exact
roster identities. Two producer identities receive separate worktrees, commit
distinct outputs, and pass their own recipes. A producer self-integration is
refused byte-for-byte before relay mutation. The designated integrator then
serializes two merges, hands the relay to distinct recipients, and removes both
producer worktrees. The target contains both outputs, the final jobs are
`integrated`, and runtime doctor reports no fleet errors.

The orchestration uses Python argv arrays (`shell=False`) and delegates platform
worktree semantics to the already cross-platform RFC 008 companion. The
acceptance suite runs entirely in a temporary repository with no network or
provider dependency; actual provider/model availability remains a host concern.
