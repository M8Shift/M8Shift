# v3.60.0 release notes

## Version

**v3.60.0 (Révision).** Backwards-compatible feature and hardening release: new
operational skills, init capability profiles, a versioned status snapshot with a
read-only dashboard, a generation-safe adopter upgrade path, a faster (byte-
identical) scrub, honest usage-window display, and CI/supply-chain hardening. No
relay-format or CLI compatibility break.

## Highlights

### Tooling & workflow
- Four advisory skills (`release-manager`, `adversarial-verifier`, `ci-triage`,
  `leak-warden`); compartmentalization invariants live as guide rules a skill
  cannot relax.
- `init --profile bare|headless|ops|full` + machine-readable `bootstrap.json`
  (argv actions, operator/agent approval, never executed by init).

### Observability
- Status snapshot `m8shift.status/1` (additive; legacy flat keys frozen) and the
  read-only `m8shift-top` dashboard (alt-screen, guaranteed restore, non-TTY
  fallback to `watch`).
- Usage line shows `5h N/A (Reset …)` for a window an agent previously reported
  but the provider no longer returns — absence is explicit, never invented.

### Adopter upgrade (generation-safe)
- `install.sh --upgrade` / `install.ps1 -Upgrade`: stage + checksum-verify the
  full engine set, then delegate to `m8shift.py update`.
- `update` refuses a cross-Generation (major) change unless
  `--allow-generation-change`, keeping `M8SHIFT.md`/relay state byte-identical.
- Honest boundary: the retro-compat guarantee is the Generation gate; predictable
  failures (checksum, version, WORKING relay) abort before any write. `update` is
  not set-atomic against a mid-pass per-companion refusal — that is reported as
  `partial`, not rolled back. True set-atomic rollback is a possible follow-up.

### Performance & hardening
- Scrub history walks parallelized (bounded stdlib pool, denylist-ordered,
  byte-identical output; ~2–3× on the audit path).
- Hash-pinned CI installs + Dependabot pip; pre-push also verifies the checksum
  manifest; behavioral mutation-gated pre-release contracts.

## Upgrade and verification

- No migration; no removed or renamed command/flag.
- Regenerate `checksums.sha256`; update lockstep version references; run the
  focused security/runtime/usage suites and the full quality gate on the 3.8
  floor and a current interpreter; verify the release commit and tag before
  pushing either remote.
