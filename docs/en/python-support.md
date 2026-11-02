# Python support and migration

## One maintained interpreter series

M8Shift maintains **CPython 3.15.x**, using the normal GIL build and the latest
stable bugfix release. [`.python-version`](../../.python-version) selects `3.15`
for development tools and all Python GitHub Actions jobs. `check-latest: true`
keeps that minor current without silently moving the project to 3.16, a
prerelease, or a free-threaded build.

The choice follows the maintainer's decision on 2026-10-28 to maintain one Python
minor. At that date, [Python's official downloads](https://www.python.org/downloads/)
listed [3.15.2](https://www.python.org/downloads/release/python-3152/) as the latest
stable release; 3.16 was a prerelease. Future patch updates within 3.15 are part of
this policy. A later minor requires an explicit support-policy update and a full
suite result rather than a floating `3.x` selection.

The full pytest suite runs **once per CI execution**. Compilation, checksums,
data hygiene, focused decision tests, and Python SAST use the same minor. No test
assertions or suite selection are removed by this migration. CodeQL extracts
Python source directly; its own analysis tooling is not another supported
M8Shift interpreter lane. CI logs record the actual patch version used.

## Compatibility is separate from support

The existing **3.12 technical minimum** is retained. Installers may still use an
older compatible interpreter, or an explicitly selected compatible interpreter,
but print that it is an **unsupported compatibility fallback**. `doctor --install`
reports both the technical floor and whether the running minor is maintained.
This avoids deliberately breaking an existing relay merely to reduce the CI
matrix. It does not promise correctness on 3.12, 3.13, 3.14, future minors, PyPy,
or free-threaded Python, and none of those receives a separate CI or backport lane.

M8Shift remains a stdlib-only, copyable core. There is no required virtual
environment or package installation for ordinary core/runtime use. The
`.python-version` file is repository tooling, not a new file that must accompany
the standalone core. Installers and the standalone install diagnostic carry the
same documented minor explicitly because each must work without the checkout.

## Moving an installation

1. Install a current Python 3.15 bugfix release from
   [python.org](https://www.python.org/downloads/) or the operating system's
   supported package channel. Do not replace an OS-managed Python in place.
2. Check `python3.15 --version` on POSIX or `py -3.15 --version` on Windows.
3. Point the existing launcher, shell alias, service configuration, or virtual
   environment at that interpreter. A running listener keeps its current process
   and interpreter until it is deliberately restarted by its owner; changing a
   file on disk does not upgrade that process.
4. Run the existing relay's read-only diagnostics through the selected
   interpreter, for example `python3.15 m8shift.py doctor --install`. Preserve the
   relay and its state; an interpreter change does not require `init --force`.

The Bash installer prefers `python3.15`, then any generic `python3`/`python` that
actually reports 3.15. An explicit `PYTHON` remains authoritative. The PowerShell
installer first tries `py -3.15` and `python3.15`, then inspects generic launchers
before using a compatible fallback. Neither installer modifies PATH or downloads
Python itself.

For development, create a fresh 3.15 environment instead of reusing an older
environment's interpreter or installed wheels:

```bash
python3.15 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r .github/requirements-ci-test.txt
python -m pytest -q
```

On Windows, create it with `py -3.15 -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1`. Test tools remain development-only. Optional
Headroom dependencies have their own Python/platform wheel availability and are
not guaranteed by the stdlib core policy; an unavailable optional helper must
remain advisory and must not prevent the core installation.

Historical release notes, RFC evidence, and recorded benchmark interpreter
versions remain historical facts. They are not additional current support lanes.

**Protocol impact: no.** The support and CI policy changes no relay format, LOCK
state, pen authority, command, or provider-selection rule. This document does not
claim a released 4.5 tag or completed CI for a commit that has not yet run.
