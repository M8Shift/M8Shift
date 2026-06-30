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

Typical usage:

```bash
pytest -q 2>&1 | python3 m8shift-context.py adapters run rtk-shell-output --mode err --stdin
git log --stat -25 | python3 m8shift-context.py adapters run rtk-shell-output --mode log --stdin
ls -lR | python3 m8shift-context.py adapters run rtk-shell-output --mode ls --stdin
```

The runner is companion-only: argv arrays only, bounded timeout/output, allowlisted
environment, no shell string, no `LOCK` mutation, and fallback behavior declared in
the manifest.
