# RFC 034 — Companion Adapter Interface and native context companion

- **Status:** Phase 1 + Phase 2 implemented; RTK default-if-pinned shipped in v3.34.0 (#76); corrupt-manifest auto fallback shipped in v3.34.1
- **Date:** 2026-06-30
- **Scope:** optional companion interface for context tools around M8Shift, with a first
  stdlib-only native context companion.
- **Builds on:** [014-rfc-provider-management.md](014-rfc-provider-management.md),
  [018-rfc-agent-runtime-architecture.md](018-rfc-agent-runtime-architecture.md),
  [023-rfc-agent-token-footprint.md](023-rfc-agent-token-footprint.md),
  [024-rfc-doctor-split.md](024-rfc-doctor-split.md),
  [025-rfc-status-runtime.md](025-rfc-status-runtime.md),
  [028-rfc-headless-command-templates.md](028-rfc-headless-command-templates.md),
  [033-rfc-context-economy.md](033-rfc-context-economy.md).

## 1. Decision

M8Shift adopts a **Companion Adapter Interface** for optional tooling around the
relay, without turning `m8shift.py` into a plugin host.

The first implementation is deliberately narrow:

```bash
python3 m8shift-context.py init
python3 m8shift-context.py pack --profile reviewer --write
python3 m8shift-context.py benchmark --real-tokens measured.json --require-real-tokens
python3 m8shift-context.py doctor
```

Phase 1 ships only a native context companion:

- referenced context packs;
- receipts;
- metrics;
- a benchmark harness with small / medium / large fixtures;
- no external dependencies;
- no adapter subprocess runner.

External adapter execution is deferred to Phase 2.

## 2. Core invariant

`m8shift.py` remains the stdlib-only, passive, repository-local coordination relay.
It owns `LOCK`, claimability, turn order, the one-pen mutex, TTL, and the append-only
turn journal.

`m8shift.py` must not:

- import adapter code;
- load Python plugins from `.m8shift/`;
- call provider SDKs;
- call compression libraries;
- call network services;
- require tokenizer, vector database, ONNX, Node, Rust, MCP, or model dependencies;
- let adapter configuration alter legal `claim`, `append`, `release`, `pause`,
  `resume`, or `done` transitions;
- let companions write `M8SHIFT.md` directly.

Companions may prepare, compress, observe, report, benchmark, and advise. They never
become a second routing authority.

## 3. Problem

RFC 033 defines the context economy: agents should exchange compact contracts, not
whole conversations. That policy needs tooling, otherwise agents fall back to copying
logs, status output, old turns, and local exploration into the next handoff.

The unsafe failure modes are predictable:

- arbitrary plugin imports inside the core;
- shell strings and interpolation in tool execution;
- compressed summaries treated as evidence;
- secrets leaked into prompts or versioned files;
- adapter metadata influencing core lock legality;
- token savings claimed from proxy byte counts only, without measuring real model
  tokens before / after.

This RFC creates a boundary: the center stays boring; the edges can become useful.

## 4. Phase split

| Phase | Scope | Status |
|---|---|---|
| 1 | Native `m8shift-context.py`: pack, receipts, metrics, benchmark, doctor | implemented |
| 2 | External adapter subprocess runner: manifest validation, allowlisted argv execution, timeout, stdout/stderr caps, env allowlist, fallback policy | shipped for `shell_output_filter` adapters in `m8shift-context.py` |
| 3 | Optional example manifests for Headroom-style, RTK-style, and repo-packer tools | RTK shell-output manifest shipped; context packs default to pinned RTK when present |
| 4 | Agent-guide/runtime documentation integration, including the condensed waiting-cost rule from RFC 033 | RTK agent-guide rule shipped; broader runtime docs ongoing |

Phase 1 must not implement all adapter types. It establishes the data model and
measures whether native context packing actually reduces context.

## 5. Context companion

`m8shift-context.py` owns advisory context artifacts under:

```text
.m8shift/context/
├── profiles/
├── packs/
├── receipts/
├── metrics.jsonl
└── benchmarks.jsonl
```

Generated packs and receipts are operational views. They are not source-of-truth
evidence. Verification uses originals: source files, original logs, test output,
diffs, and retrieved originals.

## 6. Pack contract

A native context pack must include source references and preserve the relay handoff
contract fields verbatim:

- `ask`;
- `done`;
- `decision` / `decisions`;
- blockers and waiver fields when present;
- file paths.

The pack may truncate noisy supporting material, but it must not truncate the
handoff fields that define the work contract.

## 7. Metrics contract

Each written pack records a metrics row:

```json
{
  "schema": "m8shift.context.metrics.v1",
  "timestamp_utc": "2026-06-30T09:15:00Z",
  "pack_id": "ctx_20260630T091500Z_reviewer",
  "profile": "reviewer",
  "input_bytes": 84231,
  "output_bytes": 23111,
  "estimated_proxy_tokens_before": 21057,
  "estimated_proxy_tokens_after": 5778,
  "line_count_before": 1804,
  "line_count_after": 422,
  "compression_ratio": 0.274,
  "required_fields_preserved": true,
  "real_tokens_before": null,
  "real_tokens_after": null,
  "real_token_reduction": null,
  "warnings": []
}
```

M8Shift remains tokenizer-less. `estimated_proxy_tokens_*` is only `bytes / 4`.
Real token counts must be supplied by an external measurement step and stored in the
benchmark results when the team wants to decide whether the feature really ships.

## 8. Benchmark-first rule

The benchmark harness is the first deliverable of Phase 1, not a later polish task.
It compares **WITHOUT** native packing against **WITH** native packing across three
fixtures:

- small;
- medium;
- large.

It records proxy metrics automatically. For a shipping decision, it also requires
real measured token counts:

```bash
python3 m8shift-context.py benchmark \
  --real-tokens measured-tokens.json \
  --require-real-tokens
```

Expected `measured-tokens.json` shape:

```json
{
  "small": {"without": 500, "with": 200},
  "medium": {"without": 5000, "with": 1000},
  "large": {"without": 20000, "with": 2500}
}
```

The ship gate passes only when every fixture has:

- real token counts present;
- `with < without` for real tokens;
- `with < without` for proxy tokens.

If measured reduction is not real, the feature is reconsidered instead of shipped
on byte-count optimism.

## 9. Adapter interface — Phase 2 shape

External adapters were not executed in Phase 1. Phase 2 starts with a narrow
`shell_output_filter` runner in `m8shift-context.py`; adapter manifests use JSON
and a process boundary:

```json
{
  "schema": "m8shift.adapter.v1",
  "name": "native-context",
  "type": "context_transform",
  "version": "0.1.0",
  "authority": "advisory",
  "command": ["python3", "m8shift-context.py", "internal-transform", "--stdin-json"],
  "capabilities": ["compress_context", "preserve_references", "estimate_size"],
  "input_schema": "m8shift.context.request.v1",
  "output_schema": "m8shift.context.response.v1",
  "mutates_core": false,
  "mutates_repo": false,
  "requires_env": [],
  "timeout_seconds": 30,
  "max_stdout_bytes": 1048576,
  "failure_policy": "fallback_original"
}
```

Phase 2 constraints:

- `command` is an argv array, never a shell string;
- `command[0]` is a bare allowlisted program name resolved through `PATH`;
- the resolved executable must match the manifest's trusted executable identity
  (`program`, resolved absolute path, and SHA-256), so renamed copies, wrappers,
  symlink/path hijacks, and relay binaries disguised as adapter tools fail closed;
- stdin/stdout are versioned JSON for JSON-native adapters; `shell_output_filter`
  adapters may consume/produce text, but the M8Shift runner wraps the result in a
  versioned JSON response;
- runtime and output size are bounded;
- environment variables are allowlisted;
- stderr is diagnostic only;
- invalid JSON is adapter failure;
- adapter failure follows the declared fallback policy;
- adapters do not mutate core relay files directly.

The shipped RTK manifest is advisory and operator-installed. Since v3.34.0 (#76),
`m8shift-context.py pack` defaults to the RTK `shell_output_filter` adapter only
when `rtk` is present **and** the manifest is identity-pinned
(`trusted_executable.path` + SHA-256). If RTK is absent, unpinned, or invalid, the
pack silently degrades to the native stdlib path. Operators can opt out explicitly
with `pack --adapter native` / `--no-rtk`.

Since v3.34.1, automatic adapter selection also treats a corrupt, unreadable, or
non-object on-disk RTK manifest as a diagnostic error finding and degrades to the
native pack path. Explicit operator selection remains fail-closed: `pack
--adapter rtk-shell-output` aborts on corrupt or invalid manifests.

The RTK manifest recommends `err`, `test`, `log`, and `ls` for noisy shell output,
and forbids `git-diff` for code review because Round 2 measurements showed it
drops hunks. M8Shift invokes RTK only as a local argv subprocess. It does not call
remote RTK services; install/setup runs `rtk telemetry disable` when RTK is present
or installed, and `doctor --json` surfaces RTK presence, pin status, and telemetry
state.

## 10. Authority levels

| Authority | Meaning | Examples |
|---|---|---|
| `read_only` | Reads project/sidecar state and returns observations. | status renderer, IDE panel |
| `advisory` | Produces packs, compressed views, warnings, reports, or metrics. | context packer, shell-output filter |
| `host_action` | Starts or controls a host-side process but does not directly mutate core relay files. | notifier, approval prompt |
| `mutating_m8shift_command` | Calls explicit M8Shift CLI commands. | future constrained MCP mutating tools |

`mutating_m8shift_command` is exceptional and must use the public CLI, never direct
file writes.

## 11. Deferred adapter types

The vocabulary is reserved for Phase 2+, not implemented in Phase 1:

- `provider`;
- `context_collector`;
- `repo_packer`;
- `context_transform`;
- `shell_output_filter`;
- `reporter`;
- `notifier`;
- `mcp_surface`;
- `doctor_check`;
- `metrics_sink`.

This avoids building ten half-interfaces before the native baseline has measured
value.

## 12. Doctor split

`m8shift.py doctor` remains the CI-safe core diagnostic surface.

`m8shift-context.py doctor` owns context-companion diagnostics:

- missing or malformed profiles;
- malformed receipts;
- missing receipt references;
- malformed metrics rows;
- proxy-only metrics warnings;
- later: adapter manifest validation and argv safety checks.

The core doctor may mention removable sidecar hygiene, but it must not make context
sidecars routing authority.

## 13. Security rules

Companions and future adapters must:

1. use argv arrays, not shell strings;
2. avoid shell expression evaluation;
3. keep secrets out of prompts and versioned files;
4. use environment allowlists;
5. use bounded timeouts and output caps;
6. capture stderr as diagnostics, not prompt material;
7. never mutate `LOCK` or `M8SHIFT.md` directly;
8. never decide claimability from adapter metadata;
9. never auto-force a fresh holder;
10. never auto-install dependencies from the companion; installers may offer optional dependencies only with explicit operator consent;
11. treat compressed or compacted context as an operational view, not evidence.

## 14. Acceptance criteria

Phase 1 is acceptable when:

- `m8shift.py` behavior and semantics are unchanged;
- `m8shift.py` does not import or execute context adapters;
- `m8shift-context.py` has no external dependency;
- `m8shift-context.py init` writes profile scaffolding;
- `m8shift-context.py pack --write` writes a referenced pack, receipt, and metrics;
- packs preserve `ask`, `done`, and `decision` fields verbatim;
- `m8shift-context.py benchmark` compares small / medium / large fixtures;
- the benchmark distinguishes proxy estimates from real token counts;
- `--require-real-tokens` fails unless real measured counts show reduction;
- `m8shift-context.py doctor --json` reports context-sidecar findings;
- RTK absent or unpinned degrades to native packing without error;
- RTK present and identity-pinned is selected by default for supported shell-output sources;
- operators can opt out with `pack --adapter native` / `--no-rtk`;
- setup attempts `rtk telemetry disable` when RTK is present;
- doctor surfaces RTK presence, pin status, and telemetry state;
- tests cover init/doctor, pack preservation, receipts/metrics, and benchmark gates;
- the full test suite remains green.

## 15. Non-goals

- No plugin marketplace.
- No Python import plugins in `m8shift.py`.
- No dynamic dependency installation.
- No remote adapter registry.
- No hosted control plane requirement.
- No provider SDK in the core.
- No vector database requirement.
- No mandatory tokenizer.
- No automatic model routing.
- No automatic agent selection.
- No change to the core `LOCK` format.
- No change to `claim`, `append`, `release`, `pause`, `resume`, `done`, or `next` legality.
- No compressed context as source-of-truth evidence.
