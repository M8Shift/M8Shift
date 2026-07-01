# Changelog

## v3.30.0 — 2026-07-01

Release scope:

- #56 — `m8shift.py init` now manages a marker-delimited M8Shift block in the
  host `.gitignore` by default, keeping relay state artifacts local and
  uncommitted.
- Added non-interactive flags `--gitignore` / `--no-gitignore`; headless init
  defaults to adding/refreshing the block without prompting.
- The generated block covers relay state, sidecars, temp files, backups, and
  session reports, but deliberately does not add agent anchors such as
  `CLAUDE.md` or `AGENTS.md`.

Validation:

- Added tests for absent `.gitignore` creation, user-entry preservation,
  idempotency, stale-block refresh, `--no-gitignore`, anchor exclusion, and
  malformed marker-block refusal without clobbering user content.
- Lockstep version surfaces bumped from `3.29.0` to `3.30.0` across distributed
  scripts and tests.

## v3.29.0 — 2026-07-01

Release scope:

- #45 — Implemented RFC 026 runtime sidecar retention policy:
  `m8shift-runtime.py retention apply [--dry-run] [--json] [--no-archive]`
  reads `.m8shift/runtime/retention.json`, while
  `retention policy show [--json]` reports the effective policy.
- Added opt-in retention strategies: `fixed-count`, `age`, and `combined`
  union semantics. Age-based policies keep undatable rows fail-safe and report
  them instead of pruning unknown timestamps.
- Policy pruning archives raw rows under `.m8shift/runtime/archive/` when enabled
  and appends compact audit rows to `archive/index.jsonl`; malformed JSONL
  ledgers are reported and left untouched.

Validation:

- Added policy tests for disabled no-op, policy show, each strategy, undatable
  row fail-safe, dry-run immutability, malformed JSONL, `--no-archive`, and
  archive index writes.
- Lockstep version surfaces bumped from `3.28.1` to `3.29.0` across distributed
  scripts and tests.

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
