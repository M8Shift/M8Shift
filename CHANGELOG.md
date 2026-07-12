# Changelog

## Unreleased

- **#108 slice 2 + #107 — usage/listener liveness surface.** Listener status
  reports explicit host-wake capabilities (`can_invoke_agent`,
  `survives_parent_exit` — backend-only, no residency conflation —
  `backend_configured`, `last_successful_run`); interactive `wait`/`next`
  disclose their host-lifecycle limit (TTY-only); runtime doctor gains one
  fail-open `runtime.stale_state` advisory for a stale AWAITING turn without a
  live listener and for stale usage snapshots. **#107:** when the newest usage
  snapshot has no usable windows (a transient empty official fixture at a watch
  tick), the core display falls back to the newest snapshot WITH usable
  windows, explicitly marked stale (a clean public `last_known` boolean in
  `status --json`; no underscore-prefixed internal keys leak); the em-dash is
  byte-identical when no usable snapshot exists at all.
- **#92 — compression pending-file hardening.** Exclusive
  `O_CREAT|O_EXCL|O_NOFOLLOW` temporary writers (symlink/clobber resistant),
  pending cleanup on backend abort and via `finally`, the record published
  through pending-replace-last, and a `doctor` `compression.stale_pending`
  sweep of leftover `*.pending.*`/`*.tmp.*` under `context/compression/`.
- **#96 — RTK routing-adoption advisory.** Runtime `doctor` derives a per-agent
  RTK adoption ratio from the pinned local `rtk discover --format json`
  (bounded subprocess), warns below a configurable threshold
  (`M8SHIFT_RTK_ADOPTION_THRESHOLD`, clamped), and reports an explicit
  `unavailable` state for non-Claude lanes or missing/disabled RTK. Advisory,
  fail-open, never gates.
- **Security (v3.58.0 adversarial hunt).** Two confirmed findings fixed:
  `doctor` no longer renders attacker-authorable `skills/*/SKILL.md` values
  (directory names, `name`, `m8shift-lane`, oversized-body path) into human
  output without stripping terminal-escape / control bytes (RFC 050 skills
  path now reuses the RFC 051 display whitelist); and the opt-in
  `examples/usage-adapters/tokscale-spend.py` reader is now memory-bounded
  (daemon reader capped at the size limit + kill-on-overflow) instead of
  materializing the child's entire stdout before the post-hoc cap check.
- **RFC 053 (draft) — shared rules and governed habits.** A design-only RFC for
  a governed project-local normative-rules layer distinct from memory (RFC 004),
  skills (RFC 041), and preferences; quarantine→candidate→proposed→active
  lifecycle, ≥2 human-scrutinized evidence + explicit human validation,
  pen-gated mutations when a relay governs, gitignored-by-default artifact, and
  a hard reserved-authority boundary (learned content never touches the
  mutex/pen/permissions/security floors). No code.

## v3.58.0 — 2026-07-12

Open-format Agent Skills (RFC 050 Phase 1+1b), the host wake-up guard
(#108 slice 1), deterministic shift demos (#102), and the opt-in tokscale
spend adapter (#103).

**Opt-in tokscale spend adapter example (#103).** `usage init` scaffolds a
fifth DISABLED adapter entry, `tokscale-spend` (`cli_json`, placeholder
command the operator points at their local tokscale install), and
`examples/usage-adapters/tokscale-spend.py` ships as reference material
(not in checksums): it runs tokscale's local non-interactive JSON output
via argv, sums token counts with a bounded version-tolerant reader
(explicit totals preferred — never double-counted), and emits a SPEND
fixture (`used_tokens` only, `limit_tokens` null, NO invented windows,
provenance `local_estimate` — official windows stay with the
Keychain/app-server adapters; gating only through the explicit budget.json
bridge). Costs and identity fields are never copied. A hard never-submit
guard refuses any argv mentioning submit/autosubmit/login BEFORE launching
anything (RFC 052: usage data never leaves the machine through M8Shift).
Fail-open everywhere; injectable main; mutation-gated tests.

**Shift demos (#102).** `examples/shift-demos/` ships four tiny,
self-contained two-agent exercises (reference pair claude ↔ codex, any pair
works) with deterministic oracles: compute-and-verify (pinned SHA-256),
fix-and-review (pinned failing test turns green), spec-implement-verify
(pinned test file, solution gitignored), and adversarial-verify (a
plausible-but-wrong claim refuted against a fixed file). Each demo has a
one-paragraph README and initializes its own relay in place; runtime
artifacts stay gitignored. A repo test class pins every oracle without
spoiling the exercises (true digest, exactly-one-red start, unimplemented
start, both claim parts wrong).

**Host wake-up guard (#108).** A live incident stalled a handoff in
`AWAITING_<agent>`: a shell waiter (`wait --interval 300`) had been described
as an autonomous loop, but waiters DETECT a turn and exit — they cannot wake a
completed chat/model turn, and no resident listener existed. The generated
guidance now carries the guard on both surfaces: the stanza floor states
"waiters detect, never launch — without host wake-up, say a human must
reactivate you" (a new `wake-up` floor marker pins it), and the agent pack
gains a full "Host wake-up guard" section (poll / waiter / listener /
chat-wait terminology, the `listener status --agent <you>` decision rule with
ALIVE = resident process + valid invocation backend, disclosure duty, and the
detection-is-not-invocation rule). agents-guide documents the same
terminology for contributors. Runtime improvements (listener status
`can_invoke_agent`/`survives_parent_exit`, `wait` interactive notice,
stale-AWAITING notifier) remain #108 slice 2, designed jointly with #107.

**RFC 050 — manual multi-agent specialists as open-format Agent Skills
(Phase 1 + 1b).** Specialist definitions adopt the open Agent Skills format
(agentskills.io): one directory per skill under `skills/` with a `SKILL.md`
(`name`/`description` frontmatter; M8Shift lane properties under namespaced
`metadata:` keys — `m8shift-lane`, `m8shift-report`). Ships two seed
specialists (advisory `security-review-advisory` with a bundled report
template; mutating `worktree-implementer` carrying the foreign-loader safety
contract: explicit `compatibility`, authority preconditions, stop-and-report,
inert outside an M8Shift project), no executable `scripts/` in seeds, a
product-wiring walkthrough (`examples/skills-wiring.md` — discovery is
product- and version-specific and explicitly operator-wired), the
agents-guide source-of-truth link, and the RFC 041 amendment (bespoke format
+ `index.json` superseded). `doctor` gains bounded, fail-open, advisory
`skills.*` findings (`frontmatter_invalid`, `lane_unknown`,
`metadata_unknown_key`, `oversized`, `unvalidated`): a conservative stdlib
frontmatter subset is validated (single-line plain scalars + one indented
`metadata:` block); anything outside the subset deterministically degrades
the whole file to a single `skills.unvalidated` info finding (valid-but-
unsupported YAML is never labeled invalid), and skills.* findings never gate
`--lint`, even under `M8SHIFT_SCRUB_ENFORCE`.

## v3.57.0 — 2026-07-11

RFC 049 holder-liveness completion, a unified multi-window usage display, and
live-verified usage adapters.

**Live-verified usage adapters (#105).** The two reference adapters fold back
the fixes discovered by running them against the REAL providers (2026-07-10):

- `examples/usage-adapters/claude-oauth-usage.py` now understands the LIVE
  endpoint shape — top-level `five_hour`/`seven_day` objects carrying a
  USED-percent `utilization` (no inversion) and an OFFSET-BEARING `resets_at`,
  normalized to the strict-`Z` form the usage schema requires. A timezone-NAIVE
  reset (no offset) is ambiguous and never invented — `astimezone()` would
  assume the host timezone and make the same payload host-dependent — so a naive
  reset normalizes to `null`; likewise a calendar-bound aware reset whose UTC
  conversion overflows degrades ONLY `resets_at` to `null` while still recording
  the valid utilization ratio (never dropping the whole window). Fallback
  precedence is EXACT: any successfully
  normalized `windows[]` entry suppresses the fallback; only an empty normalized
  list (windows[] absent / non-list / empty / all-invalid) attempts the
  top-level live shape, degrading per entry (non-dict window, implausible
  utilization, unparseable/naive reset).
- `examples/usage-adapters/codex-ratelimits.py` no longer uses a
  `communicate()`-style write-then-close call: codex-cli 0.144.1's app-server
  DROPS pending requests when stdin reaches EOF, losing the `id=2` response and
  hanging to the timeout. stdin now stays OPEN while stdout is read on a DAEMON
  reader thread feeding a queue; the main thread waits on the queue with the
  remaining monotonic deadline, so even a SILENT-but-live server is bounded (a
  blocking `readline` can never outrun the deadline). Cleanup is non-racing:
  ONLY the reader thread ever touches stdout, and on exit the child is killed,
  the reader is JOINED (bounded), then the child is reaped with `wait()` — which
  never reads stdout — instead of `communicate()` (which would read stdout
  concurrently with the reader). Portable — no `select` on Windows pipes.
  Fail-open semantics unchanged.

Both foldbacks originate from the copies that served the live relay all day
(2026-07-10, including the saturation events), further hardened in review
(bounded silent-child deadline, aware-only resets). The process-contract tests
are re-pinned to the held-stdin protocol (including a regression that goes RED
if stdin is closed before the reply is read, plus a silent-live-child deadline
bound) and the live claude shape is pinned with mutation-verified tests
(inversion, missing-normalization, and naive-reset all bite).

**RFC 049 PR C — worktree ownership sidecar and advisory guard (#104).**
`m8shift-worktree.py claim` now records the claiming agent in
`.m8shift/worktree-owners/<id>.json` (`m8shift.worktree_owner.v1`) — a SIBLING
of the checkout (not a file inside it), so normal edits confined to the
worktree do not touch it. `done`/`integrate`/`drop` refuse when a DIFFERENT
agent owns the worktree unless `--takeover --reason TEXT` is explicit; a
takeover re-stamps the sidecar with an audit trail (previous owner, reason,
timestamp) and preserves the original `created_at`. New read-only
`doctor [--json]` emits `worktree.owner_missing` (managed worktree without a
USABLE sidecar) and `worktree.owner_mismatch` (well-shaped metadata conflicting
with roster/path/branch, or an orphan sidecar) — never repairs, never gates.
This is an ADVISORY companion guardrail, NOT a security boundary (direct
git/editor/filesystem writes never pass through the companion, RFC 049
"Security and prompt boundaries"), but the mechanism is hardened:

- **Actor-first.** Every actor is roster-validated BEFORE any owner read/write
  or destruction — an unknown agent can no longer drop or take over a worktree.
- **Per-id ownership lock + generation-aware compare-and-swap.** Every
  ownership mutation for a worktree id — `claim` create, `done`/`integrate`/
  `drop` takeover, and `drop`'s WHOLE authorize→remove→cleanup span — runs under
  a per-id lock (`.m8shift/worktree-owners/<id>.lock`), finer-grained than the
  global core lock so `git worktree remove` never freezes the relay yet no
  concurrent takeover can slip between a drop's authorization and its removal.
  Under that lock the takeover ticket (captured beforehand) is an OPTIMISTIC
  EXPECTATION, not authority: the commit re-reads the current owner and requires
  it to still equal the ticket's expected prior owner AND its per-claim
  GENERATION nonce, refusing (writing nothing) otherwise. Each `claim` stamps a
  fresh nonce and a takeover preserves it, so a drop + re-claim by the SAME
  agent yields a new generation the stale ticket can never match (agent-name ABA
  is defeated). `integrate` re-applies a supplied takeover even on the resume
  path (a sidecar that went foreign mid-integration is never bypassed). A `drop`
  whose post-removal completion audit cannot be written reports a bounded
  partial-failure (rc 2) instead of a silent full success. The per-id lock
  breaks a stale lock ONLY when its recorded holder PID is provably dead and its
  inode/token is unchanged (a slow-but-live `git worktree add/remove` is never
  stolen), never reclaims or spins on a directory/non-regular lock (the
  contender times out BUSY), unlinks only its own unchanged token on release,
  and FAILS CLOSED on a lock-acquisition error in a SAFE owners directory rather
  than running a mutation unserialized.
- **Durable audit + atomic `integrate`.** Every takeover appends to a durable
  append-only ledger (`.m8shift/worktree-owners/_takeovers.jsonl`) — the audit
  that survives a `drop` (which destroys the sidecar): drop records `authorized`
  before the removal and `completed` after, distinguishing an authorized-but-
  failed drop from a completed one. For `integrate`, the authoritative pen
  check, the mandatory audit, and the pen flip are ONE serialized phase under
  the core file lock: a busy pen transfers nothing and a failed audit flips
  nothing (the become-busy race is closed, not merely narrowed). Every mandatory
  audit is durable-ledger-first and fails CLOSED — a failed write leaves
  ownership unchanged and reports failure instead of printing success.
- **Path-safe writes.** Writes go through the core's unpredictable-temp
  `+ os.replace` primitive inside a validated real parent (no symlinked
  `.m8shift`/`worktree-owners` component; contained in ROOT by realpath/
  commonpath). Precise guarantee: a pre-existing symlinked parent or a
  preplanted fixed-temp is refused; a live privileged attacker *concurrently*
  swapping a parent into a symlink between validation and use (classic TOCTOU,
  no portable stdlib `openat2(RESOLVE_NO_SYMLINKS)` on `makedirs`/`replace`) is
  the same out-of-scope write class the RFC 049 threat model already excludes —
  documented, not papered over.
- **Strict semantic reader + sanitized output.** The reader is bounded,
  path-safe, and STRICT: schema, exact id, roster-shaped agent, a REAL canonical
  UTC-Z `created_at` (an impossible `2026-99-99T99:99:99Z` is rejected, not just
  shape-checked), a bounded relative path, a NON-EMPTY branch, and an all-or-none
  takeover audit tuple (a partial/ANSI/oversized/impossible-time audit makes the
  whole doc malformed). A malformed/symlinked/oversized/wrong-shaped sidecar
  reads as `owner_missing`; well-shaped metadata conflicting with reality
  (off-roster agent, wrong path, or a recorded branch while the worktree is
  DETACHED) is `owner_mismatch`. No recorded agent/id/path/reason, orphan
  filename, or foreign-checkout path is ever echoed raw — every untrusted string
  (including the `status` worktree name and `integrate` error paths) is reduced
  to printable ASCII (RFC 052 §9.5). `status` lists a DETACHED-HEAD worktree
  (marked `(detached)`) and shows `owner=n/a` for the shared `_integration`
  tree, so it agrees with `doctor`/`_managed_worktrees`.

A self-run adversarial hunt over the ledger + under-lock rework confirmed the
`integrate` atomicity and closed a robustness asymmetry: the ledger writer now
mirrors the reader's `O_NONBLOCK` + `S_ISREG` guard, so a FIFO planted at the
ledger path fails closed instead of BLOCKING a write-only open forever (which
would freeze the relay under the global lock). Timestamp validation is now
strictly canonical — the string must equal the re-rendered
`strftime("%Y-%m-%dT%H:%M:%SZ")` of a real instant, rejecting single-digit
fields, whitespace padding, and non-ASCII year digits that bare `strptime`
would accept — and a whitespace-only `takeover_reason` no longer validates.

52 new tests (10 lifecycle/guard/doctor + 42 adversarial hardening: tmp/dir
symlink escape, FIFO-ledger fail-closed-no-hang, unknown-actor destruction,
durable drop audit + dirty-tree attempted-vs-completed + no-phantom-on-missing,
deterministic ledger-dir fail-closed audit, a git-hook race seam proving
`integrate` atomicity, driver-level compare-and-swap concurrency (stale-ticket
refusal, truthful `from`, resume re-applies takeover, cmd_drop completed-audit
failure surfaced rc 2, same-agent drop/reclaim ABA refused by the generation
nonce, drop authorize↔removal atomic vs a foreign takeover), per-id lock
robustness (live long-holder not stolen, dead-holder reclaimed, directory-lock
no-hang, cleanup never unlinks a successor, safe-dir acquisition fails closed, Windows tasklist probe fail-safe, malformed-token no-reclaim),
impossible/non-canonical-calendar, empty-branch, detached,
all-or-none-audit-tuple/whitespace-reason schema, ANSI/oversized/traversal,
detached-HEAD + `_integration` status↔doctor agreement).

**Unified multi-window usage line (#106, RFC 051 amendment E).** The
`── usage ──` block in `status`/`watch` now renders EVERY plausible
`windows[]` entry inline — consumed percentage plus its reset —
instead of only the decision window:
`codex  5h 64% (Reset 18:05) - weekly 42% (Reset 16/07 23:45) · (official) · 2m ago`.
The reset shows the DATE (`dd/mm HH:MM`) whenever it does not fall on today's
local date, so a weekly window resetting next Wednesday never reads as tonight.
Window labels adapt to each agent's real window kinds (`session_5h` → `5h`,
anything else sanitized as-is — inter-agent generic); per-window percentages
are enforced to the schema range (finite, non-bool, `[0, 1]` — a hostile
`-0.5`/`1.5` never renders `-50%`/`150%`), and fragments degrade at FIELD
level, never row level (an unhashable hostile `kind` skips that fragment; the
valid sibling windows and the agent's row — human and `--json` — stay
visible), capped with a disclosed `+N` overflow. Snapshots without a plausible
`windows[]` (older adapters, spent-only scans) keep the previous single-window
layout, with one intentional correction: the fallback `resets …` fragment also
carries the date when the reset is not same-day. `--json` output is unchanged
(the full `windows[]` was already echoed). The watch `--changes-only`
signature now covers per-window changes.

**RFC 049 PR B — the listener is the managed liveness producer (#104).** While
a child runner turn is ALIVE, the listener supervision loop now emits
PROTECTIVE heartbeats through the core `heartbeat` verb (never writing the
sidecar itself) at `min(poll, 60)s` cadence, and performs the early
`claim --refresh` at ~TTL/2 when it owns the holder turn — closing the exact
gap of the recorded incidents: a long-running child could outlive the pen with
no liveness signal. Every liveness call is fail-open (logged once, supervision
never interrupted); a relay outside the agent's WORKING window skips quietly.
Unit-tested via the injectable tick (heartbeat / refresh-first ordering /
foreign-window no-op) and integration-tested against a real sleeping child
emitting a real protective beat.

**RFC 049 PR A — holder liveness core (#104).** A managed producer can now
prove a WORKING holder is alive: new `heartbeat <agent> --source
runtime-listener|wrapper --cadence-seconds N` verb (RFC 052-gated,
validated before any write) records PROTECTIVE beats; force protection uses
`age <= max(120, min(2*cadence, TTL))`. `claim --refresh` records audit-only
beats (never protective after expiry). `claim --force` recovery is TWO-PHASE:
observe + capture the identity tuple under the lock, release, sleep a fixed
5s grace (never blocking the holder's own refresh), reacquire and revalidate
— one attempt, three pinned refusal branches (changed identity / refreshed
TTL / new protective beat); `next --force` clamps its interval to [5s, 60s]
as its grace. An alive-expired lock (fresh protective beat) refuses ordinary
force-claim; `--live-override --reason` is the audited human-authorized
escape. Stale recovery and every explicit forced release are audited as
session events (prior holder, captured identity, reason, override flag); the
pinned force + release-back sequence preserves the journal, the pending
handoff, and the turn number byte-for-byte (asserted twice in a row, with the
recoverer's own pending incoming turn no obstacle). `status` (human and JSON)
exposes the liveness sub-state and bounded heartbeat metadata; `wait`/`next`
distinguish alive-expired (keep waiting, never offer force) from
ordinary-stale; doctor extends the ONE canonical `lock.stale_working` with
the liveness sub-state and adds `holder.heartbeat_malformed` /
`holder.heartbeat_orphaned`; orphan beats are cleaned best-effort on
`release`/`done`. Documented in the EN reference and all 8 i18n packs; the
agent-pack gains the refresh-early/checkpoint discipline. 12 tests pin the
incident-derived families from forge #104 — including the real-time
contention race (single winner, no double-holder) and a measured 5s grace.

**RFC 052 PR4 — session binding (#101, RFC 038 §9).** A shift now binds
mechanically to ONE project. A centralized pre-write gate covers every relay
mutator: when the `M8SHIFT_ROOT`-designated relay and the script-local relay
BOTH exist and physically differ (`samefile` identity — symlinked same-root is
not ambiguous), every write refuses BEFORE any lock file exists — agentless
admin writes (`archive`, `cooldown`, `decisions --set`, `session report
--write`) always refuse under unresolved ambiguity; an actor-bearing command is
resolved only by that actor's own self-consistent binding. New penless
`bind <agent>` verb (`--show`/`--list` read-only, `--clear`) with a
deterministic target: under ambiguity it requires the closed
`--candidate env|script` selector — never silent env-wins — and a live-pen
guard refuses rebinding while the agent holds a live WORKING lock in any
candidate. Binding verification re-checks under the file lock (TOCTOU pin).
`init` refuses any non-empty `M8SHIFT_ROOT` resolving to a different physical
root than HERE — even if it does not exist yet — before creating anything. One
disclosure rule everywhere: a foreign root appears as basename + sha256-10,
never the full path. The agent-pack and anchor stanza gain the mechanical
bind-at-start rule (floor-marked). Zero-config behavior is byte-identical.

**RFC 052 PR3 — opt-in anchor hygiene (#101).** `doctor --hygiene-anchors`
re-scans the generated anchors (`CLAUDE.md`, `AGENTS.md`), which the default
path lint excludes because they legitimately carry the operator's OWN path. The
operator pins their own home root(s) in `M8SHIFT_HYGIENE_ALLOWED_ROOTS`
(comma-separated; comparison is case-insensitive so a case-variant of the pinned
root is not foreign); only FOREIGN home roots are flagged
(`hygiene.anchor_foreign_path` — advisory, never fails `--lint` unless
`M8SHIFT_SCRUB_ENFORCE=1`). Unset roots yield an info notice — ownership is
never guessed. Building the mode surfaced a real false positive: the generated
stanza documents `/Users/…` with a REAL UTF-8 ellipsis, which the placeholder
matcher only knew as three ASCII dots — now recognized (strengthens the C1 lint
too).

**RFC 052 PR2 — confidential denylist + scrub-check (#101).** `doctor --hygiene`
gains the operator-confidential denylist: identifiers listed OUT-OF-REPO
(`$M8SHIFT_DENYLIST`, else `~/.config/m8shift/denylist.txt`, else a silent no-op)
are flagged in tracked publishable files with a hashed label — never the term,
never the matched line (`--hygiene-verbose` shows terms locally for forensics).
Literal and `word:` modes, `allow:` exceptions, case-insensitive; a denylist hit
is a visible warning that never fails `--lint` unless `M8SHIFT_SCRUB_ENFORCE=1`.
New `scripts/scrub-check.py` scans git TIP (`git grep -F`, revisions before `--`)
and HISTORY (`git log --all --pickaxe-regex -i -S`, `refs/pull/*` opt-in, bounded)
via raw git argv — never a lossy optimizer; word semantics are post-filtered
in-process because `\b` in `git grep -E` scans silently CLEAN on BSD/macOS (an
empirically-caught false negative). New `hooks/pre-push` plus an advisory hygiene
stage in `hooks/pre-commit` (the pen guard is unchanged): findings are printed
and the operation proceeds unless `M8SHIFT_SCRUB_ENFORCE=1`; scanner errors fail
open, visibly. 15 tests pin redaction, precedence, argument order, parser drift,
hook layering, and fail-open.

**RFC 040 Phase 4 Slice 3 — Codex rate-limit adapter.** The disabled
`codex-ratelimits` scaffold now points to a shipped reference adapter
(`examples/usage-adapters/codex-ratelimits.py`) for the verified local Codex CLI
app-server protocol: newline-delimited JSON-RPC over `codex app-server --stdio`,
with `initialize` before `account/rateLimits/read`. The adapter maps only known
aggregate windows (`300` minutes → `session_5h`, `10080` minutes → `weekly`),
emits provider `usedPercent` as `used_ratio`, fails open to an empty official
fixture on every app-server/auth/schema error, and never emits account identity,
credits, plan type, limit names, raw responses, or stderr.

## v3.56.0 — 2026-07-08

Usage-provider adapters and project compartmentalization.

**RFC 040 Phase 4 — real default usage adapters (#100).** `usage init` now
scaffolds four disabled-by-default provider adapters (`claude-jsonl-scan`,
`claude-quota-keychain`, `codex-jsonl-scan`, `codex-ratelimits`) — inert until
explicitly enabled, no-clobber, identity-pinned. A reference Claude adapter
(`examples/usage-adapters/claude-oauth-usage.py`) reads the Claude Code OAuth
access token from the macOS Keychain (or an explicit file override) entirely in
memory and emits only an official usage fixture (`used_ratio`/`resets_at`) — never
the access/refresh token, account identity, or raw response body; non-macOS has no
plaintext credential default. It is fail-open on every error path — a malformed
response, broken stdout, arbitrary-precision overflow, or ANY exception yields an
empty official fixture, never a crash or a leak — and per-window resilient, so one
malformed window never discards good readings. A validation-and-contract test slice
pins the Phase-4 privacy / fail-open / disabled-by-default guarantees against
regression. Codex implemented, Claude reviewed: each slice cleared an adversarial
merge gate — empirical crash/leak matrices across stdout *and* stderr, plus mutation
testing that confirmed every contract test fails when its behavior is broken. The
`codex-ratelimits` adapter stays a disabled TODO scaffold until its RPC shape is
verified live.

**RFC 052 PR1 — project compartmentalization and data hygiene (#101).** A new
`doctor --hygiene` / `--hygiene-only` lint raw-reads tracked docs and examples for
real home-directory paths and flags them — placeholder-aware, so it never trips on
its own `<name>` / `.../` examples.
High-confidence hits gate under `--lint`; advisory hits are informational; it runs
without a relay. The agent-guidance floor gains a Compartmentalization rule: a fact
learned in one shift keeps its identity there, and cross-project reference is
deny-by-default. Claude drafted, Codex reviewed — a code review caught five real
defects (including a CLI crash on Python 3.14 from an argparse `%`-literal) that the
test suite missed; all were fixed before merge.

## v3.55.0 — 2026-07-08

Two features land together.

**#59 — token consumption in the RFC 051 usage line.** The core `status`/`watch`
usage advisory now shows raw consumption (`used <count>/<window>`, humanized
P/T/B/M/k, bounded window count) alongside or in place of the ratio — still
read-only, and byte-identical when no usage sidecar is present.

**#60 — `update` refreshes installed runner artifacts.** A new default `runner`
component refreshes already-installed `scripts/watch-status.sh` and
`examples/headless_runner.py` from a newer source, gated by `.m8shift/kit.json`
runner metadata (sha256-proven): it never creates absent runners, never blind-
overwrites edited/untracked ones, and refuses symlinked/non-regular targets or
targets whose real path escapes the project root. `doctor --source` emits
read-only `runner.stale` / `runner.manual_review_required` preflight findings;
`.m8shift/kit.json` gains a `runners[]` block, and `watch-status.sh` carries a
lockstep-tested `M8SHIFT_RUNNER_VERSION` marker. Implemented by Codex,
adversarially reviewed by Claude — five findings (HIGH target path-confinement,
MEDIUM non-UTF-8 backup crash, three LOW) were all fixed before merge.

## v3.54.0 — 2026-07-07

RFC 051 — **usage advisory in the core display** (#55; PR #57). A read-only
usage line now renders in the core `status` and `watch` output (and therefore in
`scripts/watch-status.sh`, which forwards to core `watch`), fed by the companion's
local usage sidecar. The core **computes nothing** — it echoes the last recorded
snapshot per agent — so the remaining-quota picture is visible where a human
watches without the core running an adapter, opening a socket, or spawning the
companion.

- **Companion (`m8shift-runtime.py`)**: `normalize_usage_snapshot` additively
  records `decision_window: {kind, resets_at}` (the window that drove
  `decision_ratio`, or `null` on the top-level/unknown case; ties resolve to the
  first max), so the core can echo the driving window and its reset time without
  recomputation.
- **Core (`m8shift.py`)**: a small stdlib-only reader (no companion import) reads
  `.m8shift/runtime/usage.jsonl` and renders a `── usage ──` block after the LOCK
  in `status`/`watch`, **absent entirely** (byte-identical) when there is no usable
  snapshot; `--json` gains an optional `usage` array (the `usage` key is omitted,
  not `[]`, when empty). Hardened per an adversarial design + implementation
  review: TOCTOU-safe open (`os.open` with `O_NOFOLLOW | O_NONBLOCK` + `fstat` on
  the fd — the opened fd is the proof, and a FIFO/device never blocks the read),
  bounded binary tail-read with partial-line discard, roster/`AGENT_RE`/consistent
  agent validation, terminal + JSON output sanitized (no ANSI/control escapes;
  never a non-finite number or an absurd percentage), strict staleness, and
  fail-open on every sidecar shape — nothing can crash `status`/`watch`.
- Reviewed at design and implementation (cross-review + solo adversarial hunts);
  each pass caught real bad-shape/security defects — non-string timestamps,
  huge-integer ratio overflow, and a sidecar-swap TOCTOU — all fixed before merge.

## v3.53.0 — 2026-07-05

RFC 040 Phase 3 — **real, opt-in usage adapters** (#47; PRs #49–#52). The Phase 2
framework (snapshot/guard/watch/wait/resume, cooldown, the pinned schemas, the
adapter manifest, the ledger) shipped in v3.48.0 with fixture/stub adapters; this
release makes the data real. Nothing in the core changes; all four slices are
opt-in and land in the `m8shift-runtime.py` companion.

- **Slice 1 — `used_ratio` schema extension.** One additive optional per-window
  field so a source that reports a percent/ratio (a remaining-quota endpoint) is
  never encoded into token fields. `decision_ratio` derives from `used_ratio`
  directly; a window carrying both a ratio and token counts is unit-mixed and
  dropped (never coerced); token-only snapshots stay byte-identical.
- **Slice 2 — `jsonl_scan` adapter + privacy gate.** A built-in, opt-in
  (default-off) scan of local agent-session JSONL that sums token integers into
  rolling windows — **aggregate-only** (never reads message content, never
  descends into content-bearing keys), bounded (files / candidates / bytes /
  mtime horizon / wall-clock deadline), version-tolerant (schema-drift
  diagnostic), symlink-safe. A spent/reporting source: `limit` is null, so it
  **never gates** (fail-open).
- **Slice 3 — gating remaining-quota.** A worked, argv-only operator OAuth example
  (`examples/usage-adapters/claude-oauth-usage.py`) that maps a remaining-percent
  endpoint to `used_ratio` — M8Shift never opens the socket, fail-open on any bad
  shape (missing/malformed credential, non-finite percent), credential never
  printed — plus a disabled `claude-quota` scaffold.
- **Slice 4 — operator budget bridge.** An opt-in `.m8shift/usage/budget.json`
  (absent by default; inactive `budget.example.json` scaffold) supplies a missing
  window `limit` so a spent-only scan can gate — **estimate only**: applied only
  to non-official snapshots, never overrides a real limit, never on a ratio
  window, downgrades provenance to `local_estimate`, fail-safe on a malformed
  budget (never invents a limit, never crashes), bounded caps.
- Adversarially reviewed at each slice (cross-review, then a solo 3-lens hunt for
  Slice 4 when the reviewer went offline); each pass caught real bad-shape defects
  (NaN/non-finite, content-recursion, unbounded scan, malformed credential,
  malformed-budget crash, ratio overflow) fixed before merge.

## v3.52.0 — 2026-07-05

Multi-OS core install (#24) + update/manifest fixes (#42, #43; PR #44).

- **Multi-OS core install (#24).** `install.sh` (macOS/Linux/WSL/Git Bash;
  bash requirement explicit) and `install.ps1` (native Windows) are kept in
  lockstep for the core components — verified by structural static parity
  tests and executed end-to-end where `pwsh` is available. Core install
  requires only Python 3.8+, a download path, write permission, and SHA-256
  support: no sudo, no PATH mutation, no daemon, no package-manager-only
  path; verification stays ON by default (`--no-verify` / `-NoVerify` is the
  explicit opt-out). Capability detection prints one honest line per optional
  helper (available / unavailable / skipped / installed / ask-will-prompt);
  optional helpers are POSIX-only where no safe Windows path exists and are
  skipped with an info line on Windows. **Opted-in helper failures no longer
  abort the core install**: they degrade to a prominent warning, init still
  runs, exit stays 0, and a summary lists the failed helpers. `--dry-run`
  prints the plan and prerequisites even without Python on the host.
- **Read-only post-install verification (#24).** `doctor --install` reports
  Python floor, script/core presence, checksum-manifest validity and drift,
  kit companion status, and optional helper states (6 `install.*` findings;
  optional-absent is `info`, core-unhealthy is distinguished from
  optional-accelerator-absent; no network, no repair, no mutation).
- **Manifest covers every shipped companion (#42).** `checksums.sha256`
  gains the missing `m8shift-e2e.py` entry, with a regression test that
  every shipped `m8shift-*.py` script is manifested — found live when the
  MUST-verify-when-present rule correctly refused to update the one
  unmanifested companion.
- **Mixed companion outcomes report `partial` (#43).** A companions update
  where some scripts refresh and some are refused now folds to `partial`
  (per-companion rows preserved, `--json` carries per-companion outcomes),
  and the **update-audit gate now sees per-companion writes**: a partial run
  that wrote files records its audit row and syncs the kit version (this
  gate miss predated #43 and also affected refused-fold runs).
- Release shipped solo (standing reviewer unavailable until 2026-07-07,
  operator-ordered continuation); review of record = 3-lens adversarial
  workflow with per-finding refutation (2 majors + 8 minors confirmed and
  fixed pre-merge, 1 finding refuted as pre-existing). Retro-review queued.

## v3.51.0 — 2026-07-05

Guidance batch — what agents must believe about evidence and shared state
(#22, #23, #25; PR #40).

- **Compression/raw-proof contract (#22).** New protocol-core `Raw-proof rule`:
  compressed or filtered views (digests, context packs, adapter output,
  summaries) are *orientation, not proof* — proof-bearing claims are verified
  against raw originals. Detailed `Evidence & workspace discipline` section in
  the protocol reference (proof-bearing content list: diffs, checksums,
  legal/verbatim text, logs-as-evidence; honest adapter roles consistent with
  RFC 023) and a `Compression is not proof` section in the agent pack. The
  protocol core stays within its hard 2000-proxy-token budget (1997 after the
  batch, was 1994): existing prose was trimmed and every safety-invariant
  substring is preserved by test.
- **Shared-checkout destructive-git guardrails, advisory only (#23).** New
  protocol-core `Shared-checkout rule`, pack section, and reference detail:
  destructive git operations (`reset --hard`, `checkout -f`, `clean -fd`,
  forced switches) require explicit human authorization in a shared checkout;
  a refused checkout is a signal, not an obstacle; inspect non-destructively
  first; prefer worktree isolation; never manipulate a peer's checkout outside
  relay coordination. The `doctor --source DIR` update preflight now also
  emits an **info-level** `workspace.dirty_worktree` advisory when the project
  checkout carries uncommitted changes (read-only
  `git --no-optional-locks status --porcelain`, 5 s timeout, fail-open;
  `doctor --lint` stays green; nothing is blocked or repaired).
- **Recurring memory-parasite audit (#25).** New agents-guide §11 contributor
  process: cadence (each minor release, or monthly), keep/mixed/parasite
  taxonomy, hard local-only rule for audit artifacts, scrub checklist,
  symptom → masked-gap → issue conversion template, and the 2026-07-04
  audit precedent (issues #17–#25) cited by date and numbers only. No core
  behavior, no runtime machinery, nothing generated by `init`.

## v3.50.1 — 2026-07-04

Hotfix — `update` baseline authority (found dogfooding v3.50.0 against the live relay).

- A long-lived relay keeps its ORIGINAL `M8SHIFT.md` banner across dogfood promotions
  (the live relay still said v3.14.0 from the pre-rename era) while its installed
  script is current: the baseline chain let the stale banner VETO a supported target.
  The baseline is now the BEST provable version among kit.json, the banner, and the
  target script — refusal requires every parseable authority below the 3.41 floor.
- Regressions: stale-banner+current-script accepted with the relay byte-identical;
  banner+script both pre-3.41 still refused with the manual-upgrade message.

Lockstep bump to `3.50.1`.

## v3.50.0 — 2026-07-04

RFC 048 PR B complete — source-driven local update for adopted projects
(closes #19).

- **First-hop update model**: run the new source copy, not the old target copy:
  `python3 SOURCE/m8shift.py update --target TARGET --source SOURCE`. Every write
  is rebased onto the target; the source directory remains untouched.
- **Safe component order**: protocol, agent pack, anchors, installed companions, and
  core are processed in that order, with the core copied last. `M8SHIFT.md` relay
  state is never copied from the source and stays byte-identical during update.
- **Safety gates**: baseline v3.41+, downgrade refusal by default, checksum
  verification when the source ships `checksums.sha256`, source/driver version
  split refusal, target file-lock serialization, and `WORKING_*` refusal unless
  explicitly overridden with `--allow-working`.
- **Generated-file repair and audit**: `--force-generated` repairs only generated
  pack/stanza marker blocks after backup; update writes bounded audit rows to
  `.m8shift/update-audit.jsonl`; `doctor --source` reports update recommendations
  and unreadable source paths.

Lockstep bump to `3.50.0`. Full pytest suite: 547 passed, 382 subtests passed.

## v3.49.0 — 2026-07-04

RFC 048 PR A complete — adoption discipline pack and adoption-health diagnostics
(closes #18 and #20).

- **Generated agent pack**: `init` now creates `M8SHIFT.agent-pack.md`, a concise
  first-read discipline document for agents. It carries the operational floor:
  claim-before-write, shell/runtime waiting, no parking, unread-turn handling,
  keep-listening / idle-is-not-done, prompt-security boundaries, stale-lock recovery,
  companion boundaries, and the incident #99 delivery discipline.
- **Compact anchor floor**: `CLAUDE.md` / `AGENTS.md` stanzas now point to the pack
  and protocol while keeping the mandatory inline guardrails. The stanza is measured
  and tested at 1615 bytes, over the soft 1536-byte target only because the
  safety floor is mandatory; the hard ceiling remains 2048 bytes.
- **Adoption doctor**: `doctor` reports pack presence, integrity and staleness plus
  stanza-floor health using the existing anchor finding IDs where appropriate.
  Pre-3.49 projects receive informational adoption findings so `doctor --lint`
  remains green until `init` delivers the new surface.
- **Safe generated-file repair**: `init --force-generated` rebuilds only a corrupted
  generated pack block, backs the previous file up as `*.m8shift.bak`, and never
  resets the relay state.

Lockstep bump to `3.49.0`. Full pytest suite: 526 passed, 374 subtests passed.

## v3.48.0 — 2026-07-04

RFC 040 Phase 2 complete — AI session usage monitoring (advisory, cooperative).

- **Read-only surface (PR A)**: `usage init` / `adapters list|check` / `snapshot` /
  `status` — argv-only bounded adapters (identity pin fail-closed, stdout hard-capped by
  a killing bounded reader, zero network by M8Shift), normalization to
  `m8shift.usage.snapshot.v1`, append-only `usage.jsonl` ledger, always-redacted
  excerpts, advisory exits, unknown = fail-open (never a pause).
- **Guard family (PR B)**: `usage guard [--apply]` / `watch` / `wait` / `resume` —
  holds placed ONLY through the core `cooldown` argv call with the snapshot's
  `resets_at` (never an invented reset); own-`WORKING` = advisory hold + exit 12, no
  interrupt; peer-`WORKING` = advice only, nothing written; an ok watch tick never
  resumes; `usage resume` is the explicit-only road back, gated on verdict exactly
  `ok`. `m8shift.usage.hold.v1` sidecar; audit via `usage.hold_*` events.
- Motivated by two real worker losses to provider session limits during dogfooding on
  2026-07-04: an unattended lane can now check its budget before waking and hold
  through a quota window instead of dying silently.

Lockstep bump to `3.48.0`. Full pytest suite: 506 passed.

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
