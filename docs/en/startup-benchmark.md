# CLI startup benchmark

M8Shift deliberately ships as a single, standard-library-only Python file. This
benchmark tests whether compiling that file would materially improve the latency
of the process-per-action relay workflow.

## Method

Run from the repository root:

```console
python3 scripts/benchmark-startup.py --runs 50
```

The script creates and initializes a temporary relay, then invokes `status --for
codex` in a new process for every sample. `first_ms` represents the first
invocation against the newly created relay (cold process and file-system state);
the median and p95 represent repeated invocations with warm file-system caches,
but still include the fresh interpreter process M8Shift pays for each action.
It compares normal source execution with an explicitly precompiled `.pyc`.
Optional standalone builds can be measured with
`--candidate NAME=/path/to/executable`.

## Result

Measured on macOS with CPython 3.14.6, 50 fresh processes per candidate:

| Candidate | First (ms) | Median (ms) | p95 (ms) | Mean (ms) |
|---|---:|---:|---:|---:|
| Source | 115.306 | 100.032 | 118.164 | 104.720 |
| Precompiled `.pyc` | 57.368 | 57.194 | 63.428 | 59.117 |

Nuitka, PyInstaller, and mypyc were not installed on the measurement host, so no
standalone binary result is claimed. `python3 -X importtime m8shift.py --version`
showed ordinary standard-library imports; it did not identify a third-party
dependency or single import that would justify changing distribution.

## Verdict

Compilation is not worth making the default distribution more complex. A `.pyc`
reduced this host's median `status` latency by about 43 ms (43%), but remains
Python-version-specific and still requires an interpreter. A standalone compiler
would replace one portable, auditable file with platform- and architecture-specific
artifacts, a build/release matrix, and a larger trust surface. That conflicts with
the project's single-file, standard-library-only installation contract for a
small absolute saving on human-paced coordination actions.

Users with unusually latency-sensitive local automation can precompile or test a
standalone build with the benchmark, but source remains the recommended release
artifact. Results are host-specific; rerun the script on the target system before
using them for an optimization decision.
