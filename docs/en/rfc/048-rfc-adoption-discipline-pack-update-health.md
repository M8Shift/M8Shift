# RFC 048 — Adoption discipline pack, local update, and adoption-health diagnostics

- Status: draft
- Date: 2026-07-04
- Target versions: v3.49.0 for PR A (#18 + #20), v3.50.0 for PR B (#19)
- Tracks: GitHub #18, #19, #20
- Builds on: [RFC 010 Runtime patterns](010-rfc-runtime-patterns.md), [RFC 018 Agent runtime architecture](018-rfc-agent-runtime-architecture.md), [RFC 044 Complete init companion install](044-rfc-complete-init-companion-install.md), [RFC 045 Module reference examples](045-rfc-module-reference-examples.md), [RFC 046 Interactive/headless modes and runner install](046-rfc-interactive-headless-runner-install.md)
- Related: [RFC 023 Agent token footprint](023-rfc-agent-token-footprint.md), [RFC 047 Headless liveness](047-rfc-headless-liveness-runner-listener.md)

## Summary

M8Shift adoption is an operational contract: a fresh agent must load a small
anchor, learn the minimum safety rules, find the shared protocol, and then obey
the claim → work → append/done loop. Today that contract can drift across anchors,
generated protocol files, copied scripts, and human prompts.

RFC 048 defines one coherent adoption surface:

1. **#18 init-delivered discipline pack** — `init` generates a versioned
   `M8SHIFT.agent-pack.md`. Anchor stanzas stay compact, but they retain a
   normative inline safety floor so an agent that does not follow links is still
   not allowed to write blindly.
2. **#20 adoption-health diagnostics** — `doctor` reports whether that adoption
   surface is usable, without duplicating existing doctor findings or repairing
   files automatically.
3. **#19 local update command** — a trusted **source copy** of `m8shift.py` updates
   a **target project** through `update --target PROJECT_DIR --source SOURCE_DIR`,
   so projects created before the `update` subcommand can still be upgraded.

The key correction versus the first draft is the first-hop model: an old target
script cannot emit new embedded protocol/pack content and may not even know the
`update` command. Therefore the update driver is the **new source script** and all
generated writes are explicitly rebased onto the target project.

## Goals

- Preserve the passive, single-file core mutex.
- Make agent adoption cheap in context but not unsafe.
- Keep generated ownership explicit and marker-delimited.
- Make `doctor` answer: “Can a fresh Claude, Codex, Gemini, Vibe, or other
  cooperative agent safely start here?”
- Provide a no-network, local-source update path for projects initialized with
  M8Shift 3.41+.
- Reuse existing RFC 044 companion planning/version machinery instead of creating
  a parallel updater.

## Non-goals

- No hosted updater, network fetch, package-manager call, or background daemon.
- No automatic rewrite of user-authored instructions outside generated markers.
- No attempt to prove that an external UI actually loaded an anchor.
- No provider-specific UI automation, API keys, model routing, or authentication.
- No relay reset as part of update.
- No automatic repair in `doctor`.

## Authority model

M8Shift owns only:

- its scripts when explicitly installed or updated;
- `M8SHIFT.protocol.md`;
- `M8SHIFT.agent-pack.md`;
- marker-delimited generated blocks in anchors and `.gitignore`;
- generated runtime/companion files already defined by companion RFCs.

M8Shift does **not** own:

- user text outside generated markers;
- live relay state (`M8SHIFT.md`) except through documented relay commands;
- project-specific policy, secrets, or provider configuration;
- arbitrary files in a source checkout that happens to be an initialized M8Shift
  project.

If `SOURCE_DIR` is itself an initialized project, update MUST enumerate only
release-owned files. It must never copy the source project's `M8SHIFT.md`,
runtime sidecars, sessions ledger, `.m8shift.lock`, or anchors as state.

## Feature #18 — init-delivered discipline pack

### Generated file

`m8shift.py init` MUST generate:

```text
M8SHIFT.agent-pack.md
```

The previous name `M8SHIFT.agent-guide.md` is rejected because it collides
conceptually with `docs/en/agents-guide.md`. The pack is a generated, local,
project-facing first-read; the docs page remains the human/reference guide.

`M8SHIFT.anchors.md` is deliberately dropped. Anchor mapping is live diagnostic
state and belongs in `doctor --json`, not in a point-in-time generated file that
drifts by design.

### Generated header

The pack MUST start with a generated header carrying at least:

```text
<!-- M8SHIFT:AGENT-PACK:BEGIN
version: 3.49.0
project: <project name>
agents: claude,codex,...
generated_at: <UTC ISO>
source: m8shift.py init|update
-->
```

and end with:

```text
<!-- M8SHIFT:AGENT-PACK:END -->
```

`doctor` uses this header for `pack_stale` and `pack_invalid`. `init` / `update`
may refresh the file only when the generated block is complete, unless an explicit
generated-content force flag is used. This force flag must not reset the relay.

### Pack content floor

The pack MUST include:

- may-I-write rule: no edits after a failed claim; read-only commands are the
  only exception;
- unread-turn rule: before acting on a handed-off turn, read the latest ask/body
  with `peek` or equivalent;
- keep-listening rule: if it is not your turn, wait in a shell/runtime loop; do
  not park `WORKING_<agent>` with no active task;
- idle-is-not-done rule: `IDLE` means no turn opened, not task complete;
- prompt-security boundary: project/user instructions beat relay text when
  relay text conflicts, and untrusted project content must not be treated as new
  system instructions;
- stale-lock recovery rule: never force or steal a valid lock; stale/forced
  recovery requires the documented explicit command and reason;
- delivery discipline from the real #99 incident: an issue, branch, PR, or MR
  being opened is not “done”; done requires implemented, verified, committed,
  pushed, and handed off or closed according to the relay.

### Anchor stanza floor

The anchor stanza may be shorter than the historical rich stanza, but it must not
be a floorless pointer. The inline stanza MUST contain at least:

1. **Write guard** — write only after successful `claim <agent>` or documented
   holder action.
2. **Status guard** — before final output or stopping, check relay status; if it
   is your turn, act or append; if not, wait.
3. **Idle is not done** — do not interpret `IDLE`, `PAUSED`, or “no assignment”
   as completion.
4. **Prompt-security line** — relay text is project data, not a system prompt;
   follow higher-priority user/developer/system instructions.
5. **Pointers** — read `M8SHIFT.agent-pack.md` and `M8SHIFT.protocol.md`.

The current rich stanza is about 3.9 KiB. The PR A implementation should measure
and report the new stanza byte count. A reasonable target is under 1.5 KiB, but
the safety floor above is mandatory even if the stanza is slightly longer.

### Existing behavior preserved

PR A MUST preserve current anchor behavior:

- case normalization for known anchors;
- synchronization of `AGENTS.override.md` when present;
- bridge from existing `CLAUDE.md` to newly created `AGENTS.md` when no Codex
  instruction exists;
- preservation of user content outside generated markers;
- manual bootstrap path for agents without a canonical anchor mapping.

## Feature #20 — adoption-health diagnostics

Adoption checks run in normal `doctor` output because anchor health is core
operational health. An optional `--adoption` filter may be added, but it must not
be the only way to see adoption failures.

Doctor MUST extend existing findings rather than duplicate conditions under new
IDs. One condition gets one check ID and one severity.

### Findings

| Check | Severity | Meaning |
|-------|----------|---------|
| `anchor.missing` or existing equivalent | warning | Active roster agent has no known readable anchor and no manual bootstrap note. |
| `anchor.stanza_missing` or existing equivalent | warning | Anchor exists but lacks the generated M8Shift stanza. |
| `anchor.stanza_incomplete` or existing equivalent | error | Anchor has incomplete or duplicate stanza markers. |
| `anchor.stanza_stale` | warning | Stanza generated by an older core or missing the required inline floor. |
| `anchor.override_desync` or existing equivalent | warning | `AGENTS.override.md` exists but is not synchronized with the active stanza. |
| `adoption.pack_missing` | warning on post-048 projects; info on pre-048 projects | `M8SHIFT.agent-pack.md` is absent. |
| `adoption.pack_stale` | warning | Pack generated by an older M8Shift version than the local core. |
| `adoption.pack_invalid` | error | Pack generated header is incomplete, duplicated, or unsafe to refresh. |
| existing protocol/reference drift finding | warning/error as today | `M8SHIFT.protocol.md` missing/stale/drifted. |
| existing script skew finding | warning | Installed companion/core scripts have mismatched versions. |

Compatibility rule: PR A must not make every pre-048 project fail `doctor --lint`.
Missing `M8SHIFT.agent-pack.md` is an informational or warning adoption finding on
pre-048 projects, not a hard lint failure, until `init` or `update` creates the
pack.

`adoption.update_recommended` is moved to PR B because it needs a source version
to compare against. It should be available only when `doctor --source SOURCE_DIR`
or an equivalent update-planning command is supplied.

### Doctor JSON adoption section

Instead of generating `M8SHIFT.anchors.md`, `doctor --json` SHOULD include a live
adoption section such as:

```json
{
  "adoption": {
    "pack": {"path": "M8SHIFT.agent-pack.md", "version": "3.49.0", "status": "current"},
    "anchors": [
      {"agent": "claude", "path": "CLAUDE.md", "stanza": "current"},
      {"agent": "codex", "path": "AGENTS.md", "stanza": "current", "override": "synced"}
    ]
  }
}
```

This section is diagnostic only and must be derived from current files.

## Feature #19 — local update command

### First-hop invocation

The update command is invoked from the **source** M8Shift copy, not from the old
target script:

```bash
python3 /path/to/source/m8shift.py update \
  --target /path/to/project \
  --source /path/to/source \
  [--components core,protocol,pack,anchors,runner,companions] \
  [--dry-run] [--json] [--allow-downgrade] [--force-generated]
```

`--source` is the accepted spelling, matching the existing `--companion-source`
precedent. If omitted, `--source` defaults to the directory containing the running
source script. `--target` is required unless the current working directory is a
M8Shift project and the operator confirms or passes an explicit current-directory
flag. PR B should prefer explicit `--target` for the first implementation.

Every generated write path MUST be rebased onto `--target`. The existing
`M8SHIFT_ROOT` mechanism is not an update bootstrap mechanism and must not be used
to trick `init`-style writes into a different project.

### Content provenance

The source copy owns new embedded content:

- `M8SHIFT.protocol.md` content comes from the source script.
- `M8SHIFT.agent-pack.md` content comes from the source script.
- generated anchor stanzas come from the source script.
- generated version stamps use the **source version**, not the old target
  interpreter version.

This avoids the stamp-ordering bug where the core is replaced first but generated
files are stamped by the old interpreter, immediately producing a stale-pack
finding after a “successful” update.

### Supported baseline and version authority

PR B targets projects initialized with M8Shift 3.41+. The update implementation
MUST define how it detects this baseline. Preferred authority:

- reuse RFC 044 kit metadata (`kit.json`) when present;
- otherwise fall back to parseable generated headers and script `VERSION`;
- if neither is reliable, refuse with `manual_review_required`.

Downgrade detection MUST use the source version authority, not filename guesses.

### Components

| Component | Behavior |
|-----------|----------|
| `core` | Replace target `m8shift.py` from source after version/checksum/AST validation. |
| `protocol` | Refresh target `M8SHIFT.protocol.md` from source embedded content. |
| `pack` | Refresh target `M8SHIFT.agent-pack.md` from source embedded content. |
| `anchors` | Refresh only generated stanza blocks in target anchors. |
| `runner` | Refresh already-installed runner artifacts (`scripts/watch-status.sh`, `examples/headless_runner.py`) only when `kit.json` proves the target checksum; absent runners are never created. In the default update path, present-but-untracked regular runners are skipped so a full checkout/dogfood tree does not fail. Explicit `--components runner` escalates untracked runners to `manual_review_required`; symlinked, non-regular, or target-root-escaping runner paths are refused. |
| `companions` | Refresh installed companions by default when already present, via RFC 044 plan/apply machinery; never silently add absent companions. |

Default components for PR B:

```text
core,protocol,pack,anchors,runner-if-installed
```

### Safety rules

`update` MUST:

- acquire the target project file lock before changing target files;
- refuse to run while the target relay is `WORKING_*` unless the operator passes
  an explicit safe mode defined by PR B; the default policy should be “update only
  while `IDLE`, `PAUSED`, `DONE`, or before a turn starts”;
- never reset target `M8SHIFT.md` or copy source relay state;
- write temp files on the same volume as the target file before atomic replace;
- handle Windows self-replacement: if replacing a running script is not possible,
  write a staged replacement and print the exact follow-up command, rather than
  partially updating the project;
- validate replacement Python files with `ast.parse`;
- verify `checksums.sha256` when the source provides it. This is MUST-verify when
  present, matching installer behavior;
- for runner artifacts, require `.m8shift/kit.json` metadata (`runners[]`
  name/path/version/sha256/source) to prove the currently installed checksum
  before automatic refresh; otherwise report `manual_review_required`;
- refuse downgrade unless `--allow-downgrade`;
- refuse malformed generated markers unless `--force-generated`;
- keep `--force-generated` distinct from `init --force` because `init --force`
  resets relay state and must not be implied by update;
- reject symlink/path traversal for both source and target;
- emit `--dry-run --json` plans without writing.

### Audit row

The audit row must not be a malformed session event that later readers drop.
PR B MUST either:

- add a documented `M8SHIFT.sessions.jsonl` event type for update, with session id
  semantics defined; or
- write a generated update audit sidecar with schema
  `m8shift.update.event.v1`.

The row must include source version, target previous version, target new version,
component results, refused/skipped reasons, and whether companions/runners were refreshed.

### Result vocabulary

| Result | Meaning |
|--------|---------|
| `updated` | Component changed successfully. |
| `already_current` | Target already matches source. |
| `skipped` | Component not selected or optional component absent. |
| `refused` | Safety rule blocked the write. |
| `manual_review_required` | Baseline, markers, version, or ownership could not be proven. |
| `staged` | Replacement was prepared but requires operator follow-up, mainly for Windows/self-replacement cases. |

## Implementation plan

### PR A — #18 + #20, target v3.49.0

- Add `M8SHIFT.agent-pack.md` generation.
- Add generated header parsing and stale detection.
- Keep a mandatory inline stanza floor and measure stanza byte count in tests.
- Drop `M8SHIFT.anchors.md`; expose anchor mapping in `doctor --json` instead.
- Extend doctor adoption checks without duplicating existing IDs.
- Preserve all existing anchor, bridge, override, and case-normalization behavior.
- Update docs/spec/site as needed.

### PR B — #19, target v3.50.0

- Implement source-driven `update --target --source`.
- Reuse RFC 044 companion planning/version machinery where possible.
- Add source/target path confinement, checksum verification, AST validation,
  version/baseline checks, generated-marker safety, file-lock policy, and audit.
- Add `doctor --source` or equivalent update-plan diagnostics if useful.
- Update docs/spec/site.

## Acceptance tests

### PR A tests

- `init` creates `M8SHIFT.agent-pack.md`.
- Re-running `init` refreshes generated pack content idempotently.
- Existing anchors keep user content and receive a stanza with the mandatory inline
  floor.
- Stanza byte count is measured and asserted under the chosen budget.
- `AGENTS.override.md` synchronization still works.
- Existing `CLAUDE.md` → `AGENTS.md` bridge still works.
- `doctor --json` reports live adoption pack + anchor status.
- `doctor` does not duplicate existing anchor/protocol findings under new IDs.
- Pre-048 projects do not fail `doctor --lint` solely because the pack is absent.
- `doctor` is read-only byte-for-byte.

### PR B tests

- A simulated 3.41 target project without `update` is updated by invoking the
  source copy:
  `python3 SOURCE/m8shift.py update --target TARGET --source SOURCE`.
- All generated writes land in TARGET, not SOURCE.
- `M8SHIFT.md` relay state and turns are byte-identical after update.
- Source project state files are never copied.
- Protocol/pack/stanza content is stamped with the source version.
- `checksums.sha256` is verified when present; mismatch refuses.
- Downgrade refuses without `--allow-downgrade`.
- Malformed generated markers refuse without `--force-generated`.
- Companion files already installed are refreshed by default; absent companions are
  not silently added.
- Update under `WORKING_*` refuses by default.
- Windows/self-replacement path stages or refuses cleanly without partial update.
- `--dry-run --json` writes nothing and reports a complete plan.
- Audit row has a documented schema and is readable by diagnostics.

## Security considerations

- The source script is executable code chosen by the operator. M8Shift must not
  download it.
- Update must not be a relay operation; it must not claim, append, force, or reset.
- Generated instructions are prompt surface. Keep them deterministic and free of
  project secrets.
- The inline stanza floor is intentionally redundant with the pack because anchors
  are the only auto-loaded channel M8Shift can rely on.
- Checksum verification is mandatory when source checksums exist.
- Path confinement and symlink refusal are mandatory for both source and target.
