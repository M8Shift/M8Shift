# RFC 068 — Zero-downtime forge token rotation

- **Status:** draft / design-only; every credential action remains operator-only
- **Date:** 2026-07-21
- **Issues:** #24 and #35; prerequisite for #77 and #165
- **Scope:** rotation of a forge access token used by local delivery helpers,
  pre-push flows, CI jobs, and managed listeners/runners
- **Builds on:** [RFC 052](052-rfc-project-compartmentalization-data-hygiene.md),
  [RFC 065](065-rfc-ticketed-committed-pushed-delivery.md), and
  [RFC 076](076-rfc-incident-first-deterministic-reentrant-discipline.md)
- **Operator runbook:** [Forge token rotation](../runbooks/token-rotation.md)

## 1. Incident packet

### Symptom and impact

One forge credential is pending rotation while several consumers may have
snapshotted it at different times. Revoking it first can strand a push, make a
pre-push credential helper fail, break a CI job, or leave a resident listener
using a value that no longer works. Leaving it active indefinitely preserves an
unnecessary exposure window and blocks work that would add another consumer.

### Root cause

The credential has a lifecycle at the forge, but its consumers have no common
cutover contract. A local `.env` file can change atomically while already running
processes retain their inherited environment and CI jobs retain the secret
snapshot from job start. File replacement is therefore not proof of propagation,
and forge revocation is not proof that every consumer adopted the replacement.

### Anti-recurrence guard

Every rotation uses two concurrently valid token generations and the re-entrant
operator runbook linked above. The replacement is minted, minimally scoped,
propagated, and independently verified before the old generation is revoked.
Completion requires post-revocation checks from every consumer class. A fresh
operator can reconstruct the phase from durable, secret-free evidence and safely
repeat any completed step.

This RFC records the lifecycle contract only. It does not mint, read, copy,
validate, revoke, or otherwise handle a live token.

## 2. Decision

Forge token rotation is an explicit state machine:

```text
inventoried -> replacement_valid -> overlap -> consumers_cut_over
            -> old_revoked -> post_revoke_verified
```

The invariant at every transition is:

```text
at least one known-valid, minimally scoped generation is available to every
authorized consumer, unless emergency revocation deliberately chooses outage
containment over continuity
```

The ordinary path keeps the old token valid throughout a bounded overlap window.
The operator first proves the replacement with a read-only API request and a Git
push dry-run, then updates consumers, drains or cancels in-flight work, and only
then revokes the old token. Emergency response may revoke first, but that is an
incident path with an expected outage, not a successful zero-downtime rotation.

## 3. Least-privilege token contract

The replacement must be narrower than or equal to the authority actually used:

1. prefer a repository- or project-scoped token over an account-wide token;
2. grant repository metadata read and content push only where delivery needs it;
3. grant issue and pull/merge-request write only to consumers that perform those
   RFC 065 actions;
4. omit organization administration, user administration, repository deletion,
   hook management, package publication, and unrelated repositories;
5. set the shortest operationally practical expiry and a descriptive generation
   label that contains no secret material; and
6. split CI, read-only automation, and human/gateway delivery credentials when
   the forge supports that separation.

Possessing a scope never authorizes an external action. Relay ownership, operator
authorization, independent review, and RFC 065 delivery gates remain separate.
If the forge cannot express the required narrow scopes, the operator records that
exception and treats the broader credential as higher risk; the software must not
silently widen it.

## 4. Credential transport and storage

### 4.1 Environment, never argv

The established Git credential-helper discipline is normative: the helper reads
the token from a named environment variable and writes the credential only to
Git's credential protocol pipe. The token value never appears in:

- a command argument, process title, remote URL, Git config, or helper definition;
- a relay turn, issue, PR, commit message, durable report, or test fixture;
- stdout/stderr, shell tracing, CI logs, listener plans, or runtime diagnostics.

The helper definition may name the environment variable, but it must not expand
the value while constructing argv. `set -x`, `GIT_TRACE`, HTTP tracing, and verbose
request logging stay disabled during credential operations. A helper may report
`present`/`absent` and a generation label; it must not echo, hash, prefix, suffix,
or otherwise fingerprint the token.

### 4.2 Local source and CI store

The local source is an ignored, mode-restricted `.env` entry using a colon as the
separator:

```text
FORGEJO_TOKEN:<token>
```

There is exactly one active line for that key. The replacement is written through
an atomic temporary-file-and-rename operation under a restrictive umask. The old
value is retained only in the operator's secret store until revocation; it is not
kept as a second `.env` line or a backup file beside the repository.

CI receives the replacement through the forge's encrypted secret setting, never a
committed workflow value. Existing jobs retain the generation captured when they
started; updating the setting affects only subsequent jobs.

### 4.3 Redaction is defense in depth

RFC 052 plus the #222/#240 scrub work redact recognized secret shapes before
durable storage. The generic long-blob pattern also catches a bare 40-hex value.
That is a backstop, not permission to handle a token in output: pattern matching
can miss new shapes, while a 40-hex Git object ID can also resemble a secret.
Prevention remains primary; raw leak scans remain mandatory before delivery.

## 5. Consumer inventory and propagation

The operator records one secret-free row per real consumer before cutover:

| Consumer class | How it reads the token | Adoption boundary | Required proof |
|---|---|---|---|
| Local `.env` | colon-delimited private file | atomic replacement | key present once; permissions restricted |
| Git credential helper / pre-push | named environment variable | next helper process | API read plus representative push dry-run |
| CI secret | forge encrypted secret setting | next job start | new job reaches authenticated no-mutation gate |
| Listener | inherited/allowlisted environment | explicit stop/start or managed restart | new process healthy; redacted plan shows variable name only |
| Runner child | listener/runner environment snapshot | next child invocation after parent adoption | bounded no-mutation preflight succeeds |

Changing `.env` does not mutate an already resident listener. Consumers are
restarted one at a time while the old token remains valid, and their effective
redacted configuration is rechecked after restart. A provider/listener plan that
contains the environment-variable name is not proof that its value is current.

## 6. Zero-downtime cutover

1. Inventory all consumers and establish a successful baseline without printing
   a credential.
2. Mint a replacement with the §3 scope and keep the old generation active.
3. Load the replacement into one isolated operator process and verify a read-only
   API call plus a representative `git push --dry-run`.
4. Atomically replace the local `.env` entry and update the encrypted CI secret.
5. Restart long-lived listeners/runners one at a time; after each restart, verify
   health and an authenticated no-mutation action before proceeding.
6. Stop dispatching new work briefly. Let pre-cutover pushes and CI jobs finish, or
   cancel them and reconcile their exact remote/job state.
7. Start a fresh CI job and fresh helper/runner invocations; verify every inventory
   row on the replacement generation.
8. Revoke the old token at the forge.
9. Repeat the API read, push dry-run, CI, and resident-consumer checks. Record only
   generation labels, times, status codes, job IDs, and exact Git SHAs where needed.

The overlap window is bounded by work, not a guessed timer: it opens when the
replacement is proven and closes when all pre-cutover work is settled and all
consumer rows are green. If the window exceeds the operator's chosen limit, stop
new work and investigate rather than revoking on schedule without evidence.

## 7. Pushes and CI jobs in flight

Never revoke a token while its use is merely presumed idle.

- **Push in flight:** allow it to finish or cancel it. If completion is ambiguous,
  compare the exact local SHA to the authoritative remote ref before retrying.
  After cutover, retry from the same commit with the replacement helper; never
  force-push merely because authentication changed.
- **CI job in flight:** an already started job cannot adopt the replacement secret.
  Let it finish while the old token is valid or cancel it, preserve its job/commit
  identity, then run a new job after the secret update. A canceled or auth-failed
  job is not a passing cutover check.
- **Listener invocation in flight:** do not replace the parent underneath a child.
  Reach a normal safe boundary, checkpoint, stop the producer, restart with the
  replacement environment, and launch the next invocation. Rotation never
  releases or force-recovers the relay pen.

## 8. Failure handling and rollback

Before revocation, any failed consumer check returns the rotation to `overlap`:
keep the old token active, stop new work on the failing lane, correct scope or
propagation, and repeat the check. If necessary, atomically restore the old value
from the operator's secret store; do not recover it from logs or process output.

After revocation, the old generation is never re-enabled. A failure becomes a new
incident: stop affected mutations, mint another replacement if the current token
cannot be corrected safely, propagate it through the same state machine, and
reconcile any ambiguous remote effects before retrying.

Compromise response is the explicit exception to overlap. Revoke the suspected
token immediately, accept the bounded outage, preserve redacted evidence, and run
the incident path. Do not call that path zero-downtime.

## 9. Verification and completion evidence

Rotation is complete only when all of these are true:

1. the replacement token identity, expiry, and scopes are confirmed at the forge;
2. API read and push dry-run succeed without a secret in argv or output;
3. a fresh CI job and every restarted resident consumer succeed;
4. no pre-cutover push, job, or invocation remains ambiguous or active;
5. the old token is revoked and a controlled old-generation check receives the
   forge's unauthenticated/forbidden response without printing the value;
6. all replacement-generation checks still pass after revocation; and
7. raw diff/history/leak gates find no credential in durable artifacts.

Evidence records only consumer name, generation label, UTC time, bounded result,
job/ticket IDs, and Git SHAs. It never records either token value.

## 10. What this unblocks

Completing the operator runbook resolves the credential-lifecycle prerequisite in
#24/#35. It allows #77/#165 to reconsider a replacement token for direct forge
delivery and managed runner/listener use. It does **not** enable that path:

- #77 must still resolve and accept its network-egress, profile, allowlist, and
  external-action policy;
- #165 must still follow RFC 065 ticket, push, review, and merge evidence;
- the replacement token is not added to a new consumer until that consumer is
  separately authorized and included in the rotation inventory.

## 11. Non-goals

- No live token creation, inspection, propagation, validation, or revocation.
- No secret manager, forge API, CI, provider, listener, or helper implementation.
- No network-access or direct-delivery authorization for #77/#165.
- No claim that redaction proves absence or that `.env` replacement proves runtime
  adoption.
- No Python-version impact; this is an operator and documentation contract.

## 12. Acceptance criteria

1. The runbook is executable by a fresh operator with placeholders only and is
   safe to resume after interruption.
2. The replacement is valid before the old token is revoked, with a bounded
   evidence-driven overlap window.
3. Every consumer has an explicit adoption boundary and post-cutover proof.
4. Credential helpers consume environment values, never token-bearing argv.
5. In-flight pushes, CI jobs, and listener invocations reach an observed safe
   boundary before revocation.
6. Rollback before revocation and incident recovery after revocation are distinct.
7. Durable artifacts and logs remain credential-free, with raw leak verification.
8. #77/#165 are unblocked only as separately authorized follow-up work.
