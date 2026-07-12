---
name: leak-warden
description: Operate and interpret repository anti-leak controls, including denylist handling, activation checks, redacted scans, and tip-versus-history remediation. Use when checking whether sensitive identifiers can enter commits or pushed history.
license: Apache-2.0
metadata:
  m8shift-lane: advisory-read-only
  m8shift-report: required
---

# Leak warden

Locate the repository's anti-leak documentation before scanning. Keep the
denylist at the documented local path, one term per line, with restrictive
permissions (normally `0600`). Mirror it into CI only through the documented
secret mechanism; never commit or print its terms.

## Activate before trusting

Confirm the configured hooks path, the enforcement variable or switch, and the
presence of the CI secret. A control can be shipped in the repository while
remaining undeployed in a checkout or forge, so record each activation check.

## Choose the scan

- Scan the tip for material about to be committed.
- Scan the pushed range before publication or handoff.
- Scan full history for an audit or when earlier exposure is suspected.

Use the repository's raw scan tools. Normal output should expose only redacted or
hashed labels. A forensic `--verbose` mode is local-only because it can reveal
denylist terms; never paste that output into CI, issues, or relay records.

## Remediate

If a match exists only on the tip, remove or abstract it, add an appropriate
denylist term locally, then rerun the relevant scan. If it exists in history,
stop publication and follow the repository's history-rewrite or `filter-repo`
runbook, including credential rotation where applicable. Do not improvise a
shared-history rewrite.
