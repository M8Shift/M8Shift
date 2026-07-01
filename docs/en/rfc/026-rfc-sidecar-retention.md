# RFC — Runtime sidecar retention and archive policy

**Status:** implemented in v3.29.0; path hardening shipped in v3.34.2 (#73) · **Source:** deferred from
[010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define retention for `.m8shift/runtime/` sidecars: presence snapshots, progress JSONL, inbox JSONL,
run ledgers, idempotency ledgers, approvals, reports, and related companion files.

Sidecars provide observability but can grow forever in long-running projects. Retention needs to keep
recent troubleshooting data without making runtime files a hidden database.

## Shipped baseline

M8Shift ships a narrow fixed-count baseline:

```bash
python3 m8shift-runtime.py retention prune --keep 1000
```

The command:

- scans runtime JSONL ledgers under `.m8shift/runtime/`, including `runs.jsonl`,
  `progress.jsonl`, `idempotency.jsonl`, `approvals.jsonl`, and `inbox/*.jsonl`;
- keeps the newest `N` rows in each ledger;
- archives older rows under `.m8shift/runtime/archive/` by default;
- supports `--no-archive` for explicit discard;
- reports malformed JSONL as a diagnostic and does not mutate that ledger;
- never edits `M8SHIFT.md`, the core turn log, or the `LOCK`.

This is intentionally not a full policy engine. It is a manual/operator command
for bounded local sidecars.

## Policy design (implemented)

The baseline stays as the manual, always-available command. On top of it, RFC 026 adds an **opt-in,
operator-owned policy** that a new `retention apply` evaluates. The policy is advisory, stdlib-only,
**no daemon** (a one-shot command the operator runs, or wires into their own scheduler / the runtime
`watch` loop), no network, and it **never** touches the core.

### Manifest — `.m8shift/runtime/retention.json` (gitignored, host-local)

Schema `m8shift.runtime.retention.v1`. Ships as an example and is **disabled by default**
(`enabled: false`), so nothing prunes automatically until the operator opts in.

```json
{
  "schema": "m8shift.runtime.retention.v1",
  "enabled": false,
  "default": {"strategy": "fixed-count", "keep": 1000, "archive": true},
  "ledgers": {
    "runs.jsonl":        {"strategy": "fixed-count", "keep": 2000, "archive": true},
    "progress.jsonl":    {"strategy": "age",      "max_age_days": 14, "archive": true},
    "idempotency.jsonl": {"strategy": "combined", "keep": 500, "max_age_days": 30, "archive": false},
    "inbox/*.jsonl":     {"strategy": "fixed-count", "keep": 200, "archive": true}
  }
}
```

### Strategies

- **`fixed-count`** — keep the newest `keep` rows; prune the rest (the shipped baseline, now
  expressible per-ledger).
- **`age`** — keep rows whose timestamp is newer than `max_age_days`; prune older. A row whose
  timestamp is missing or unparseable is **never pruned by age** (fail-safe: never delete what you
  cannot date) and is reported.
- **`combined`** — keep a row if it is **either** within the newest `keep` rows **or** newer than
  `max_age_days` (a union — the safe interpretation; never over-prunes). At least the newest `keep`
  always survive.

### Command surface (additions; baseline unchanged)

```bash
python3 m8shift-runtime.py retention prune --keep N               # shipped baseline (unchanged)
python3 m8shift-runtime.py retention apply [--dry-run] [--json]   # evaluate the manifest policy
python3 m8shift-runtime.py retention policy show [--json]         # print the effective policy
```

- `retention apply` reads the manifest; if it is absent or `enabled:false`, it does nothing and says
  so (the baseline manual command remains the way to prune without a policy).
- `--dry-run` prints what each ledger would prune/archive, changing nothing.
- Malformed JSONL in a ledger is reported and that ledger is left untouched (baseline behavior).

### Archive + audit

Archiving keeps pruned rows under `.m8shift/runtime/archive/` (baseline). `retention apply` also
appends one compact audit row per pruned ledger to `.m8shift/runtime/archive/index.jsonl`
(`{ledger, strategy, pruned, kept, oldest_ts, newest_ts, archived_at}`) — this is the "compact
summary before deleting raw rows." `--no-archive` (baseline flag) discards instead of archiving.

Since v3.34.2 (#73), retention policy ledger patterns normalize `\` to `/` before
parent-segment checks, so `..\\...` cannot bypass the unsafe-pattern guard.
Runtime JSONL append paths also refuse symlink redirection before archive and
archive-index writes; when the platform exposes `O_NOFOLLOW`, append opens use it
as an additional final-component guard.

## Resolved subquestions

- **Which files auto-prunable vs explicit?** Only the `.m8shift/runtime/` JSONL ledgers named in the
  manifest, and only when `enabled:true` **and** the operator runs `retention apply`. Nothing prunes
  on its own.
- **Preserve a compact summary before deleting?** Yes — the archive keeps the raw rows and
  `archive/index.jsonl` records a per-apply summary.
- **Interaction with session reports and project memory?** None — retention touches only runtime
  sidecars. Session reports, project memory, and `M8SHIFT.md` are out of scope and never pruned.
- **Disabled by default?** Yes — `enabled:false` ships; the policy engine is strictly opt-in.
- **Symlinked archive/ledger path?** Refused. Retention reports a hard failure
  instead of following a symlink to a file outside `.m8shift/runtime/`.

## Non-goals

- **Never** prune `M8SHIFT.md`, the core turn log, the `LOCK`, session reports, or project memory
  through runtime retention. Core archive remains the only mechanism for the relay journal.
- **No daemon / no background pruning.** `retention apply` is a one-shot operator command; M8Shift
  never spawns a retention process, and it never requires the network.
