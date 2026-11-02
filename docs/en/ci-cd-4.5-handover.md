# M8Shift 4.5 CI/CD handover

This document records the release-candidate validation chain, not a production deployment.

## Branches and version

- Public GitHub: `M8Shift/M8Shift`
- Release candidate: `release/4.5.0-integration`
- Production/default: `main` (v4.2.0 until approved)
- Maintained interpreter: Python 3.15.x via `.python-version`
- Release PR: https://github.com/M8Shift/M8Shift/pull/18

## Continuous integration

The following GitHub Actions workflows are configured to run for pull requests
targeting `main` **or** `release/4.5.0-integration`, and on pushes to those branches
where their path filters match:

- `ci.yml`: byte compilation, checksum manifest, hygiene and optional confidential scrub, full pytest suite.
- `lint.yml`: shell/action/Python static analysis.
- `codeql.yml`: Python security analysis.

Other targeted workflows cover decision routing, test discovery, quota checkpoint
advice and watcher liveness. Targeted success does not replace the full suite.

**Confidential scrub caveat:** the denylist secret `M8SHIFT_DENYLIST` is
operator-managed and skipped if unavailable. A green run with a skipped scrub
is not evidence of confidential-data clearance. Verify this secret and the
scrub result before publishing private Forgejo changes.

## CD / release gating

There is **no automatic deployment or publication** from this branch. Keep
`main` and release tags unchanged until:

1. All required checks succeed on the exact final release commit.
2. The full test suite and integrity manifest succeed after the final version bump.
3. Confidential-data and provenance checks are verified, not silently skipped.
4. An independent reviewer approves the release diff.
5. The maintainer explicitly authorizes the merge into `main`.
6. Only then create a signed/approved release tag and publish artifacts through
   the project's approved release workflow.

Do not infer that GitHub-hosted runners prove availability of macOS, Windows,
or Debian self-hosted Forgejo runners. Runner registration and execution must
be checked separately on the Forgejo instance.

## Session restart checklist

Read PR #18, inspect the latest head SHA and GitHub Actions checks, review the
private Forgejo port chain and issue #560, then continue only missing slices.
Do not merge cumulative Forge port branches wholesale. Preserve one-pen/LOCK
authority and the optional advisory-only routing boundary.
