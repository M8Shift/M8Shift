# v3.59.0 release proposal

Status: proposed — operator decision required.

## Version

**v3.59.0 (Révision).** Unreleased adds backwards-compatible security,
conformance, listener-observability, and stale-state capabilities without a
relay-format or CLI compatibility break. It is more than a Correction and does
not require a Génération.

## Release-notes skeleton

### Security baseline

- Advanced CodeQL, Bandit, ShellCheck, actionlint, Scorecard, and Dependabot.
- `SECURITY.md`, threat model, and behavioral mutation-gated conformance tests.
- RFC 052 anti-leak activation, `scrub-check --range`, exact pushed-range
  scanning, and dormant-gate doctor visibility.

### Runtime honesty

- #108 slice 2 listener capabilities, TTY waiter notice, and stale-AWAITING
  advisory (subject to design review).
- #107 explicit last-known stale usage fallback (subject to design review).

### Upgrade and verification

- No migration and no removed or renamed command/flag.
- Regenerate protocol artifacts and `checksums.sha256`; update lockstep version
  references; run focused security/runtime suites and the full quality gate;
  verify the release commit and tag before pushing either remote.

The operator approves, revises, or defers the cut after design review and
implementation status are known.
