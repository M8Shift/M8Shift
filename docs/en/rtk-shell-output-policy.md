# RTK shell-output policy

M8Shift treats RTK as an optional shell-output filter adapter. RTK is not bundled,
not auto-installed, and never becomes evidence by itself. The operator either
installs `rtk` separately or gives explicit installer consent with `--with-rtk`
when they want this optimization.

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
available on normal `PATH`: resolved absolute path plus binary SHA-256. At
runtime, M8Shift re-resolves `rtk` and rejects execution unless both the path and
hash match the recorded identity. This deliberately rejects same-name wrappers,
renamed copies, symlink/path hijacks, and relay binaries disguised as `rtk`.

Project-local `.m8shift/bin/rtk` is a separate trust path. It is accepted only
when `adapters init` is run with an explicit review flag:

```bash
python3 m8shift-context.py adapters init --force --allow-project-local-adapters
```

That opt-in is still insufficient by itself: the installer provenance file must
also match the candidate's real path and SHA-256. The Bash installer passes this
flag automatically only after `--with-rtk` downloaded a release asset and verified
it against the same release checksums.

The Bash installer can perform the optional setup portably:

```bash
bash install.sh --with-rtk
```

It downloads the OS-specific RTK release asset for macOS, Linux, or Git
Bash/Windows, verifies it against RTK's `checksums.txt` from the same GitHub
release tag (the installer trust model is GitHub + TLS for that tag), installs it
under `.m8shift/bin`, records installer provenance, disables telemetry, and
writes the pinned adapter manifest. If a matching prebuilt asset is unavailable,
Cargo/Rust source builds are disabled unless `--allow-source-build` is explicit;
that fallback is pinned to the selected `--rtk-version` tag.

Project-local binaries are never trusted just because they exist. `adapters init`
prefers a normal `PATH` executable for pin establishment. A `.m8shift/bin/rtk`
candidate is accepted only after explicit opt-in and matching installer
provenance. Setup telemetry helpers execute
`rtk telemetry disable` only via a freshly verified manifest `trusted_executable`;
absent, unpinned, drifted, or symlinked local binaries are skipped instead of
run. Public `status`/`doctor` output deliberately does **not** log RTK telemetry
stdout/stderr; it reports telemetry as `not-reported`.

If RTK is installed or upgraded after manifest generation, regenerate the manifest
from a trusted shell:

```bash
python3 m8shift-context.py adapters init --force
python3 m8shift-context.py adapters check rtk-shell-output
```

Visibility:

```bash
M8SHIFT_RTK=on python3 m8shift-runtime.py watch codex --once
python3 m8shift-runtime.py status-runtime
python3 m8shift-context.py status
python3 m8shift-context.py doctor
```

`M8SHIFT_RTK=on|off` is self-declared by each agent lane. It is intentionally not
evidence of actual command usage. M8Shift never probes an agent shell over the
network and never re-enables RTK telemetry.

To audit an agent's actual local RTK command usage, use RTK's own local audit
tooling:

```bash
rtk discover
```

This is the intended audit path because RTK telemetry remains disabled by design.

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
