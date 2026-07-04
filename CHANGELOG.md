# Changelog

## v3.47.0 — 2026-07-04

RFC 047 complete — the headless liveness block (closes #21; #6 keeps its broader
holder-liveness/force-claim scope).

- **Listener lifecycle companion** (`m8shift-runtime.py listener start|stop|status|logs`):
  a supervised headless lane in one command — zero model spend while polling, exactly one
  bounded runner turn per wake, `start_on_idle` opt-in (one starter per roster, enforced),
  PID/process-group lifecycle with stale-PID detection/repair, persistent `halted` phase
  honored across restarts AND service managers, writer-side log rotation (5 MiB, keep 3,
  `runs.jsonl` exempt).
- **OS service backends** behind a pure selection matrix + injectable probe seam:
  launchd (plist, `KeepAlive=false`), systemd user unit (`Restart=no`, link+start),
  Windows schtasks — all argv-only; `auto` falls back to `local` with a printed reason
  (no GUI/user session, macOS protected folder).
- **Runner `--resume-working`** (requires `--once`): recovery launches on an own
  `WORKING` lock; the provider child gets `M8SHIFT_RESUME_WORKING=1` only on genuine
  resume launches. The listener's stuck-`WORKING` retry is re-enabled exclusively
  through this path (deadlock found in review of the PR-1 draft path).
- **Doctor**: 9 advisory `listener.*` findings (not_installed, dead, backend_failed,
  protected_folder, version_skew, repeated_non_completion, halted, multiple_starters,
  log_too_large).
- Phase E docs: runtime module page, README, specification EF-30 + RFC-surface row,
  agents-guide headless note.

Lockstep bump to `3.47.0`. Full pytest suite: 473 passed (pytest `tests/`;
the equivalent single-module unittest run counts 411 — both green).

## v3.46.0 — 2026-07-04

RFC 047 Phase A — headless runner final-state enforcement (closes #17).

- Post-run classification is now **authorship-primary and total**: a run succeeds iff
  the relay is `DONE` or this agent authored a transcript turn numbered above the
  pre-run turn. Statuses: `completed`/`advanced`/`non_completion`/`stuck_working`/
  `suspended`/`external_transition`/`invalid_relay`; bounded LOCK re-read for
  transient errors; exit map 0 success / 1 failure / 2 infrastructure-timeout /
  3 external transition / 4 suspended; the retry counter moves only on provider
  failures. Covers the fast peer ping-pong race, operator reset, the `integrating:`
  sentinel, and usage cooldowns (never burn retries).
- New core guard `claim <agent> --refresh`: refresh-only TTL heartbeat, refused unless
  the agent already holds its own `WORKING` lock, mutually exclusive with `--force` —
  closes the plain-claim ghost-claim TOCTOU found in the RFC 047 adversarial review.
  Runners must never heartbeat with a plain claim (protocol core, EF-7, module docs).
- `run.non_completion` runtime events with pre/post snapshots; heartbeat failures emit
  `run.heartbeat_failed` and never abort the run; no automatic force-claim anywhere.
- Listener lifecycle companion (#21) = RFC 047 Phases B–E, next.

Lockstep bump to `3.46.0`. Full suite green (442).

## v3.45.1 — 2026-07-04

Detailed help release (operator request): every CLI parameter documents itself.

- Every `add_argument` across the 7 shipped scripts now carries a `help=` line
  (146 previously bare parameters annotated: 54 core, 53 runtime, 25 context,
  10 worktree, 4 launchers/harness), and every `add_parser` carries its one-line
  summary — `--help` prints one described line per parameter everywhere.
- New guard tests (`TestDetailedHelpCoverage`): any future flag added without
  `help=` fails the suite.
- No behavior changes: help/description text only. Lockstep bump to `3.45.1`.
  Full suite green (428).

## v3.45.0 — 2026-07-03

RFC 046 (part 1) — execution modes and project identity.

- `status` and `watch` now surface the **project name, cwd, and root** in their header
  (human, `--json`, and the watch banner), so multiple open terminals stay
  distinguishable. `cwd` is the real working directory (`os.getcwd()`) and `root` is the
  relay root (`project_root()`); the human block and `--json` agree, and the two diverge
  correctly when the tool is invoked from a subdirectory.
- The project label prefers the operator's **`init --name`** (persisted on the session
  start event), falling back to the relay-root folder name.
- The **status-guard** rule now lives in the generated protocol core (every anchor), not
  only the agents-guide: never claim you hold the pen or reached `DONE` from memory —
  re-run `status --for <agent>` before ending a turn or asserting state. agents-guide also
  gains the **interactive vs headless** distinction and the interactive-UI honesty message.
  This closes the stale-baton desynchronization observed in a pure chat UI.
- The RFC 046 runner-install (copy `examples/headless_runner.py` + `scripts/watch-status.sh`
  on init) lands next.

Lockstep bump to `3.45.0`. Full suite green.

## v3.44.0 — 2026-07-03

Adoption and documentation release.

Release scope:

- RFC 044 — `init` gains a version-locked companion-install phase: `--companions
  runtime,context,...` / `--with-*` / `--full` copy the selected companion scripts into
  the kit dir, version-locked to the core, idempotent, no-clobber (edited/newer refused,
  never downgrades), atomic, allowlisted selectors, static VERSION parse (no import),
  merged `.m8shift/kit.json` manifest, and `--companion-source <dir>` to copy from a
  release/checkout dir. Companion selection is preflighted before any mutation and exits
  non-zero on failure (no half-initialized relay); the copy is serialized under the relay
  lock. `doctor` gains read-only `kit.companions` checks (missing/skewed/edited).
- RFC 045 — one reference/example page per shipped module under `docs/en/modules/`
  (core-relay, runtime, context, worktree, headroom, i18n, e2e) plus an index, each with a
  color Mermaid ownership diagram, a command table, tagged runnable examples, failure
  modes, and links to owning RFCs/tests. A drift test keeps the pages in lockstep with the
  module set. All pages carry the honest compression framing (RTK = lossy filter, Kompress
  ~45–55% prose only, stored = excerpt).
- RFC 040 — a Phase 2/3 implementation contract (usage `snapshot`/`adapters`/`guard` CLI +
  exit codes + exact `usage.jsonl`/`usage-hold.json` bytes + RFC 034 adapter I/O + Claude/
  Codex readers + a per-agent token-consumption timeline) and RFC 023 — a stricter
  measurement methodology from the compression cross-test (documentation).
- agents-guide §3 — a post-push GitHub hygiene step (verify CI/CodeQL green + no anomalous
  issue/PR + delete merged branches) and a corrected honest token-economy figure.

Validation: full suite green. Lockstep version surfaces bumped to `3.44.0`.

## v3.43.0 — 2026-07-03

Optional Headroom/Kompress context-compression adapter — the feature deferred
from v3.42.0. Everything here is **opt-in**; the relay core stays stdlib-only,
no-network, no-daemon, and unchanged.

Release scope:

- #95 — `compress --backend headroom_ext` routes context through a pinned,
  project-local Headroom/Kompress wrapper that produces a real Kompress ONNX-int8
  compact (~46–55% reduction on prose/RFC content) **offline** (socket-blocked,
  `HF_HUB_OFFLINE`, model served from cache only). Verified end-to-end on a live
  arm64 venv.
- `m8shift-headroom.py` — offline wrapper: redaction-preserving, fail-closed on
  import/runtime error with no secret echo, calls `KompressCompressor` directly and
  gates on `compressed_tokens < original_tokens`.
- `install.sh --with-headroom` — creates a native-arch venv
  (`headroom-ai==0.28.0` + `onnxruntime==1.27.0` + `transformers==5.12.1`),
  preloads `chopratejas/kompress-v2-base`, installs the launcher, and identity-pins
  it (realpath + SHA-256) — requiring the `--allow-project-local-adapters` opt-in.
- Routing stays conservative: explicit `--backend headroom_ext` only; `--backend
  auto` remains on the builtin digest until the Phase D evidence gate
  (`backends.headroom_ext.auto_enabled`) is opened. Redaction always runs before
  the adapter.
- Inherits the v3.42.0 case-insensitive-FS boundary fix; the project-local
  exclusion is verified for the Headroom venv two-dir layout (a case-variant of
  `.m8shift/venvs/headroom/bin` on `PATH` cannot bypass the opt-in).

Validation:

- Full suite green (400 tests) on the rebased branch; independent case-variant
  bypass PoC (rtk + Headroom venv) and offline compression E2E confirmed.
- Lockstep version surfaces bumped to `3.43.0` (including the new
  `m8shift-headroom.py`, previously out of lockstep at `3.41.1`).

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
