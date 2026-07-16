# v3.61.0 release notes

## Version

**v3.61.0 (Révision).** Backwards-compatible feature and hardening release: an
exact-identity fleet manager (RFC 072), a vendor-neutral agent CLI adapter
registry and detached durable fleet recovery (RFC 073 slices 1–2), and
per-agent usage throttles, plus provider-pinned models and dashboard/checksum/
liveness follow-ups. New command families are additive; legacy v1 usage-hold
recovery remains supported. No relay-format or CLI compatibility break.

## Highlights

### Per-agent usage throttles (#88)

- A `limit_hit` gates only the affected agent's claim/next/wait and
  managed-listener launch; peers keep their normal relay rights and new applies
  never set global `PAUSED` — the global-pause misfire is fixed.
- Independent v2 hold records preserve concurrent limits; explicit
  `usage resume --agent` clears only a freshly recovered target (v1
  singleton/global-cooldown recovery still supported).
- Hold deadlines come from the exact normalized `decision_window` that
  triggered the verdict, ratio-native weekly windows included; invalid or
  unrelated reset fallbacks are refused.

### Exact-identity fleet orchestration (RFC 072, #85)

- A lane fails closed until its git-ignored per-agent identity artifact loads
  at developer/system precedence (O1); fleet specs select a curated provider
  template plus an explicit model — never arbitrary argv or an inherited global
  CLI model (O2).
- `fleet apply --by HOLDER` is idempotent and holder-attributed, delegating
  every membership addition to core `roster add` (O3); stopping a lane keeps
  roster membership intact — offline is an observed runtime condition, not a
  relay mutation (O4).
- Immutable jobs carry explicit done criteria and shell-free verification
  recipes; provider exit alone is never completion (O5). Only the
  relay-designated integrator assigns, merges, hands off, and drops — at most
  two active producer worktrees, never the shared target (O6).

### Vendor-neutral adapter registry (RFC 073 slice 1, #65/#66)

- `m8shift.agent-cli-adapter.v1` (`launch_argv`/`stop`/`resume`/`health`)
  dispatches through a provider-keyed registry; managed Codex and Claude
  launch compilation migrated behind adapters with byte-identical fixtures.
- A registered Gemini validated stub proves a third provider joins without a
  core or generic-launcher change; its live flags and resume stay fail-closed
  pending probe evidence.

### Detached durable fleet recovery (RFC 073 slice 2, #65)

- `fleet supervise --detach` installs one control plane through
  launchd/user-systemd/Windows-service definitions when available, with an
  honest local process-group-detached fallback otherwise.
- Crash-consistent `.m8shift/runtime/fleet/` store (control, lanes, jobs,
  attempts, opaque sessions, events) with fsync + atomic replace; startup
  reconciles by PID start identity.
- Liveness hardening — four HIGH findings resolved through multi-pass
  adversarial review, including cross-model review: a complete four-way
  partition (adopt an exact live survivor / restart a missing desired-running
  lane once / defer-unverified on a transient probe failure / fail closed to
  `needs_reconciliation` on a live pid with an empty persisted ref),
  SIGTERM-clean shutdown persisting `state=stopped`, and stale-pid takeover
  after a reboot instead of crash-looping under a native KeepAlive unit.

### Also shipped

- Provider-pinned agent models (#86): managed rows require an explicit valid
  model before headless launch; the pin rides the immutable runner plan into
  `M8SHIFT_AGENT_MODEL`.
- Top-owned incremental status fold (#79), positional CLI help + a site-ready
  command reference (#83), automatic staged-checksum refresh in the pre-commit
  hook (#51), and claim-on-pickup liveness (#47).

### Deferred

- The remaining slice-2c hardening items and RFC 073 slices 3–4 (live Gemini +
  probed native resume; the #59 routing-matrix extension) are accepted, not
  shipped.

## Upgrade and verification

- No migration; no removed or renamed command/flag. Adopters refresh with
  `python3 m8shift.py update` driven by `scripts/m8shift-self-update.py`
  (dry-run by default; snapshot + rollback on failure).
- Verify: the post-#88 `usage` surface exists (`usage resume --agent`),
  `doctor` reports green, and the full suite passes —
  `python3 -m unittest tests.test_m8shift` → 900 tests, 2 skips.
