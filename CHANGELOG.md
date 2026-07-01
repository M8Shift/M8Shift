# Changelog

## v3.32.0 — 2026-07-01

Release scope:

- #46 — Implemented RFC 027 local notifications in the runtime companion:
  `m8shift-runtime.py notify <agent> --event turn-ready|stale|blocked|done`
  and `notify config`.
- Added local notification tiers: stdout, prompt/event sidecar files, terminal
  bell, opt-in OS presets, and opt-in operator hook argv templates.
- Added deduplication for repeated `(agent, event)` notifications, notification
  audit rows under `.m8shift/runtime/notify/log.jsonl`, and runtime doctor checks
  for malformed config, missing OS notifier binaries, unsafe hook shape, and
  sidecar hygiene.
- `watch` now uses the same notification path for human-mode state transitions;
  JSON mode remains machine-readable.

Validation:

- Added tests for stdout-only mode, prompt/event/log sidecars, deduplication,
  CI suppression, missing OS notifier fallback, hook non-zero logging, literal
  argv placeholder substitution, removable notify sidecars, and runtime init
  scaffolding.
- Lockstep version surfaces bumped from `3.31.0` to `3.32.0` across distributed
  scripts and tests.

## v3.31.0 — 2026-07-01

Release scope:

- #55 — Implemented RFC 031 decision traceability:
  `decisions target` shows or persists the advisory target
  (`forge`, `github`, `both`, `git`, `md`), while
  `decisions scaffold` exports a durable decision record from existing turns.
- Added the markdown fallback: ADR-style `docs/decisions/NNNN-*.md` records by
  default, plus an append-only `DECISIONS.md` variant with `--single`.
- Added explicit advisory stance tagging on turns via `append --stance …`; the
  scaffold uses explicit stances and Stage-4 review decisions, never inferred
  FOR/AGAINST positions from prose.
- Shipped markdown, Gitea/Forgejo, and GitHub decision templates.

Validation:

- Added tests for markdown record creation, single-file fallback, target
  inference/config override, no-tracker `md` default, shipped templates, and
  proof that scaffolding leaves the journal/`LOCK` untouched.
- Lockstep version surfaces bumped from `3.30.0` to `3.31.0` across distributed
  scripts and tests.

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
