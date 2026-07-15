# Script usage reference

This is the site-ready usage index for every command-line script shipped in the
repository. Examples use fabricated agents and paths. Run `SCRIPT --help` (or the
platform equivalent) for the exact parameters in the installed version.

Python entry points use positional commands, like Git: write
`m8shift-runtime.py listener status`, not `m8shift-runtime.py --listener`.
When a required positional or option is missing, argparse still exits with code 2,
but now prints the relevant command help and a `required invocation example`.
The Bash installer retains exit code 1 for a missing option value and prints a
correct `try:` form. PowerShell parameter-binding errors retain PowerShell's native
non-zero behavior.

## Relay and operator entry points

### `m8shift.py`

The portable relay engine owns the pen, turns, sessions, task board, and generated
kit. Invoke it as `m8shift.py <command> [args]`. Its command families are setup
(`init`, `update`, `bind`), inspection (`status`, `time`, `watch`, `doctor`,
`recap`, `log`, `history`, `session`), relay flow (`wait`, `next`, `claim`,
`append`, `release`, `done`), and supporting ledgers (`task`, `remember`,
`decisions`). See the [complete command reference](m8shift-command-reference.md)
for every parameter.

```bash
./m8shift.py status --for agent-a
./m8shift.py append agent-a --to agent-b \
  --ask "review the change" --done "implemented it"
```

For example, omitting `--to` from `append` prints the full `append` help, the
correct example above, the original argparse error, and exits 2.

### `m8shift-top.py`

The read-only terminal dashboard accepts `--interval N`, `--plain`, `--utc`,
`--root DIR`, and `--engine PATH`. Unknown remaining arguments are forwarded to
the engine's `watch` command.

```bash
python3 m8shift-top.py --interval 5 --utc
python3 m8shift-top.py --plain --for agent-a
```

### `m8shift-runtime.py`

The optional runtime companion manages local presence, notifications, operator
messages, progress, providers, routing, roles, workflows, approvals, reports,
retention, listeners, and usage snapshots. Invoke it as
`m8shift-runtime.py <command> [args]`; use `<command> -h` for that command's
parameters.

```bash
python3 m8shift-runtime.py status-runtime --json
python3 m8shift-runtime.py listener status --agent agent-a
```

Required option values use descriptive metavars. Missing required values print the
selected command's options and a valid invocation before exiting 2.

### `m8shift-context.py`

The context companion builds bounded packs and receipts, records metrics,
compresses redacted input, retrieves bounded records, manages adapter manifests,
and runs diagnostics. Commands are `init`, `pack`, `receipt`, `metrics`,
`compress`, `retrieve`, `status`, `benchmark`, `adapters`, and `doctor`; `--root
DIR` selects another project.

```bash
python3 m8shift-context.py pack --profile reviewer
python3 m8shift-context.py retrieve RECORD_ID
```

### `m8shift-worktree.py`

The worktree toolbox creates isolated lanes and serializes integration. Commands
are `claim`, `done`, `integrate`, `drop`, `status`, and `doctor`.

```bash
python3 m8shift-worktree.py claim feature-a agent-a --base main
python3 m8shift-worktree.py integrate feature-a agent-a --into main --to agent-b
```

`--base`, `--into`, `--to`, and confirmation/takeover values are shown in the
individual command help. Omitting a required value prints that help and a valid
required invocation, then exits 2.

### `m8shift-headroom.py`

The optional offline adapter reads already-redacted text from stdin. Its command is
`m8shift-transform MODE`; `MODE` is required.

```bash
python3 m8shift-headroom.py m8shift-transform report < redacted-input.txt
```

### `m8shift-i18n.py`

The language builder validates one pack with `--check CODE`, or builds one or more
standalone localized scripts with `--langs CODE,...`. `--into DIR` selects the
output directory and `--name FILE` selects the generated filename.

```bash
python3 m8shift-i18n.py --check fr
python3 m8shift-i18n.py --langs fr,es --into ./dist
```

### `m8shift-e2e.py`

The end-to-end harness requires one Markdown `CASE`. It is hermetic by default;
`--live` is explicitly gated, `--keep` retains the temporary directory, and
`--m8shift-py PATH` selects the engine under test.

```bash
python3 m8shift-e2e.py tests/e2e/arithmetic.md
python3 m8shift-e2e.py tests/e2e/arithmetic.md --keep
```

### `m8shift-aliases.py`

With no options, this prints portable `m8shift` and `m8shift-top` aliases. `--write`
installs the marked block; `--shell SHELL` selects `auto`, `bash`, `zsh`, or
`git-bash`; `--rc FILE` overrides the destination.

```bash
python3 m8shift-aliases.py
python3 m8shift-aliases.py --write --shell zsh
```

## Installation and automation

### `install.sh`

The Bash installer downloads or copies the core and selected companions, verifies
checksums by default, and runs `init`. Main parameters are `--dir DIR`, `--agents
A,B`, `--name NAME`, `--lang CODE`, `--source-dir DIR`, component opt-outs,
verification controls, and `--dry-run`. Optional RTK and Headroom setup is explicit.

```bash
bash install.sh --agents agent-a,agent-b
bash install.sh --dir ./my-project --name my-project --dry-run
```

A flag without its required value exits 1 and prints a correct `try: bash
install.sh FLAG VALUE --dry-run` hint.

### `install.ps1`

The PowerShell installer provides the same core install path with `-Dir`, `-Agents`,
`-Name`, `-Lang`, `-SourceDir`, component opt-outs, verification controls, and
`-DryRun`. Use `-Help` for its full usage page.

```powershell
.\install.ps1 -Agents agent-a,agent-b
.\install.ps1 -Dir .\my-project -Name my-project -DryRun
```

### `examples/headless_runner.py`

The reference runner launches exactly one agent command whenever its lane is
eligible. The required shape is `headless_runner.py AGENT [options] --cmd COMMAND
[ARG ...]`. Important controls include `--once`, `--start-on-idle`,
`--resume-working`, timeout/backoff values, runtime paths, and lifecycle logging.

```bash
python3 examples/headless_runner.py agent-a --once \
  --cmd codex exec --full-auto
```

Omitting `AGENT` or `--cmd` prints the full runner help and a valid required
invocation before exiting 2.

### `scripts/watch-status.sh`

This thin wrapper forwards all arguments to `m8shift.py watch`. `M8SHIFT_ROOT`
selects the relay and `M8SHIFT_ENGINE` overrides engine discovery.

```bash
scripts/watch-status.sh --for agent-a --changes-only
```

### `scripts/m8shift-self-update.py`

This operator-gated refresh tool requires `--source DIR` and `--target DIR`.
`--expected-ref REF` selects the authority ref; without `--apply` it performs the
dry-run only.

```bash
python3 scripts/m8shift-self-update.py \
  --source ./release --target ./my-project --apply
```

## Diagnostics and repository maintenance

### `scripts/scrub-check.py`

The read-only scanner checks Git tip and history against a confidential denylist.
Use `--repo DIR`, `--denylist FILE`, `--no-history`, `--refs-pull`, repeatable
`--range A..B|SHA`, `--max-commits N`, and local-only `--verbose`.

```bash
python3 scripts/scrub-check.py --repo . \
  --denylist ~/.config/m8shift/denylist.txt
```

### Benchmarks and documentation generator

These maintainer entry points also provide complete `--help` output and fabricated
examples:

| Script | Parameters | Example |
|---|---|---|
| `scripts/benchmark-startup.py` | `--runs N`, repeatable `--candidate NAME=EXECUTABLE`, `--json` | `python3 scripts/benchmark-startup.py --runs 50 --json` |
| `scripts/benchmark-status-scale.py` | `--real-root DIR`, `--python PATH`, `--runs N`, `--sizes N,...`, `--body-bytes N` | `python3 scripts/benchmark-status-scale.py --sizes 1000,5000 --runs 15` |
| `scripts/benchmark-scrub-check.py` | `--terms N,...`, `--commits N,...`, `--repeats N`, `--json PATH` | `python3 scripts/benchmark-scrub-check.py --terms 1,10 --commits 100` |
| `scripts/gen_docs.py` | `--version` | `python3 scripts/gen_docs.py` |

## Usage adapter examples

The three executable usage adapters emit normalized JSON and fail open to an empty
snapshot. `claude-oauth-usage.py` and `codex-ratelimits.py` accept no runtime
arguments; both now support `--help` and reject unknown arguments with exit 2.
`tokscale-spend.py [AGENT]` accepts an optional fabricated provider-lane label.

```bash
python3 examples/usage-adapters/claude-oauth-usage.py
python3 examples/usage-adapters/codex-ratelimits.py
python3 examples/usage-adapters/tokscale-spend.py agent-a
```
