# RFC — Headless command templates

**Status:** design finalized (this RFC) · implementation tracked in #47 · **Builds on:** [014-rfc-provider-management.md](014-rfc-provider-management.md) (provider argv rendering) + [020-rfc-headless-runner-hardening.md](020-rfc-headless-runner-hardening.md) (hardened runner, immutable run plan, post-run LOCK verification) · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define safe command templates for headless agent runs such as `codex exec`, `claude -p`, and other
cooperative CLIs.

Templates should produce explicit argv arrays, stable cwd, prompt hash, agent identity, run id, and
post-run relay validation. They may build on provider rendering but must keep secrets and shell
expansion out of M8Shift.

## Design (finalized)

M8Shift already has the two pieces a headless run needs: **provider argv rendering** (RFC 014,
`.m8shift/providers.json` + `render`, placeholder substitution into an argv array — never a shell
string) and the **hardened runner** (RFC 020, `examples/headless_runner.py` with an immutable
`m8shift.headless.run_plan.v1`, timeout/kill-grace, run ledger, post-run `LOCK` verification). RFC
028 is therefore **a curation + specification layer over those**, **not a new launcher**: it pins the
mandatory run-plan shape, ships a few **curated example templates** for common cooperative CLIs, and
fixes the minimum post-run validation. M8Shift never ships a provider SDK, never manages keys, and
never routes models here.

### Run-plan mandatory fields

A run plan (extending `m8shift.headless.run_plan.v1`) must carry:

- **`agent`** — the roster identity the run acts as.
- **`argv`** — the fully resolved command as an **array** (no shell string); `argv[0]` is a bare
  allowlisted program resolved through `PATH` (or an absolute path).
- **`cwd`** — a stable, explicit working directory.
- **`run_id`** — unique id (`M8SHIFT_RUN_ID`) for the ledger + idempotency.
- **`prompt_hash`** — hash of the exact prompt handed to the agent, for audit and idempotency (the
  prompt text itself is not required to be stored).
- **`env_allowlist`** — the explicit set of env vars passed to the child (e.g. `M8SHIFT_ROOT`,
  `M8SHIFT_AGENT`, `M8SHIFT_RUN_ID`); everything else is dropped. No secrets are injected by M8Shift.
- **`timeout` / `kill_grace`** — bounded runtime (RFC 020).
- **`expected_transition`** — the relay state the run is expected to leave (used by post-run
  validation), or `none` for a read-only run.

### Where templates live

Templates reuse **`.m8shift/providers.json`** (RFC 014) — no new store. A provider entry already
holds the argv template with `$M8SHIFT_PROMPT` / `$M8SHIFT_AGENT` / `$M8SHIFT_RUN_ID` markers
substituted as literal argv items. RFC 028 ships **curated example entries** for cooperative CLIs
(e.g. `codex exec`, `claude -p`) as documentation/opt-in samples, not as bundled launchers. The run
plan is `provider argv` + runtime context (prompt, agent, run_id) resolved by the runner.

### Platform differences without shell strings

A provider entry MAY carry per-platform argv **arrays** (an optional `argv_by_platform` map, e.g.
`{ "default": [...], "win32": [...] }`); the runner selects by `sys.platform` and otherwise resolves
`argv[0]` via `shutil.which`. Platform variation is expressed as **distinct argv arrays**, never as a
shell string or an interpolated conditional.

### Minimum post-run validation (before reporting success)

Reusing RFC 020, a run is reported **success only if all hold**: (1) the process exited `0` within
`timeout` (else timeout/kill-grace applies and it is a failure); (2) the run's `LOCK` was **not
force-stolen** mid-run (post-run `LOCK` verification); (3) the `expected_transition` actually occurred
in the relay (or the run declared `none`); (4) the run ledger recorded the lifecycle events. Anything
short of all four is reported as **failed/partial**, never a false success.

## Resolved subquestions

1. **Which fields are mandatory in a run plan?** The eight above (`agent`, `argv`, `cwd`, `run_id`,
   `prompt_hash`, `env_allowlist`, `timeout`/`kill_grace`, `expected_transition`).
2. **Where do templates live?** In `.m8shift/providers.json` (RFC 014) — reused, not a new file;
   RFC 028 adds only curated **example** entries and the run-plan spec.
3. **How are platform differences represented without shell strings?** Distinct per-platform argv
   **arrays** selected by `sys.platform`, with `argv[0]` resolved via `PATH`; never a shell string.
4. **Minimum post-run validation?** Exit 0 within timeout **and** un-stolen `LOCK` **and** the
   expected transition **and** ledger events — all four, or it is not a success.

## Non-goals

- **No provider SDK, no API-key management, no model routing** in the core (routing is RFC 039).
- **No new launcher.** RFC 028 curates + specifies over RFC 014/020; it does not add a second
  headless execution path.
- **No shell strings, no secret injection.** argv arrays only; env is an explicit allowlist.
