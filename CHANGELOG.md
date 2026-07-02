# Changelog

## v3.42.0 — 2026-07-03

Security-hardening and portable-installer release. No new runtime features; this
consolidates the supply-chain, telemetry, boundary, and documentation work that
landed after `v3.41.0`. The optional Headroom/Kompress feature is intentionally
NOT in this release — it ships separately in `v3.43.0`.

Release scope:

- #82 / RFC 037 — portable multi-OS installer (`install.sh`) with opt-in RTK and
  Headroom options, plus adapter identity hardening (realpath + SHA-256 provenance
  pinning for project-local adapter executables).
- #94 — project-local adapters require an explicit
  `adapters init --allow-project-local-adapters` opt-in before any project-local
  executable is pinned or run; without it, resolution stays PATH-only and
  fail-closed. This opt-in is the documented trust boundary — provenance is
  drift-detection, not signature-by-authority.
- #4 / PR #5 — closed a case-insensitive-filesystem gap in that boundary:
  `is_path_under()` now falls back to `os.path.normcase` and a physical
  `(st_dev, st_ino)` ancestor walk when the lexical comparison is insufficient, so
  a case-variant of the project-local adapter bin dir on `PATH` (e.g. `.m8shift/BIN`
  vs `.m8shift/bin`) can no longer be discovered as a "system" executable and pinned
  without opt-in. Case-sensitive filesystems are unaffected. Regression tests added
  for rtk and headroom adapter names (skipped on case-sensitive filesystems).
- CodeQL HIGH (`py/incomplete-url-substring-sanitization`) — the commit provenance
  trailer parses the git remote host (`_remote_host` / `_is_github_host`) instead of
  a `"github.com" in url` substring match.
- RTK telemetry hardening — telemetry output is no longer emitted, sensitive RTK
  diagnostics are redacted, and RTK must be identity-pinned before any telemetry
  command is attempted.
- #97 — security documentation corrected for the post-#82 surface (test count,
  version scope, supply-chain/RCE claims scoped core-vs-adapters, threat-model
  invariants, OWASP Agentic Top-10 mapping, RFC 036 positioning).
- Agents guide — added a "Stale locks, force-claim, and worktree isolation" section
  (§7): a stale pen reclaims only the write token, never proof the peer is gone;
  one worktree, one owner; validate in an isolated detached worktree; keep the pen
  fresh during long work. Structural fix (liveness decoupled from pen-TTL) tracked
  in the relay-robustness backlog (#6).
- RFC 042 Phase C — whole-content measurement round recorded (documentation).

Validation:

- Full suite green on `main` (388 tests). No behavior change to the relay core.
- Lockstep version surfaces bumped from `3.41.1` (unreleased CodeQL patch) to
  `3.42.0` across distributed scripts, tests, examples, and docs.

## v3.41.0 — 2026-07-02

Release scope:

- RFC 042 Phase B — `m8shift-context.py compress` now accepts
  `--access-mode retrieve|inline` and `--whole-content`, records both advisory
  routing signals on compressed-context records, and keeps signal-driven
  Headroom routing gated behind future measurement.
- The v3.40.0 manual Headroom opt-in remains intact:
  `backends.headroom_ext.auto_enabled: true` still routes broad `--backend auto`
  records to pinned `headroom_ext`; explicit `--backend headroom_ext` remains
  available.
- #91 — `retrieve` now verifies raw and compact content hashes before serving
  evidence, and `compress` writes raw/compact artifacts through pending files
  before publishing the record last.
- #90 — architecture/specification docs now include color Mermaid views for
  module communication and inter-application agent flow.

Validation:

- Added tests for default/inline/whole-content signal plumbing, explicit and
  manual-opt-in Headroom behavior, internal fail-safe normalization, legacy
  record compatibility, tampered raw/compact retrieval rejection, and pending
  artifact cleanup.
- Lockstep version surfaces bumped from `3.40.0` to `3.41.0` across distributed
  scripts and tests.

## v3.40.0 — 2026-07-02

Release scope:

- #82 / RFC 037 follow-up — Headroom remains an optional operator experiment:
  `compress --backend auto` now keeps broad context types on the builtin digest
  unless `.m8shift/context-compression.json` explicitly sets
  `backends.headroom_ext.auto_enabled: true`.
- Explicit `--backend headroom_ext` is still honored for pinned adapter
  experiments and keeps the existing fail-closed/reference-only behavior.
- Future official Headroom wrappers must force offline/cache-only execution
  (`HEADROOM_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) and
  refuse to run unless the model is already cached.

Validation:

- Added tests for pinned Headroom + auto broad content with and without explicit
  config opt-in, explicit Headroom backend selection, absent/unpinned Headroom
  degradation, and drifted Headroom manifests.
- Recorded the follow-up library-mode measurement: `headroom-ai==0.28.0`
  can run in-process with a cached ONNX model, but the exploratory comparison
  is not like-for-like: builtin is a lossy digest plus mandatory raw retrieval,
  while Headroom is closer to a near-lossless conversation compressor. The
  default remains builtin because that matches M8Shift's handoff model.
- Lockstep version surfaces bumped from `3.39.0` to `3.40.0` across distributed
  scripts and tests.

## v3.39.0 — 2026-07-01

Release scope:

- #82 / RFC 037 Phase D — Added the optional `headroom_ext`
  `context_transform` backend for broad context compression records.
- `compress --backend auto` now uses an explicit content-type dispatch map:
  shell/tool content types stay on `rtk-shell-output` when identity-pinned, while
  broad content types (`conversation`, `history`, `file`, `report`, `diff`,
  `large-context`) try `headroom_ext` when it is installed and identity-pinned.
- `headroom_ext` is advisory, argv-only, one-shot, local-subprocess only. M8Shift
  does not start Headroom proxy/MCP/server modes and does not require Headroom to
  be installed.
- Adapter execution now uses a shared safe dispatch helper so RTK and Headroom
  mode/manifest/path identity failures degrade instead of crashing `auto`.

Validation:

- Added Headroom backend tests for pinned auto-selection, absent/unpinned
  degradation, drifted-manifest no-crash behavior, and secret redaction before
  backend input/output records.
- Recorded the measured local base Headroom footprint available during
  implementation: `headroom-ai==0.28.0` base wheels + dependencies = 37.04 MiB
  on the implementation Mac. No Headroom compression gain is claimed without a
  real-tokenizer + output-equivalence run.
- Lockstep version surfaces bumped from `3.38.0` to `3.39.0` across distributed
  scripts and tests.

## v3.38.0 — 2026-07-01

Release scope:

- #82 / RFC 037 Phase C — Added compression backend dispatch in
  `m8shift-context.py compress`.
- `compress --backend auto` now selects the existing RFC 034 `rtk-shell-output`
  adapter for shell/tool content types (`shell_output`, `test_output`, `logs`,
  `git_output`) when RTK is present and identity-pinned; otherwise it falls back
  to the builtin compressor without inserting raw content.
- Explicit `--backend rtk-shell-output` uses the same argv-only, identity-pinned,
  output-capped `run_adapter_process` path as adapter runs. Invalid/unavailable
  explicit backends fail closed to reference-only.
- Compression records now distinguish `requested_backend`, actual `backend`, and
  `backend_version`.

Validation:

- Added RTK compression backend tests for pinned auto-selection and RTK failure
  fallback to builtin without raw bleed-through.
- Lockstep version surfaces bumped from `3.37.0` to `3.38.0` across distributed
  scripts and tests.

## v3.37.0 — 2026-07-01

Release scope:

- #81 / RFC 037 Phase B — Added the local foundation for agent context
  compression in `m8shift-context.py`.
- `m8shift-context.py compress` now writes `compressed_context_record` JSON
  records that wrap `m8shift.adapter.result.v1`, with `context_digest`,
  `handoff_digest`, and `raw_output_reference` objects.
- Added the in-process builtin compressor: bounded head/tail digest, repeated
  line collapse, error/warning extraction, path extraction, and exit-code
  preservation.
- Raw evidence is redacted before local storage by default; missing or malformed
  `.m8shift/context-compression.json` fails safe to redacted reference-only.
- `m8shift-context.py retrieve` performs mandatory bounded retrieval by safe
  record id, with native stdlib `re` grep guarded by pattern length and simple
  ReDoS heuristics.
- Hardened the Phase B review findings before release: counted-repetition grep
  patterns are rejected, grep line scans are capped, compression record ids drop
  `:`, numeric config values are coerced fail-safe, and the secret pattern set
  was bumped to `m8shift.secret_patterns.v2` with common Slack, Google, Stripe,
  URL-inline credential, and identifier-embedded secret shapes.

Validation:

- Added negative tests for traversal record ids, ReDoS/oversized grep patterns,
  secret-bearing raw content, missing/malformed compression config fail-safe,
  and backend-error reference-only fallback.
- Added regressions for counted-repetition ReDoS patterns, embedded secret
  identifiers (`MYSECRET`, `aws_secret_access_key`), common token formats, URL
  inline credentials, invalid numeric config values, and `:` record ids.
- Lockstep version surfaces bumped from `3.36.0` to `3.37.0` across distributed
  scripts and tests.

## v3.36.0 — 2026-07-01

Release scope:

- #79 — Made RTK usage visible without changing the no-network/no-telemetry
  charter.
- `m8shift-runtime.py watch` records each agent lane's self-declared RTK state
  from `M8SHIFT_RTK=on|off`; absent or invalid declarations fail safe to `off`.
- `m8shift-runtime.py status-runtime` now surfaces both per-agent RTK
  declarations and the context-adapter RTK state (`RTK: ON (pinned, compressing
  packs)` / `RTK: OFF (native)`), plus the last context-pack compression ratio
  when metrics are available.
- `m8shift-context.py status` was added, and `doctor` now uses the same
  prominent RTK state line and last-pack metric summary.
- Read-only RTK status paths fail closed without hanging/aborting: non-regular
  trusted executable paths and >512 MiB RTK binaries are treated as RTK OFF, and
  corrupt RTK manifests or malformed metrics rows are reported as findings.
- Documentation now states that `rtk discover` is the audit path for an agent's
  actual shell command usage; M8Shift does not re-enable RTK telemetry.

Validation:

- Added regression coverage for self-declared `M8SHIFT_RTK`, absent/invalid RTK
  declarations, context-adapter ON/OFF surfacing, last-pack ratio display, and
  no network-client imports in the touched scripts.
- Added adversarial negative tests for FIFO/device-like trusted executable paths
  and corrupt context-sidecar JSON.
- Lockstep version surfaces bumped from `3.35.0` to `3.36.0` across distributed
  scripts and tests.

## v3.35.0 — 2026-07-01

Release scope:

- #59 Phase 1 — Added advisory-only model/task routing recommendations in
  `m8shift-runtime.py route recommend`.
- Added empty, provider-neutral `.m8shift/routing/models.json` and
  `.m8shift/routing/skills.json` manifests during runtime init; no vendor list,
  no bundled prices, no launch path.
- Selection is capability-first: task floor, required capabilities, and context
  gates are hard filters; cost is minimized only among eligible models and
  latency breaks ties.
- Unknown task types, missing manifests, and no eligible model fail safe to the
  pen-holder/self path, or report no delegation recommendation when no self model
  is known.
- Runtime `doctor` validates routing manifests.

Validation:

- Added tests for missing manifests, cheapest eligible selection, floor
  preservation, self fail-safe, adversarial-verify pinning, and doctor manifest
  errors.
- Lockstep version surfaces bumped from `3.34.2` to `3.35.0` across distributed
  scripts and tests.

## v3.34.2 — 2026-07-01

Release scope:

- #73 — Hardened runtime retention path handling as defense-in-depth:
  backslash-separated parent segments in ledger policy patterns are rejected, and
  runtime JSONL append paths refuse symlink redirection before archive/index
  writes.
- Normal retention behavior is unchanged for real runtime ledger/archive files.

Validation:

- Added regression coverage for unsafe `..\\...` retention patterns and
  symlinked archive targets.
- Lockstep version surfaces bumped from `3.34.1` to `3.34.2` across distributed
  scripts and tests.

## v3.34.1 — 2026-07-01

Release scope:

- #76 / CTX-1 — `m8shift-context.py pack` now degrades to the native stdlib
  pack path when the RTK manifest is corrupt, unreadable, or not a JSON object in
  automatic adapter mode.
- Explicit operator selection remains fail-closed: `pack --adapter
  rtk-shell-output` still aborts on corrupt or invalid manifests.

Validation:

- Added regression coverage for broken JSON and non-object
  `rtk-shell-output.json` manifests in automatic pack mode.
- Lockstep version surfaces bumped from `3.34.0` to `3.34.1` across distributed
  scripts and tests.

## v3.34.0 — 2026-07-01

Release scope:

- #76 — Enabled the RTK shell-output adapter by default for context packs only
  when `rtk` is present and identity-pinned. If RTK is absent, unpinned, or
  invalid, `m8shift-context.py pack` degrades to the native stdlib pack path.
- Added explicit operator opt-out for context packing with
  `pack --adapter native` / `--no-rtk`.
- `m8shift-context.py init` and `adapters init` now attempt
  `rtk telemetry disable` whenever RTK is present; `doctor --json` surfaces RTK
  presence, pin status, telemetry state, and the no-network/local-subprocess
  boundary.
- `install.sh` now downloads `m8shift-context.py` by default and offers optional
  RTK installation via Homebrew only with operator consent (`--with-rtk`, prompt,
  or `--no-rtk`), then runs `rtk telemetry disable` when RTK is present.

Validation:

- Added tests for pinned-RTK default selection, absent-RTK native degradation,
  operator opt-out, telemetry-disable setup, doctor RTK status, installer RTK
  telemetry handling, and existing identity-pin fail-closed behavior.
- Lockstep version surfaces bumped from `3.33.0` to `3.34.0` across distributed
  scripts and tests.

## v3.33.0 — 2026-07-01

Release scope:

- #47 — Implemented RFC 028 as a curation/spec layer over RFC 014 provider
  argv rendering and RFC 020 hardened headless runner behavior.
- `.m8shift/providers.json` generated by `m8shift-runtime.py init/providers init`
  now includes opt-in curated examples for cooperative CLI runs (`codex exec`,
  `claude -p`) with argv-only templates, `//` guidance markers, explicit
  `env_allowlist`, and optional `argv_by_platform` arrays.
- `m8shift-runtime.py providers render/check` now supports platform-specific
  argv selection, validates `argv_by_platform`, rejects shell-string argv, and
  checks the selected `argv[0]` without shell interpolation.
- `examples/headless_runner.py` now writes and validates the mandatory RFC 028
  run-plan fields: `agent`, `argv`, `cwd`, `run_id`, `prompt_hash`,
  `env_allowlist`, `timeout`, `kill_grace`, and `expected_transition`.
- The headless runner now launches the resolved argv in an explicit `cwd` with
  an explicit env allowlist, and reports success only when the process exits
  `0`, the expected transition occurs, the lock is not stolen, and lifecycle
  ledger events are present.

Validation:

- Added tests for mandatory run-plan validation, shell-string rejection,
  platform argv selection, missing transition, stolen lock, non-zero exit after
  progress, provider examples, and provider `argv_by_platform` diagnostics.
- Lockstep version surfaces bumped from `3.32.0` to `3.33.0` across distributed
  scripts and tests.

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
