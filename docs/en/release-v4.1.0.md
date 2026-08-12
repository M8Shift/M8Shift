# v4.1.0 release notes

## Version

**v4.1.0 (Revision).** This is a backwards-compatible feature release. It adds
managed interactive authority, scoped gateway transport, stronger publication
proofs, and more honest runtime/usage evidence without changing the relay file
format, removing a command, or raising the Python 3.12 floor introduced by
v4.0.0. Existing v4 relays update without a Generation override.

## Highlights

### Interactive work keeps both liveness and write authority (#280/#281)

`lease-keeper <agent> -- COMMAND ...` runs one shell-free child while refreshing
the real pen lease and emitting a bounded `wrapper` heartbeat. Those operations
are deliberately separate: the heartbeat protects a live holder from stale
takeover, while `claim --refresh` preserves actual write authority. If either
guarantee is lost, the wrapper stops the child.

`guard-exec <agent> -- COMMAND ...` places the point-in-time pen check directly
next to one external mutation. The generated pre-push hook applies the same
configured-agent fail-closed contract as pre-commit; an unconfigured human
checkout remains usable, but is visibly reported as unverified rather than
clean.

### A gateway receives one capability, not ambient authority (#281)

The live holder may create an immutable mandate for a distinct gateway actor,
bound to one action, target, project, working directory, relay turn, canonical
argv digest, executable path and executable bytes. `gateway-exec` claims that
mandate atomically and only once, rejects replay or any binding mismatch, then
launches a private re-hashed snapshot copied from the already-open executable
descriptor. This closes option smuggling and original-path replacement without
persisting argv, comment bodies, credentials, output, or secrets.

The allowlist is intentionally small: exact push, issue comment, PR creation and
PR comment transport. Merge, close, tag, deletion, mirror, force-push and other
integration/destructive operations remain outside mandate authority and still
need explicit human authorization.

### Publication is proven at the destination and fails closed (#263/#264/#265/#266/#300/#306)

The pre-push boundary now combines six closures:

- publication policy binds to the fingerprint of the canonical destination,
  not a convenient remote name or stale tracking ref;
- a short-lived single-use published-base receipt can attest a clean new branch
  or tag after two exact live observations of the same destination, while the
  pushed tag object and every unpublished commit remain scanned;
- merge-resolution content is compared against every parent, so a finding
  introduced and later hidden by merges remains visible;
- missing or incomplete configured stages are distinct from clean stages and
  block whenever policy requires a complete publication verdict;
- denylist comparison has bounded Unicode/separator normalization, stable
  overlapping labels, guarded word rules and production parser/object limits;
- `allow:` exceptions obey the same minimum length as denied terms, and never
  suppress tree or path-name findings.

The network-capable attestation helper is isolated from the local-only scanner.
Receipts carry endpoint fingerprints, never URLs or credentials, and a moved,
diverged, deleted, ambiguous or unreachable endpoint invalidates the proof.

### Runtime success and quota health say what was actually observed (#312/#313/#316/#317)

A headless run is `advanced` only when the new closed turn carries its exact
`M8SHIFT_RUN_ID`; a parallel manual turn by the same agent is an external
transition, not success for the resident run. The core stamps this binding at
append time, and generated commit hooks add validated agent attribution.

Usage adapters distinguish a measured quota response, a successful provider
response with no usable quota window, and an unavailable/degraded read. The
tokscale example consumes the real redacted v4.13.0 quota shape, converts native
percentages to ratio windows, preserves model-specific weekly quota, discards
identity/plan fields, and retains the legacy spend-total path without ever
submitting telemetry.

`doctor` also warns when an active worktree's pre-push hook differs from the
locally cached published-main copy. This is a local, non-fetching drift signal,
not a new gate.

### Review and upgrade authority are explicit (#279/#301/#302/#307)

Independent approval and publication consent are separate. Only the human
operator or maintainer authorizes a merge, tied to the exact PR and head SHA;
peer approval is review evidence. The adopted-kit procedure now names the
coordinating agent and the safe `pause -> update -> verify -> resume` window, so
the pen and the updater are never made to contradict each other.

RFC 067's governed headless policy is frozen as a bounded, locally attested
design. It documents capability envelopes without adding ambient network/filesystem
authority or moving routing authority out of the passive core.

The generated `protocol.m8shift.ai` Markdown, HTML and Worker are synchronized
with the canonical Agent Exchange Protocol in this release. The agent-first
surface now carries the publication-audit boundary and the new direct-holder
authority mappings instead of serving the stale pre-v4.1 copy.

## Known boundaries

- `guard-exec` narrows the cooperative check/use window; it is not a hostile-host
  sandbox. Interpreter replacement, inherited environment poisoning and Git
  configuration redirection remain outside the local cooperative threat model.
- Gateway mandates authorize transport only. They cannot merge, tag, delete or
  turn a gateway identity into an unrestricted writer.
- RFC 067 policy is design documentation in this release, not an automatic
  capability broker. The minor-release memory-parasite audit converted the
  remaining private workaround into implementation follow-up #325 rather than
  leaving fresh adopters to rediscover it.
- Worktree hook drift is advisory and uses only locally cached published-main
  evidence; it never fetches on the operator's behalf.

## Upgrade and verification

Use the **new** v4.1.0 source while the adopted relay is paused:

```sh
./m8shift.py pause <you> --reason "kit upgrade to v4.1.0"
python3 <v4.1.0-source>/m8shift.py update \
  --target <relay> --source <v4.1.0-source> \
  --companions context,e2e,headroom,i18n,runtime,worktree,top
./m8shift.py doctor
shasum -a 256 -c checksums.sha256
./m8shift.py resume <you> --reason "kit at v4.1.0, doctor clean"
```

`update` preserves `M8SHIFT.md`, its turn journal and the active session. No
`--allow-generation-change` flag is needed when updating from v4.0.0.
