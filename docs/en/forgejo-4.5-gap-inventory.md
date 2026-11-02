# Forgejo-to-GitHub 4.5 gap inventory (2026-10-28)

Status: **audit only**, no source transplant or release approval.

## Revisions compared

- Private Forgejo `TheLazyGeekGuy/M8Shift` `main`: `451b107ccd04dab4c90185aa5292b10d97d5f33d`.
- Public GitHub `M8Shift/M8Shift` `release/4.5.0-integration`: `4d5312bb3106d777293e7d8d2ce57a917f99635e`.
- Both trees have 384 entries. Comparison uses Git blob SHA and exact repository paths, not version strings.
- 248 shared blobs have identical SHAs, 65 shared blobs differ, 16 are Forge-only, and 16 are GitHub-only.
- The two `main` lines both descend from 4.2.0 but are not interchangeable. The public release candidate already contains Python 3.15 single-version CI and the advisory routing bridge.

## Forge-only source and test candidates

| Files | Recommendation | Reason |
| --- | --- | --- |
| `scripts/check-test-loading.py`, `tests/test_test_loading.py` | **High: inspect and port with checks** | Exact-tip unittest discovery attestation; potential CI gate #406 |
| `tests/test_usage_liveness.py`, `tests/test_usage_advice.py` | **High: inspect alongside runtime implementation** | Quota watcher liveness #404 and pre-limit advice #412; tests alone are insufficient |
| `tests/test_working_listener_status.py` | **High: inspect alongside runtime** | Live listener status #532 |
| `tests/test_kit_drift.py` | **High: inspect alongside install/doctor** | Same-version different-byte drift #533 |
| `scripts/check-mirror-freshness.py`, `tests/test_mirror_freshness.py`, `docs/en/mirror-freshness.md` | **Medium: adapt** | Private Forge main vs public mirror freshness; publication assumptions need review |
| `scripts/onboard-probe.py`, `docs/en/onboarding.md` | **Medium: adapt** | Onboarding probes may need Python 3.15 and installer behavior updates |
| `docs/en/rfc/082-rfc-first-class-relay-observer.md`, `083-rfc-surfaces-measure-announced-activity.md`, `084-rfc-mutualized-installation-tree.md`, `085-rfc-remote-runners-instance-identity.md`, `086-rfc-exact-tip-test-loading.md` | **Design review** | Preserve RFC status and provenance; do not treat a proposal as implemented |

## GitHub-only release candidate assets (must preserve)

`.python-version`, `m8shift-decision.py`, `m8shift-routing-bridge.py`,
`.github/workflows/decision-engine.yml`, `docs/en/modules/decision-engine.md`,
`docs/en/python-support.md`, `docs/en/release-v4.5.0.md`,
`tests/_fleet_fixture_cleanup.py`, and the new decision/runner/session/lease regression tests.

## Changed shared files (65)

Includes the core and runtime, install scripts, GitHub CI and lint workflows,
`hooks/pre-push`, `scripts/scrub-check.py`, documentation, checksum manifests,
`tests/test_m8shift.py`, and localization/protocol packs. **Do not overwrite.**
Review behavior and tests per subsystem; preserve the v4.5 Python 3.15 CI,
the one-pen/LOCK invariant, the public scrub gate, and the opt-in advisor policy.

## Private Forge branches

37 branches, including `main`. Earlier branch comparison found 33 of the 36
non-main branches with no outstanding commits relative to private Forge `main`.
`docs/rfc-065-governed-forge-delivery` and
`docs/rfc-068-codex-forge-access` each have one outstanding documentation commit.
`relay/main-2026-07-13` is a diverged historical branch (bounded comparison
reported 434 commits and truncation). **Never merge the historical branch wholesale.**

## Safe port sequence

1. Compare the 65 differing files by behavior and isolate the exact commits implementing each capability.
2. Port test-loading and quota/liveness slices in separate PRs onto the 4.5 candidate, including source, tests, docs, and integrity manifest changes.
3. Check all content against the project's disclosure/scrub policy **before** publishing anything from private Forge.
4. Re-run the single supported Python 3.15 CI, lint, CodeQL, and checksums after each accepted slice.
5. Update the Forge tickets with exact source and target commit SHAs, tests and reviewer verdict.
6. Keep `main` and any release tag unchanged until independent review and per-PR operator authorization.

This document is a differential inventory, **not** a claim that the private Forge implementation is ported or safe to publish.
