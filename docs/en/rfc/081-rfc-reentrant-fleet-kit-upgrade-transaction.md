# RFC 081 — Re-entrant fleet kit-upgrade transaction

- **Status:** implemented by #331; target v4.1.1
- **Date:** 2026-08-14
- **Issue:** #330
- **Scope:** ordered kit releases across explicitly declared, independent relay
  roots
- **Builds on:** [RFC 047](047-rfc-headless-liveness-runner-listener.md),
  [RFC 048](048-rfc-adoption-discipline-pack-update-health.md),
  [RFC 072](072-rfc-exact-identity-fleet-bootstrap.md), and
  [RFC 076](076-rfc-incident-first-deterministic-reentrant-discipline.md)
- **Implementation:** #331; doctor-drift classification follows in #332
- **Protocol impact:** no — this runtime-companion transaction does not change
  LOCK/turn schemas or routing authority; optional relay resume delegates to the
  existing core command.

## 1. Decision

M8Shift will expose a separate `fleet-upgrade` runtime workflow for kit releases
across independent relay roots. It does not change the meaning of RFC 072
`fleet`, which manages identities and listeners inside one relay.

The cohort policy is:

> **ordered fail-stop, retaining every earlier member whose update and
> postconditions were fully verified.**

The first failed or ambiguous member stops the operation. Later members remain
byte-untouched. Earlier verified members are not rolled back merely to make the
cohort look uniform. There is no automatic cohort rollback.

This deliberately chooses bounded partial progression over cohort atomicity.
Independent relays do not share a transaction manager, and restoring older kit
bytes across already verified roots would create more failure surfaces without
restoring any shared invariant. A temporarily mixed-version cohort is visible
degraded state, never a hidden success.

## 2. Authority and maintenance window

### 2.1 Named coordinator

Every operation names one `coordinator` identity and one opaque `operation_id`.
The human operator authorizes that exact coordinator, source identity, ordered
target set, generation policy, and operation id. The coordinator is recorded in
every checkpoint and report; a resumed command with a different coordinator is
refused.

The coordinator MUST be a rostered agent in every selected relay. It never
inherits a target pen from the fleet record and cannot force, recover, claim, or
pause through a live peer. The runtime sidecar remains non-authoritative.

### 2.2 #301 pause window

For an open target, the only mutating maintenance state is `PAUSED`. `IDLE` and
`AWAITING_*` are accepted by the low-level update primitive but do not satisfy
the contribution pen rule; `WORKING_*` has a pen but is unsafe for engine
replacement. Issue #301 resolved that contradiction with:

```text
coordinator prepares -> target enters PAUSED -> kit mutation -> verify -> resume
```

Before fleet mutation, the coordinator MUST either:

- have placed the target in `PAUSED` with a bounded reason carrying the
  `operation_id`; or
- observe `DONE`, which remains terminal and is never resumed.

An existing unrelated pause is not silently adopted. It requires explicit
operator confirmation recorded in the operation before mutation. `WORKING_*`,
`IDLE`, `AWAITING_*`, an unbound pause, an unreadable LOCK, or a coordinator not
in the target roster fails preflight without changing that target.

After successful listener restoration, a target paused by this operation is
resumed by the same coordinator only when the spec says `resume_relay: true`.
Otherwise it remains visibly `PAUSED` for explicit local resumption. A `DONE`
target remains byte-identical and terminal.

This is the existing #301 maintenance exception, not a new pen state or a
standing out-of-band writer.

## 3. Explicit inventory boundary

The coordinator accepts an ordered `m8shift.fleet-upgrade.spec.v1` document. It
does not recursively discover projects.

```json
{
  "schema": "m8shift.fleet-upgrade.spec.v1",
  "operation_id": "opaque-operator-id",
  "coordinator": "codex",
  "policy": "ordered_fail_stop_retain_verified",
  "source": {
    "version": "4.1.1",
    "generation": 4,
    "manifest_sha256": "<64 lowercase hex>"
  },
  "allow_generation_changes": [],
  "instances": [
    {
      "id": "relay-a",
      "root": "/configured/local/path",
      "resume_relay": true
    }
  ]
}
```

Instance ids are unique bounded tokens. Roots must be explicit, canonical,
unique, initialized directories and non-symlinks. The list order is the mutation
order and is covered by the inventory digest.

The following are excluded with an explicit reason and never guessed into the
cohort:

- archive, backup, trash, temporary, or hidden discovery candidates;
- symlinked, duplicate, nested, missing, or non-directory roots;
- directories without a valid relay LOCK and kit manifest;
- workspaces whose relay root cannot be proven consistently under #327;
- source directories, Git worktrees, and arbitrary project directories that are
  not adopted kits.

Exclusion is a preflight result. A root explicitly named by the operator but
invalid is not silently dropped: with the fail-stop policy it prevents mutation
of the entire cohort until the spec is corrected.

## 4. Source and generation identity

The source is one verified release tree. Preflight records:

- source version and Generation;
- canonical component manifest and its SHA-256;
- each selected component path, size, mode, and digest;
- source Git/tag identity when available, as evidence only;
- the exact companion set, including `top` when declared;
- any bounded runner-adoption action governed by #328.

The manifest, version and component bytes are rechecked before every target so a
source tree cannot change mid-cohort unnoticed. A mismatch halts before the next
mutation.

A Generation change is denied by default. `allow_generation_changes` contains
exact `{instance_id, from, to, approval_ref}` records authorized before the
operation. A global boolean, ambient CLI flag, or approval inferred from another
instance is insufficient.

## 5. Immutable preflight packet

Before any target mutation, the operation records a bounded packet for every
instance:

- canonical root identity in the private state; instance id plus root digest in
  portable reports;
- relay/core version, kit manifest identity, installed component subset, and
  runner identity;
- session id, state, turn, roster, and LOCK digest;
- whole `M8SHIFT.md` byte digest, plus digests for existing journals and ledgers;
- raw read-only `doctor --json` baseline and its digest;
- every listener lane's lifecycle, PID/generation evidence, coverage,
  invocation/notification capability, root consistency, plan path/digest, and
  notify-only flag;
- update dry-run result against the exact source.

The packet may read bounded authority fields and hash state files, because those
are required invariants. It never persists their bodies, turns, prompts,
provider output, environment values, account identity, or credentials.

All members must finish preflight before the first mutation. A preflight failure
means no member is changed.

## 6. Listener stop and restore set

Lifecycle and capability are independent:

- `notify-only` may be demonstrably `ALIVE`; if so it belongs to the stop/restore
  set even though `can_invoke_agent=false`;
- a normal invoker belongs to the set only when it is `ALIVE`, resident,
  generation-consistent, root-consistent, and has a #329 replayable plan;
- an already dead or non-resident lane is recorded but neither stopped nor
  restored;
- a resident `HALTED`, `UNKNOWN`, generation-mismatched, ambiguous, or
  plan-unreplayable lane fails preflight. The coordinator does not stop it under
  a claim that it was demonstrably ALIVE.

The immutable `restore_set` contains each eligible lane's agent, mode,
plan digest, and pre-stop lifecycle evidence. The coordinator stops exactly
that set, verifies every process is gone, and restores exactly that set with
`listener start --from-plan`. It never reconstructs argv from `ps`, never uses
#328 as a live detach mechanism, and never starts a lane that was dead before
maintenance.

### 6.1 Approved runner-plan migration

Implementation exposed one necessary transition that the original design did
not state: #329 correctly pins the runner executable digest in the restart
plan, while a complete kit upgrade may replace that runner. Replaying the old
plan unchanged would therefore refuse the approved new runner.

The transaction does not weaken `--from-plan`. After the target kit exactly
matches the approved source, it may migrate only the plan's versioned runner
identity to the digest already present in that source manifest. Before any plan
replacement it checkpoints the complete old and candidate plans, their digests,
the operation id, and the source-manifest digest in the private record. Each
plan replacement is fsync plus atomic replace. Re-entry accepts only the exact
old or exact migrated digest; any third value requires reconciliation. A kit
rollback restores the exact old plan before listener restoration.

The migrated plan carries `m8shift.listener.plan-upgrade.v1` lineage. Profile,
backend, cadence, mode, root provenance, workspace and every other launch field
remain byte-derived from the old validated plan. `listener start --from-plan`
still independently re-hashes the current runner, rebuilds the candidate and
refuses any mismatch. This is local runtime evidence, not a protocol message or
new authority.

Final listener success requires, per restored lane:

- resident PID with matching generation evidence;
- lifecycle `ALIVE`;
- the same invoker/notifier coverage class as before;
- matching invocation/notification capability;
- relay/workspace roots consistent with the preflight plan.

Missing any postcondition yields `updated_but_listener_down`; the cohort halts
and is never reported green.

## 7. State machines and checkpoints

### 7.1 Operation state

```text
planned -> preflighted -> running -> complete
                            |  |
                            |  +-> halted
                            +----> needs_reconciliation
```

`complete` requires every member terminal as `updated` or `already_current` and
every requested relay resumption verified. `halted` is a clean fail-stop with a
known next action. `needs_reconciliation` means local evidence cannot safely
choose continue or rollback.

### 7.2 Instance state

```text
inventoried -> preflighted -> stopping_listeners -> listeners_stopped
  -> updating -> verifying -> migrating_listener_plans
  -> restoring_listeners -> resuming_relay -> terminal
```

Each transition is validated from the previous durable state and committed by
fsync plus atomic replace before the next side effect. The coordinator records
intent before a side effect and result after it. No phase is inferred from
process memory or conversational history.

The private record uses `m8shift.fleet-upgrade.operation.v1` under a dedicated
runtime directory. It binds operation id, coordinator, source digest, inventory
digest, policy, current index, per-instance phase, restore set, backup manifest,
transition timestamps, and bounded evidence references. One lock serializes an
operation; a different spec cannot reuse its id.

## 8. Apply, verify, and rollback

One instance is mutated at a time through the existing transactional `update`
primitive. The coordinator adds ordering and evidence; it does not reimplement
file replacement.

Verification requires:

- installed kit subset exactly matches the approved source manifest;
- version and Generation equal the approved target;
- session, turn, roster, LOCK and all journal/ledger bytes are unchanged from
  preflight except the separately authorized PAUSED/resume transition;
- post-update doctor completes and its raw result is retained for #332 drift
  classification;
- listener and relay-resume postconditions in §§6–7 pass.

Rollback is per-instance only. Before update, the coordinator creates a bounded
backup manifest for kit files that may be replaced. It never backs up or restores
`M8SHIFT.md`, session history, archives, tasks, requests, runtime ledgers,
listener state, usage data, project files, or provider credentials.

If update or kit verification fails, the coordinator may restore only the
current instance's backed-up kit files, then verifies the original kit identity
and unchanged relay data. A proven restore is `rolled_back`. An incomplete or
ambiguous restore is `failed` plus operation `needs_reconciliation`.

After kit verification succeeds, listener restoration failure does not trigger
an automatic kit downgrade: it yields `updated_but_listener_down` and an exact
#329 recovery command. Earlier verified instances remain updated; later ones are
not touched.

## 9. Re-entry after interruption

The same operation may be resumed only with matching coordinator, source,
inventory, policy, and spec digests.

- terminal instances are never mutated again;
- `already_current` is a byte-mutation-free second-run result;
- before-mutation phases rerun read-only preflight and continue;
- `stopping_listeners` rechecks the immutable restore set and stops only members
  still proven to be those exact processes;
- an interrupted update compares target bytes with the approved source and
  backup manifests: exact target continues at verification, exact original
  continues at restoration/rollback reporting, and mixed or unknown bytes enter
  `needs_reconciliation` before any new update;
- plan migration accepts only the recorded old or source-approved migrated
  digest; restoration then replays only that migrated digest, while an already
  restored matching ALIVE lane is adopted as success;
- the current relay/journal digests are rechecked at every resume boundary.

No second execution reconstructs commands from process listings, repeats a
completed update, starts a previously dead listener, or skips an unresolved
instance.

## 10. Terminal outcome vocabulary

Every declared instance ends in exactly one public outcome:

| Outcome | Meaning |
|---|---|
| `excluded` | explicit preflight exclusion; no mutation |
| `not_started` | earlier member halted the ordered cohort; no mutation |
| `already_current` | target kit and postconditions already matched; no mutation |
| `updated` | kit, relay invariants, listeners, and requested resume verified |
| `rolled_back` | current member's kit restored to its exact preflight identity |
| `failed` | target or rollback cannot be proven; manual reconciliation required |
| `updated_but_listener_down` | kit verified, but a previously ALIVE lane was not restored |

`updated` and `already_current` are the only green outcomes. A report with any
other outcome cannot say the cohort succeeded.

## 11. Reports and privacy

The coordinator produces:

- the private re-entry record with canonical local paths, mode `0600` where the
  platform supports it;
- one consolidated machine-readable `m8shift.fleet-upgrade.report.v1` JSON;
- one Markdown rendering derived only from that JSON.

Portable reports contain instance ids and path digests, not raw absolute roots.
They include source/operation/inventory digests, coordinator, policy, per-instance
phase/outcome, before/after kit identities, listener classes and postconditions,
doctor artifact digests, bounded reason ids, timestamps, and one terminal TOP
observation. `top_on_disk` is a bounded stable read of the canonical regular
non-symlink script; `top_process_loaded` is `absent`, `observed`, `partial`, or
`unobservable` and retains every version carried by a matching root marker.
Legacy processes never receive an invented version. A loaded/disk mismatch is a
restart warning but does not change the outcome-derived fleet `green` verdict.
Reports exclude PIDs, raw process argv, raw
relay text, turns, prompts, environment values, provider output, account data,
credentials, and backup contents.

Evidence retention is explicit and bounded by operation. Deleting completed
runtime evidence loses audit detail but never changes relay authority or kit
identity.

## 12. Acceptance matrix for #331

| Case | Required result |
|---|---|
| all members valid | ordered `updated`; complete report |
| exact target already installed | `already_current`; byte-mutation-free |
| invalid/archive/non-kit root | preflight refusal before cohort mutation |
| unapproved Generation change | refusal before listener stop |
| target `WORKING_*` or unbound pause | refusal; no force/pause takeover |
| ALIVE invoker and ALIVE notify-only | both stopped and restored from exact plans |
| approved runner changes | plan runner identity migrates with old/new digest lineage; strict replay remains enforced |
| dead lane | neither stopped nor started |
| resident HALTED/ambiguous lane | preflight refusal, not relabelled ALIVE |
| update/verify failure | current member rollback only; later members untouched |
| listener restore failure | `updated_but_listener_down`; fail-stop |
| interruption at every phase | deterministic resume or `needs_reconciliation` |
| second run after success | all `already_current`; no mutations |
| journal/ledger byte change | fail-stop; never restore older data |
| report inspection | no raw paths, relay text, env values, provider output, or secrets |
| old TOP still attached | report loaded and on-disk versions separately; restart warning; verified upgrade remains green |
| legacy TOP without markers | `unobservable`, never an inferred loaded version |
| multiple marked TOP processes | retain every distinct loaded version; never flatten to one |
| process argv unavailable | explicit `unobservable`; no signal or process mutation |

**Protocol impact: no.** This continuation extends local crash-consistent and
portable report evidence only; it does not change relay semantics or authority.

The implementation must use hermetic temporary roots, injected process/backend
facts, and interruption fixtures. Provider/network access is neither necessary
nor permitted in acceptance tests.

## 13. Relationship to #332 and #333

#331 captures raw, immutable pre/post doctor artifacts and their digests. #332
adds the reusable `doctor-baseline capture` / `doctor-baseline compare` surface
for future upgrade orchestration. Capture creates one
`m8shift.doctor-baseline.v1` record bound to the canonical relay-root digest,
session, turn, kit/core versions, strict UTC capture/expiry timestamps, raw
doctor-payload digest, and a normalized finding multiset. The default and
maximum lifetime are 24 hours; the minimum is 60 seconds.

The multiset identity is exactly `(check, severity, normalized relative path)`.
Reporter `message` and `fix_hint` wording is validated at capture but is neither
stored nor part of identity. Comparison reports pre-existing, resolved, and
introduced counts in readable form or as
`m8shift.doctor-baseline.comparison.v1` JSON. Introduced `info` remains visible
but green. Any introduced `warning` or `error` is non-green unless an explicit
`m8shift.doctor-baseline.exceptions.v1` record binds the exact baseline digest,
relay root, accepting actor, decision reference, lifetime, finding key, and
maximum accepted count. Unknown/non-blocking keys, expired records, path
traversal, symlinked or unstable inputs, cross-root/session/future-turn
baselines, malformed schemas, and incompatible versions fail closed with exit
2; uncovered blocking drift exits 1.

The #331 transaction can reuse the surface by capturing before mutation and
comparing its retained post-update doctor artifact with `--current-json`. The
classifier is an enhancement of #331 evidence, not permission to omit the raw
artifacts or to relabel an already-completed operation retroactively.

#333 adds the independent core command
`m8shift.py verify-kit --source DIR [--json]`. It first validates the complete
source `checksums.sha256` and every listed regular non-symlink file, then reads
the strict local `m8shift.kit.v1` manifest and compares only its declared core,
companion, and runner subset. Each component exposes a stable id, version/hash
evidence, and one stable result including `success`, `missing`, `symlink`,
`drift`, `version_mismatch`, `manifest_sha_mismatch`, or `source_mismatch`.
Unsupported or incomplete kit fields and invalid, unstable, traversing,
oversized, or checksum-bad source evidence fail closed before a component
verdict. Human and `m8shift.verify-kit.report.v1` JSON output use exit 0 for a
matching subset, 1 for component drift, and 2 when no valid verdict can be
formed. Reports contain root digests rather than raw paths.

The #331 implementation retains its existing exact plan comparison for
backward compatibility; future orchestration may consume the pure verification
helper or the stable report contract without changing relay authority.

## 14. Protocol impact

**Protocol impact: yes — command/reference surface only.**

#333 adds the read-only core command `m8shift.py verify-kit`, so the canonical
protocol reference and every shipped language pack list that command. The
operational protocol is otherwise unchanged: RFC 081 uses existing `PAUSED`,
`DONE`, `pause`, `resume`, listener lifecycle, and transactional update
semantics, and adds no relay state, transition, claimability rule, turn field,
authority record, pen grant, or autonomous pause/recovery path. Runtime and
verification reports remain derived local evidence.
