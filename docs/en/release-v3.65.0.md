# v3.65.0 release notes

## Version

**v3.65.0 (Minor).** Backwards-compatible operational evidence and safe-boundary
routing foundations. This release makes delivery and usage-watcher lifecycle
observable and recoverable, while keeping model-line routing fixture-only and
outside the passive core.

## Highlights

### Safe-boundary routing is deterministic, but still does not launch (#212)

RFC 077 Slice C adds a pure eight-rule state machine over operator-declared RFC
070 model pins, normalized model-line evidence, invocation effects, a durable
checkpoint, and a bounded switch count. Active usage holds are priority zero:
they halt before evidence inspection, create no route record, and can be cleared
only by the existing explicit `usage resume` gate.

Eligible decisions apply only to the next invocation with `replay=false`.
Partial output, tool effects, ambiguous completion, unsafe refusal, missing
checkpoint, stale/unknown/aggregate target evidence, and the default one-switch
cap halt with stable reasons. `compile_dry_run_plan` compiles requested and
selected pins without launching; decisions use the checked-in
`m8shift.route-decision.v1` schema and a create-exclusive canonical writer. A
blank-agent helper verifies the attempt-plan and closed-turn hashes before it
reconstructs the boundary.

Slices D and E remain outside this release: there is no listener integration,
live provider switch, credential lookup, notification, usage-hold mutation, or
relay write.

### Usage watchers have a managed lifecycle (#214)

`usage watch` now publishes one lease-bound
`m8shift.usage-watch.lifecycle.v1` registry per agent. A short exclusive
transaction prevents duplicate epochs; replacement and finalization are
conditioned on both PID and lease id. Each tick runs the existing adapter
snapshot in a bounded subprocess group, so an adapter, credential store, or
system call can fail one tick without freezing the resident watcher.

Health distinguishes process life, tick freshness, and successful reads. Dead
watchers restart, stale ticks and repeated unknown reads recycle only after a
fresh bounded probe, intentionally stopped watchers remain stopped, and
malformed state is quarantined into a safe stopped record. The new commands are:

```bash
python3 m8shift-runtime.py usage watch stop --agent AGENT
python3 m8shift-runtime.py usage watch reconcile [--agent AGENT]
```

Legacy live watchers without leases are terminated only after their command
identity is proven. A missing or mismatched process-start identity yields
`investigate`; no signal is sent to an unrelated process. Reconciliation never
clears a usage hold or resumes the relay automatically.

### Gateway work stays visible during a pause (#229)

Gateway automation can now call `m8shift-runtime.py gateway-event` to append one
bounded `m8shift.gateway.event.v1` row to
`.m8shift/runtime/gateway.jsonl`. The helper records an actor, action, outcome,
stable cause, bounded refs/ids, and optional SHA-256 evidence digests. It rejects
URLs, absolute or parent-traversing paths, credential userinfo, raw multiline
output, and non-digest evidence; it neither performs forge actions nor touches
the relay pen.

Core status projects only a recent valid event, and `m8shift-top` renders it as a
`GATEWAY` line even in `PAUSED`. RFC 065 §6 also fixes the operational ordering:
prove ancestry before branch deletion, replace wedged mergeability with a fresh
PR for the same SHA, resolve ambiguous 405 responses from reachability, and
declare stacked base and lineage explicitly.

### Vendor evidence remains fixture-only (#212)

RFC 077 Slice B supplies Anthropic, OpenAI, Google, and Mistral adapter
subclasses behind injected bounded retrievers. Their registry rows remain
`enabled=false` and `retrieval=fixture_only`. Success, throttle, malformed, and
auth-absent fixtures preserve each vendor's documented nullability and grouping
rules without SDKs, sockets, subprocesses, credential lookup, or invented
headroom.

### Audit and consultation evidence are explicit (#231, #225)

The RFC 001–077 implementation audit records a 77-row evidence-backed inventory
and a prioritized gap register. It distinguishes implemented requirements from
design-only documents and issue-level follow-ups, so a fixture, release-note
claim, or historical RFC cannot silently stand in for runtime capability.

The runtime's separate `consults.jsonl` path also gains bounded advisory provider
consultations: shell-free, read-only attested argv; capped process groups and
output; digest-only durable evidence; and an optional private non-overwriting
response sink. Consultation remains outside relay authority.

## Known work

- #222: scope scrub HISTORY reachability and name carrier refs for retained hits.
- RFC 068 P0: create, arbitrate, or explicitly abandon the missing rotation-token
  RFC artifact before dependent work cites it.
- #218: explain TIME legacy/unclassified and rolled-window presentation without
  changing the accounting semantics.
- RFC 077 Slice D (P1): opt-in listener integration at the safe next-invocation
  boundary, including hold precedence, reconstruction, exact argv, halt/notify,
  and byte-for-byte relay non-mutation tests.
- RFC 077 Slice E remains gated on fresh vendor-contract verification, explicit
  operator authorization, and a reversible disabled-default live pilot.

## Upgrade and verification

Update in place with the source-driven updater or self-update wrapper. Relay
state remains byte-identical. Verify that core, every installed companion, the
reference runner handshake, and wrapper report 3.65.0; run both unittest
discovery and pytest; then exercise an independent Python 3.8/Linux gate.

For dogfood, stop or reconcile pre-#214 watcher processes after updating and run
one real `usage watch reconcile` against the live watcher pair. Confirm exactly
one managed lease per agent, explicit stopped intent where requested, and no
relay mutation before publishing the annotated tag.
