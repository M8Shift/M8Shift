# RFC 048 — Adoption discipline pack, local update, and adoption-health diagnostics

- Status: draft
- Date: 2026-07-04
- Target version: v3.49.0+
- Tracks: GitHub #18, #19, #20
- Builds on: [RFC 010 Runtime patterns](010-rfc-runtime-patterns.md), [RFC 018 Agent runtime architecture](018-rfc-agent-runtime-architecture.md), [RFC 044 Complete init companion install](044-rfc-complete-init-companion-install.md), [RFC 045 Module reference examples](045-rfc-module-reference-examples.md), [RFC 046 Interactive/headless modes and runner install](046-rfc-interactive-headless-runner-install.md)
- Related: [RFC 023 Agent token footprint](023-rfc-agent-token-footprint.md), [RFC 047 Headless liveness](047-rfc-headless-liveness-runner-listener.md)

## Summary

Adoption currently depends on each host project having the right anchor files
(`CLAUDE.md`, `AGENTS.md`, overrides, and equivalents for other cooperative
agents), the right generated stanza, the right local scripts, and human discipline
when a project is upgraded.

RFC 048 makes this an explicit adoption surface with three linked features:

1. **#18 init-delivered discipline pack** — `init` generates a compact,
   versioned `M8SHIFT.agent-guide.md` plus an anchors reference. Agent anchors stay
   lightweight and point to this pack instead of duplicating the full operating
   rules.
2. **#19 local `update` command** — projects created with older M8Shift versions
   can refresh the engine, protocol/reference files, generated discipline pack,
   anchor stanzas, and selected companions from a trusted local source without
   resetting the relay or clobbering user content.
3. **#20 adoption-health diagnostics** — `doctor` reports whether a project is
   actually adoptable by agents: missing/outdated pack, stale stanzas, skewed
   scripts, override drift, malformed generated blocks, and unsafe update sources.

These features belong together because they share the same authority boundary:
M8Shift may own marker-delimited generated blocks and its own generated files; it
must not rewrite arbitrary project instructions or infer provider-specific UI
behavior.

## Problem

M8Shift works only if agents actually read the right local instructions. In
practice, three failure modes repeat:

- `init` injects a stanza, but the useful rules drift across `CLAUDE.md`,
  `AGENTS.md`, protocol docs, runtime guides, and human prompts.
- Updating a project after a rename or protocol split requires manual copy steps,
  so projects can run a new script with old anchors or old protocol files.
- `doctor` can validate the relay state, but it does not yet answer the adoption
  question: “Will a fresh Claude, Codex, Gemini, Vibe, or other cooperative agent
  know what to do in this project?”

The result is avoidable human babysitting: agents miss the expected loop, hold the
pen passively, ignore companion guidance, or keep using obsolete instructions.

## Goals

- Keep the **core mutex passive and single-file**.
- Make the generated agent instructions **short, versioned, and auditable**.
- Avoid duplicating long protocol content in every auto-loaded anchor.
- Preserve existing project instructions outside generated marker blocks.
- Provide a local, non-network `update` path for projects created with M8Shift
  3.41+.
- Make adoption-health failures visible through `doctor` and JSON output.
- Support Claude and Codex explicitly while keeping the model generic for Gemini,
  Vibe, and any cooperative agent that can read its anchor and run the CLI.

## Non-goals

- No hosted updater, package manager, background daemon, or network download.
- No automatic rewrite of user-authored instruction text outside generated blocks.
- No attempt to verify that an external UI has actually loaded its anchor.
- No provider-specific authentication, model routing, or API-key management.
- No change to the one-pen relay semantics.
- No automatic repair in `doctor`; diagnostics are read-only.

## Terminology

| Term | Meaning |
|------|---------|
| **Anchor** | A file an agent UI/CLI naturally reads at startup, such as `CLAUDE.md`, `AGENTS.md`, or `AGENTS.override.md`. |
| **Stanza** | The marker-delimited `M8SHIFT:STANZA` block inserted into an anchor by `init` / `update`. |
| **Discipline pack** | `M8SHIFT.agent-guide.md`, the generated compact instructions every agent stanza points to. |
| **Anchors reference** | `M8SHIFT.anchors.md`, a generated map of active roster agents to their expected anchor files and bootstrap notes. |
| **Adoption health** | Read-only diagnostics proving the local files required for agent adoption are present, current, and internally consistent. |

## Feature #18 — init-delivered discipline pack

### Generated files

`m8shift.py init` MUST generate these files next to `M8SHIFT.md`:

```text
M8SHIFT.agent-guide.md
M8SHIFT.anchors.md
```

Both files are generated M8Shift files. They may be overwritten by `init` and
`update` when their generated marker header is intact. If a user removes or
corrupts the generated header, `init` / `update` MUST refuse to overwrite unless
the operator passes the same explicit force mechanism used for other generated
assets.

### `M8SHIFT.agent-guide.md`

The guide is the compact first-read for agents. It MUST include:

- file identity, generated-by version, project name, roster, and timestamp;
- the current work loop:
  `status/peek` → `claim` → work → validation → `append` / `done`;
- the hard rule: write only after a successful claim unless the command is
  explicitly documented as read-only;
- the waiting rule: if it is not this agent's turn, use shell/runtime waiting,
  not chat polling;
- the no-parking rule: do not keep `WORKING_<agent>` with no active task;
- how to use `PAUSED`, `cooldown`, runtime listener, and usage wait at a high
  level without duplicating their full docs;
- the companion boundaries: runtime, worktree, context, headroom, and listener
  are optional companions and do not change core pen authority;
- a short “when in doubt” section:
  read `M8SHIFT.protocol.md`, read the latest turn with `peek`, and ask/append
  through the relay rather than inventing a parallel protocol.

The guide MUST be concise enough to be cheap in agent context. Long command
references stay in `M8SHIFT.protocol.md` / `docs/en/protocol-reference.md`.

### `M8SHIFT.anchors.md`

The anchors reference MUST include:

- active roster;
- canonical anchor filename per agent;
- whether the anchor was created, refreshed, skipped, bridged, or overridden;
- whether `AGENTS.override.md` is present and synchronized;
- the exact stanza marker names;
- a note that Claude and Codex are examples, and that Gemini, Vibe, or other
  cooperative agents must read their configured anchor or be bootstrapped manually
  if no canonical anchor exists.

This file is diagnostic documentation, not a runtime authority.

### Anchor stanza

The generated stanza in each anchor SHOULD be shorter than today's rich stanza and
MUST point to the generated guide:

```text
<!-- M8SHIFT:STANZA:BEGIN (generated by m8shift.py init - do not edit by hand) -->
## M8Shift relay

This project uses M8Shift. Before editing, read:

1. M8SHIFT.agent-guide.md
2. M8SHIFT.protocol.md

Then identify yourself as the roster agent for this anchor and follow the
claim → work → append/done loop. Never edit after a failed claim.
<!-- M8SHIFT:STANZA:END -->
```

The actual text may be refined, but it must stay:

- marker-delimited;
- idempotent;
- lightweight;
- placed at the top of the anchor;
- safe for existing `CLAUDE.md`, `AGENTS.md`, and `AGENTS.override.md` files.

### Existing anchor behavior preserved

This RFC does not remove current behavior:

- case normalization for known anchors remains;
- `AGENTS.override.md` remains synchronized when present;
- if a project has `CLAUDE.md` but no Codex instruction, the safe bridge behavior
  remains;
- existing user content outside the stanza is preserved;
- unknown cooperative agents may still fall back to `AGENTS.md` or manual
  bootstrap when there is no known anchor mapping.

## Feature #19 — local `update` command

### Command surface

Add a core command:

```bash
python3 m8shift.py update \
  --from SOURCE_DIR \
  [--components core,protocol,pack,anchors,companions] \
  [--dry-run] [--json] [--allow-downgrade] [--force-generated]
```

Open naming question for implementation review: `--from` is concise, but Python
and shells tolerate it as an option name; if maintainers prefer avoiding the
reserved-word spelling in code, use `--source` while keeping docs examples clear.

### Source model

`update` is local-only:

- `SOURCE_DIR` is an already trusted local M8Shift release checkout, extracted
  archive, or installed script directory;
- no network fetch;
- no package-manager call;
- no shell interpolation;
- all file operations are stdlib and path-confined.

### Version compatibility

The command targets projects created with M8Shift 3.41+ because those projects
already have the post-split protocol/reference model and companion-copy discipline.

For older projects, `update` MUST fail with a clear message:

```text
project was initialized before the supported update baseline; run a manual
upgrade or re-init with explicit operator review
```

### Components

| Component | Behavior |
|-----------|----------|
| `core` | Replace `m8shift.py` from source after validating parseability, version, and optional checksum. |
| `protocol` | Refresh `M8SHIFT.protocol.md` and any generated protocol reference files owned by M8Shift. |
| `pack` | Refresh `M8SHIFT.agent-guide.md` and `M8SHIFT.anchors.md`. |
| `anchors` | Refresh only generated stanza blocks in active anchors. Preserve user content. |
| `companions` | Refresh installed companion scripts only when present or explicitly selected; preserve optionality. |

Default component set SHOULD be:

```text
core,protocol,pack,anchors
```

Companions SHOULD require either explicit component selection or a detected
already-installed companion, to avoid silently adding new executable files.

### Safety rules

`update` MUST:

- refuse path traversal and symlink escape from `SOURCE_DIR` or target project;
- validate replacement Python files with `ast.parse` before moving them into place;
- refuse downgrade unless `--allow-downgrade`;
- write via temp file + atomic replace when possible;
- preserve current `M8SHIFT.md` session state and turns;
- never reset the relay lock;
- never edit arbitrary user text outside generated marker blocks;
- produce a dry-run plan before writing when `--dry-run`;
- emit machine-readable results with per-component action/skipped/refused entries
  under `--json`;
- leave a local update audit event in the sessions ledger or a dedicated generated
  sidecar when a real update writes files.

### Update result vocabulary

Each component result SHOULD use one of:

| Result | Meaning |
|--------|---------|
| `updated` | File/block changed successfully. |
| `already_current` | Target already matches the source version/content. |
| `skipped` | Component not selected or optional component absent. |
| `refused` | Safety rule blocked the write. |
| `manual_review_required` | Generated markers are missing/corrupt or baseline is too old. |

## Feature #20 — adoption-health doctor checks

### Command surface

Extend existing `doctor` with adoption findings. No separate command is required.
JSON output SHOULD include enough structured data for automation.

Optional flags may be added if useful:

```bash
python3 m8shift.py doctor --adoption
python3 m8shift.py doctor --json
```

If no flag is added, adoption checks run in normal doctor mode because anchor
health is core operational health.

### Findings

Doctor SHOULD emit these advisory checks:

| Check | Severity | Meaning |
|-------|----------|---------|
| `adoption.pack_missing` | warning | `M8SHIFT.agent-guide.md` or `M8SHIFT.anchors.md` missing. |
| `adoption.pack_stale` | warning | Pack generated by an older M8Shift version than the local core. |
| `adoption.pack_invalid` | error | Generated pack header/marker is malformed or unsafe to refresh. |
| `adoption.anchor_missing` | warning | Active roster agent has no known readable anchor and no manual bootstrap note. |
| `adoption.stanza_missing` | warning | Anchor exists but has no generated M8Shift stanza. |
| `adoption.stanza_incomplete` | error | Anchor has only one stanza marker or duplicate marker blocks. |
| `adoption.stanza_stale` | warning | Stanza does not point to the current discipline pack/protocol. |
| `adoption.override_desync` | warning | `AGENTS.override.md` exists but differs from `AGENTS.md` stanza expectations. |
| `adoption.protocol_missing` | error | `M8SHIFT.protocol.md` missing. |
| `adoption.script_skew` | warning | Installed companion/core scripts have mismatched versions. |
| `adoption.update_recommended` | info | Source/current version comparison indicates a safe local update is available, when a source is provided. |

No doctor finding may mutate files. Repair remains an explicit `init`, `update`, or
operator edit.

## Implementation plan

### PR A — discipline pack + doctor visibility

- Add generated `M8SHIFT.agent-guide.md` and `M8SHIFT.anchors.md` templates.
- Make `init` create/refresh them idempotently.
- Shorten anchor stanza to point to the pack.
- Preserve current bridge/override/case-normalization behavior.
- Add doctor adoption checks for pack presence, stanza health, override sync, and
  script/protocol presence.
- Update docs/spec/tests.

### PR B — local update command

- Implement `m8shift.py update`.
- Support `--dry-run`, `--json`, component selection, baseline checks,
  parse/version checks, generated-block refresh, and audit rows.
- Add tests for upgrade, downgrade refusal, malformed markers, companion optionality,
  symlink/path safety, and no relay reset.

### PR C — polish / site / migration notes

Optional if PR A/B become too large:

- site docs and examples;
- migration guide for 3.41+ projects;
- screenshots/diagrams if the site needs them;
- final specification row.

## Acceptance tests

Minimum test families:

- `init` creates both generated pack files.
- Re-running `init` is idempotent and preserves user edits outside markers.
- Existing anchors keep user content and receive the shortened stanza.
- `AGENTS.override.md` synchronization still works.
- Missing Codex anchor bridge from existing `CLAUDE.md` still works.
- `doctor --json` reports missing/stale/malformed pack and stanzas.
- `doctor` is read-only byte-for-byte.
- `update --dry-run --json` writes nothing and reports planned changes.
- `update` refuses source paths outside the selected source root.
- `update` refuses downgrade without `--allow-downgrade`.
- `update` refuses malformed generated markers without `--force-generated`.
- `update` refreshes core/protocol/pack/anchors without resetting `M8SHIFT.md`.
- `update` refreshes installed companions only when selected or detected.
- `update` validates Python replacements with `ast.parse`.
- `update` emits a durable audit row.
- Full suite remains green after each PR.

## Security considerations

- `update` writes executable files; it must be stricter than ordinary docs
  generation.
- Source trust is operator-controlled and local. M8Shift should not download code.
- Path confinement and symlink handling are mandatory for source and target paths.
- Python replacements must parse before replace; optional checksums should be used
  when the source directory ships `checksums.sha256`.
- Generated packs are instructions to agents. They must be short, deterministic,
  and free of project-specific secrets.
- Doctor must never auto-repair generated instructions; read-only diagnostics keep
  the boundary clear.

## Open questions for Claude review

1. Should the command option be `update --from SOURCE_DIR` or
   `update --source SOURCE_DIR`?
2. Should `doctor` run adoption checks always, or only under `--adoption` plus
   `--json`?
3. Should companion refresh be included in the default component set when a
   companion file is already present?
4. Should `M8SHIFT.anchors.md` be considered generated-only, or may operators add a
   manual bootstrap section outside markers?
5. Is `v3.49.0` the right target for PR A, with `v3.50.0` reserved for `update`,
   or should all three issues ship under one version?

