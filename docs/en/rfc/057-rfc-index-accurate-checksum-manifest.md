# RFC 057 — Index-accurate checksum manifest enforcement

- **Status:** implemented (#51, 2026-07-13)
- **Scope:** local pre-commit maintenance of the shipped `checksums.sha256` manifest.
- **Builds on:** [RFC 017](017-rfc-stage6-integrations.md),
  [RFC 048](048-rfc-adoption-discipline-pack-update-health.md), and
  [RFC 052](052-rfc-project-compartmentalization-data-hygiene.md).

## Problem

The release manifest was verified at pre-push time, but contributors repeatedly had to
repair it in a follow-up commit after staging a checksummed file. Hashing the worktree
would be unsafe for partial staging because it could fold unrelated, unstaged bytes into
the commit.

## Decision

The shipped advisory `hooks/pre-commit` refreshes entries only when their paths are
already listed in `checksums.sha256` and staged. It hashes `git show :path` — the Git
index blob entering the commit — rewrites the manifest atomically, and stages the
manifest. A staged deletion removes the obsolete row.

For configured agents, `may-i-write` runs first so a failed pen guard cannot mutate the
index. Human/unconfigured commits skip only the pen guard; checksum maintenance still
runs. The hook refuses to absorb an unstaged manifest edit and fails closed on missing
Python, malformed staged-path data, hashing, rewrite, or staging failure. Pre-push
verification remains the independent backstop.

The hook is local workflow enforcement, not a security boundary. It does not add new
manifest entries automatically, contact the network, hash untracked files, or infer a
release scope.

## Acceptance criteria

1. A staged listed file refreshes and stages its manifest row in the same commit.
2. Partial staging hashes the index blob, never the worktree bytes.
3. A staged deletion removes the listed row.
4. An unstaged manifest edit is preserved and blocks automatic refresh.
5. A configured agent without the pen is refused before any index mutation.
6. Pre-push verification still detects any stale or corrupt manifest.
