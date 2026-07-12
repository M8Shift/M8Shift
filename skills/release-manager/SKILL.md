---
name: release-manager
description: Verify a software release from preparation through publication. Use when an operator asks for a release readiness check or a release to be cut, tagged, pushed, documented, and verified without assuming any forge, remote, or version policy.
license: Apache-2.0
metadata:
  m8shift-lane: advisory-read-only
  m8shift-report: required
---

# Release manager

Treat a release as a set of independently verified checks, not a chronology that
becomes correct merely because every command ran.

## Parameters

Before acting, identify the forge, canonical remote, version-policy document
(commonly `CONTRIBUTING.md`), checksum/manifest path, release branch, and site or
documentation publication process. Ask rather than guessing.

## Checks

- The working tree is clean and the required pipeline is green.
- Every lockstep version reference follows the repository's version policy.
  After the bump, only intentionally historical changelog references remain.
- The project's doctor or equivalent module-reference check reports no stale
  versions or missing companion references.
- The dated changelog section is cut and a fresh, empty `Unreleased` section
  remains.
- Every touched file listed by the checksum or artifact manifest is regenerated,
  and the manifest is verified from raw output.
- Focused release, install, doctor, and packaging suites pass.
- The merge pipeline is green before any tag is created.
- The release tag points to the merged canonical-branch tip; compare object IDs
  instead of assuming the local checkout is current.
- The branch and tag are pushed to the canonical remote first. Mirrors and
  secondary forges follow only after that succeeds.
- Site and documentation publication steps are completed.
- Published artifacts, release notes, documentation, and tag targets are checked
  from their public surfaces after publication.

Record each check and its evidence. A created tag, release page, or draft is not
evidence that the release is complete.
