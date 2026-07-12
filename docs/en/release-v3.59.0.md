# v3.59.0 release notes

## Version

**v3.59.0 (Révision).** This release adds backwards-compatible security,
conformance, listener-observability, and stale-state capabilities without a
relay-format or CLI compatibility break. It is more than a Correction and does
not require a Génération.

### Security baseline

- Advanced CodeQL, Bandit, ShellCheck, actionlint, Scorecard, and Dependabot.
- `SECURITY.md`, threat model, and behavioral mutation-gated conformance tests.
- RFC 052 anti-leak activation, `scrub-check --range`, exact pushed-range
  scanning, and dormant-gate doctor visibility.

### Runtime honesty

- #108 slice 2 listener capabilities, TTY waiter notice, and stale-AWAITING
  advisory.
- #107 explicit last-known stale usage fallback.

### Upgrade and verification

- No migration and no removed or renamed command/flag.
- Release artifacts and `checksums.sha256` are regenerated and lockstep version
  references are updated. Verify the release commit and tag before pushing
  either remote.
