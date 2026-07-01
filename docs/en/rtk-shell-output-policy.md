# RTK shell-output policy

M8Shift treats RTK as an optional shell-output filter adapter. RTK is not bundled,
not auto-installed, and never becomes evidence by itself. The operator installs
`rtk` separately when they want this optimization.

Use RTK for noisy command output where the measured compact view preserves the
decision signal:

| Use case | Recommended mode | Policy |
|---|---|---|
| compiler/test failures, warnings, noisy CI logs | `err` / `test` | Recommended before pasting into a handoff or context pack. |
| large logs where exact full text is not required | `log` | Recommended as an operational view; keep raw logs available. |
| huge listings / recursive directory output | `ls` | Recommended for navigation and inventory. |

Do **not** use RTK for code-review diffs:

| Use case | Mode | Policy |
|---|---|---|
| `git diff` / patch review / hunk inspection | `git-diff` | Forbidden by the shipped manifest; Round 2 measured this mode as lossy for hunks. Read raw diffs instead. |

Adapter output is an operational view, not evidence. When a decision depends on
exact wording, patches, security-sensitive output, or legal/contractual text, read
the original raw output.

The shipped manifest is written by:

```bash
python3 m8shift-context.py adapters init
```

`adapters init` records the trusted `rtk` executable identity when `rtk` is
available on `PATH`: resolved absolute path plus binary SHA-256. At runtime,
M8Shift re-resolves `rtk` and rejects execution unless both the path and hash
match the recorded identity. This deliberately rejects same-name wrappers,
renamed copies, symlink/path hijacks, and relay binaries disguised as `rtk`.

If RTK is installed or upgraded after manifest generation, regenerate the manifest
from a trusted shell:

```bash
python3 m8shift-context.py adapters init --force
python3 m8shift-context.py adapters check rtk-shell-output
```

Typical usage:

```bash
pytest -q 2>&1 | python3 m8shift-context.py adapters run rtk-shell-output --mode err --stdin
git log --stat -25 | python3 m8shift-context.py adapters run rtk-shell-output --mode log --stdin
ls -lR | python3 m8shift-context.py adapters run rtk-shell-output --mode ls --stdin
```

The runner is companion-only: argv arrays only, bare executable names only,
`rtk` allowlisted as the shipped shell-output filter, `PATH` resolution required,
trusted executable identity required, bounded timeout/stdout/stderr, allowlisted
environment, no shell string, no `LOCK` mutation, and fallback behavior declared
in the manifest.
