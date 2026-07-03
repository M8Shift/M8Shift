# RFC 044 — Complete initialization and companion install

- Status: draft
- Date: 2026-07-03
- Origin: operator request after the v3.43.0 dogfood cycle showed that `init` prepares the relay state but does not make optional companion scripts available in the adopted project
- Builds on: [RFC 008 Worktree companion](008-rfc-worktree-companion.md), [RFC 009 Runtime companion](009-rfc-runtime-companion.md), [RFC 034 Companion adapter interface](034-rfc-companion-adapter-interface.md), [RFC 037 Agent context compression backends](037-rfc-agent-context-compression-backends.md), [RFC 042 Compression backend routing](042-rfc-compression-backend-routing.md)
- Related: [RFC 045 Module reference and examples](045-rfc-module-reference-examples.md)

## Summary

`m8shift.py init` already creates the relay anchors, protocol files, commit hook,
session ledger entry, and `.gitignore` block for M8Shift state artifacts. That part
is sufficient and should be preserved. The remaining gap is adoption completeness:
operators still need to hand-copy optional companion scripts such as
`m8shift-runtime.py` or `m8shift-context.py` when they want the installed project to
be self-contained.

This RFC specifies a version-locked, idempotent companion-copy phase for `init`.
The phase is explicit, safe by default, and keeps the core relay passive: it copies
known local M8Shift companion scripts from the directory where the running
`m8shift.py` lives, verifies that their versions match the core script, refuses to
silently overwrite local edits, and records what was installed for later `doctor`
checks.

## Problem

The current adoption workflow is split across two mental models:

```bash
cp /path/to/m8shift.py .
python3 m8shift.py init --agents claude,codex
cp /path/to/m8shift-runtime.py .   # optional, manual
cp /path/to/m8shift-context.py .   # optional, manual
```

The first two commands look like an initialization. The later copy steps are easy
to forget, and when forgotten the failure mode appears much later: a guide asks
an operator to run `python3 m8shift-runtime.py watch codex`, but the file is absent
from the project.

The product already carries a module family:

| Script | Role |
|--------|------|
| `m8shift.py` | core relay, lock, turns, reports, tasks, doctor |
| `m8shift-runtime.py` | local runtime sidecars: presence, inbox, progress, notifications, providers |
| `m8shift-context.py` | context packs, compression records, adapter dispatch |
| `m8shift-worktree.py` | isolated worktrees and serialized integration |
| `m8shift-headroom.py` | optional local Headroom-compatible launcher |
| `m8shift-i18n.py` | language pack builder |
| `m8shift-e2e.py` | end-to-end smoke harness |

`init` should be able to install selected companions from this known family.

## Existing behavior to preserve

The `.gitignore` behavior is not the missing feature. `m8shift.py` already owns a
generated block via `GITIGNORE_ENTRIES` and `should_manage_gitignore()`:

- default non-interactive behavior manages `.gitignore`;
- TTY use asks the operator;
- `--gitignore` and `--no-gitignore` remain explicit overrides;
- the block covers M8Shift state and generated runtime data such as
  `M8SHIFT.md`, `M8SHIFT.sessions.jsonl`, `M8SHIFT.session-reports/`,
  `.m8shift.lock`, `.m8shift-*.tmp`, `.m8shift/`, and `*.m8shift.bak`.

RFC 044 must not replace that mechanism. Implementation should only verify that
new companion-install metadata, if introduced, lives under the already-ignored
`.m8shift/` tree.

## Goals

1. Let `init` copy selected companion scripts into an adopted project.
2. Keep all copied scripts version-locked with the running `m8shift.py`.
3. Make the operation idempotent: repeated `init` runs should be quiet when files
   are unchanged.
4. Refuse silent clobbering of local edits, newer versions, or unknown files.
5. Record a local manifest so `doctor` can report missing or version-skewed
   companions.
6. Preserve the passive, stdlib-only, local-filesystem core.

## Non-goals

- No package manager, daemon, background service, or hosted installer.
- No automatic download from the network.
- No third-party dependency install. `--with-headroom` remains the installer /
  optional-venv concern, not a core `init` side effect.
- No hidden overwrite of user-edited companion scripts.
- No cross-project global registry.
- No change to the one-pen relay semantics.

## CLI design

`init` gains an explicit companion selection surface:

```bash
python3 m8shift.py init --agents claude,codex \
  --companions runtime,context,worktree

python3 m8shift.py init --with-runtime --with-context --with-worktree

python3 m8shift.py init --full

python3 m8shift.py init --no-companions
```

### Companion selectors

| Selector | Copies |
|----------|--------|
| `runtime` / `--with-runtime` | `m8shift-runtime.py` |
| `context` / `--with-context` | `m8shift-context.py` |
| `worktree` / `--with-worktree` | `m8shift-worktree.py` |
| `headroom` / `--with-headroom-companion` | `m8shift-headroom.py` only, not the external Python environment |
| `i18n` / `--with-i18n` | `m8shift-i18n.py` |
| `e2e` / `--with-e2e` | `m8shift-e2e.py` |
| `--full` | all known local companions listed above |
| `--no-companions` | copy none; explicit opt-out |

`--with-headroom` is already used by the installer for the optional Headroom
environment. To avoid semantic ambiguity, the core `init` flag should be named
`--with-headroom-companion` if the implementation keeps the long-form flag family.

`--companions` accepts a comma-separated list of canonical selector names. Unknown
names are a hard error with a list of valid names.

### Source and destination

Default source directory:

```text
dirname(realpath(path_to_the_running_m8shift_py))
```

This makes the operation work from a copied release directory, an unpacked archive,
or a local checkout. `cwd` is not the source; `cwd` is the target project.

Optional override:

```bash
python3 m8shift.py init --companions runtime,context \
  --companion-source /path/to/M8Shift-release
```

Destination:

- companion scripts are copied next to the target project's `m8shift.py`;
- generated metadata is stored under `.m8shift/kit.json`;
- metadata stays ignored by the existing `.gitignore` block.

## Version lock

Each source companion must expose a top-level `VERSION = "X.Y.Z"` equal to the
running core `m8shift.py` `VERSION`. By default:

- missing `VERSION` => refuse;
- mismatched version => refuse;
- source file missing => refuse if selected;
- destination file version newer than the core => refuse unless an explicit future
  downgrade flag is added.

The release rule is simple: companions copied by `init` are a kit, not independent
floating tools. A project that needs mixed versions must opt out of managed copying.

## Idempotency and overwrite policy

For each selected companion:

| Destination state | Behavior |
|-------------------|----------|
| absent | copy atomically |
| present, byte-identical to source | report `already up to date` |
| present, same version but different hash | refuse; require `--force-companions` |
| present, older version | refuse by default; allow `--force-companions` |
| present, newer version | refuse; require a separate explicit downgrade override if ever implemented |
| present, no parseable version | refuse; do not guess |

`--force-companions` permits replacing older or same-version-different files, but it
must still print the replaced path and previous SHA-256. It must not override a
newer destination unless a future `--allow-downgrade` is also present.

Copies should be atomic:

1. read source bytes;
2. verify the source path is a regular file under the companion source directory;
3. write a target-local temporary file;
4. preserve executable bit where present;
5. `os.replace()` into place.

## Manifest

`init` writes `.m8shift/kit.json` whenever companion copying is requested.

```json
{
  "schema": "m8shift.kit.v1",
  "core": {
    "script": "m8shift.py",
    "version": "3.43.0"
  },
  "companions": [
    {
      "name": "runtime",
      "script": "m8shift-runtime.py",
      "version": "3.43.0",
      "sha256": "…",
      "copied_at": "2026-07-03T09:00:00Z",
      "source": "/abs/path/to/release/m8shift-runtime.py"
    }
  ]
}
```

The manifest is local state. It is not an authority over the relay lock. Deleting it
only removes companion-install diagnostics; it must not corrupt `M8SHIFT.md`.

## Doctor checks

Core `doctor` gains read-only kit checks:

- `.m8shift/kit.json` malformed;
- listed companion missing;
- listed companion has no parseable version;
- listed companion version differs from core;
- listed companion hash differs from the recorded hash;
- manifest references an unknown companion name.

Severity should be warning unless the current command explicitly depends on the
companion. Example: a missing `m8shift-runtime.py` is not a relay-lock failure.

`doctor --json` should expose the findings under a stable component name such as
`kit.companions`.

## Security considerations

- The companion list is allowlisted. `--companions ../../x` is impossible because
  selector names map to fixed filenames.
- Source paths are resolved with `realpath`; only regular files under the source
  directory are accepted.
- No shell is used.
- No network is used.
- Version extraction must be static text parsing, not importing selected companion
  files.
- Hashes are integrity diagnostics, not a signature or trust proof.

## Implementation phases

### Phase A — copy engine

- Add the companion registry.
- Add selector flags and `--companion-source`.
- Implement version/hash checks and atomic copy.
- Write `.m8shift/kit.json`.
- Preserve existing `.gitignore` handling unchanged.

### Phase B — doctor integration

- Add read-only kit checks.
- Add JSON output for companion findings.
- Add tests for missing, skewed, edited, and unknown companion entries.

### Phase C — documentation and examples

- Update protocol reference and installation guides.
- Cross-link to the module reference pages from RFC 045.

## Tests

Minimum regression coverage:

1. `init --no-companions` behaves like current `init`.
2. `init --companions runtime,context` copies only those scripts.
3. repeated `init --companions runtime` is idempotent.
4. version-skewed source companion is refused.
5. edited destination companion is refused without `--force-companions`.
6. newer destination companion is not downgraded by `--force-companions`.
7. `.m8shift/kit.json` is written and ignored by the existing `.gitignore` block.
8. `doctor` warns on a missing or skewed listed companion.

## Open questions

1. Should companion scripts copied next to `m8shift.py` be committed by target
   projects, or should `init` offer an optional `--gitignore-companion-scripts`
   block? This RFC leaves the default neutral: companion scripts are code artifacts,
   while `.m8shift/kit.json` remains ignored state.
2. Should installers call `init --full` automatically, or should installer and
   project initialization remain separate steps?
3. Should `m8shift-e2e.py` be included in `--full` by default, or remain a release
   test tool copied only by explicit selector?

## Definition of done

- Operators can run one `init` command and obtain the selected companion scripts.
- Copied companions match the core version.
- Re-running the command is safe and quiet.
- Local edits are not silently overwritten.
- `doctor` explains missing or skewed companions.
- Existing relay state and `.gitignore` semantics remain unchanged.
