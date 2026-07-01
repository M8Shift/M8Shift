# Changelog

## v3.28.1 — 2026-07-01

Release scope:

- #72 — Hardened the `commit-msg` hook fail-open guarantee: a non-UTF-8
  `COMMIT_EDITMSG` now exits 0 and leaves the message unchanged instead of
  aborting the commit.
- #58/#7 — `Agent-Model` provenance can now be stamped from
  `M8SHIFT_AGENT_MODEL` even when no relay version is readable; `Coordinated-With`
  remains gated on a readable relay/local version.

Validation:

- Added a regression test with a Latin-1 commit message byte.
- Lockstep version surfaces bumped from `3.28.0` to `3.28.1` across distributed
  scripts and tests.

## v3.28.0 — 2026-07-01

Release scope:

- #61 — Bound the native context companion git collector with a timeout, so
  context pack collection cannot hang indefinitely on a stuck git command.
- #62 — Implemented RFC 035 PAUSED-aware waiting: listeners stay armed while a
  session is paused, remain quiet, and wake when the session is explicitly
  resumed.
- #63 — Implemented RFC 036 runtime headroom guard: the runtime companion now
  exposes Tier-0 context headroom signals and can surface checkpoint pressure.
- #64 — Shipped the RTK shell-output adapter with identity-pinned execution:
  `rtk` is verified by resolved absolute path plus SHA-256, closing PATH hijacks,
  renamed relay copies, and wrapper-script bypasses.
- RFC 034 / RFC 035 / RFC 036 documentation updated to match the shipped
  companion adapter, listener, and headroom behavior.
- Guide rules #66 and #68 added: update the site after every stable tag and log
  user-visible decisions on the relevant ticket.

Validation:

- Lockstep version surfaces bumped from `3.27.0` to `3.28.0` across distributed
  scripts and tests.
- Full test suite passed before handoff for tag publication.
