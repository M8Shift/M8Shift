"""Ambient-environment isolation for the whole suite (#288).

Every test module imports this **first**, before importing the engine, and
`conftest.py` imports it too so a module that forgets is still covered under
pytest. `test_every_test_module_purges_the_ambient_environment` fails when a test
file omits the import, because collection order is not a guarantee.

Why a shared module rather than a block in the largest test file
---------------------------------------------------------------
The first version of this fix purged inside `tests/test_m8shift.py`. That works
only when that file happens to be collected — adversarial review measured the
consequence with `M8SHIFT_ROOT` exported: `tests/test_worktree.py` alone gave
0 passed / 67 failed while the same file co-collected gave 68 passed, and
`tests/test_m8shift_context.py` gave 1 passed / 43 failed alone against 45 passed
together. A green full suite was hiding per-file runs that were catastrophically
red, and `python3 -m unittest` — the runner CONTRIBUTING documents — shows the same
split.

Why before the engine import
----------------------------
`m8shift.py` reads `M8SHIFT_ROOT` at module scope and calls `configure_root()`,
which rebases eleven module-level paths (`COWORK`, `LOCKFILE`, `SESSIONS`,
`MEMORY`, …). `m8shift-runtime.py` resolves ~20 more the same way. Popping the
variable after the import removes the variable and leaves every path rebased for
the rest of the run.

Why not inside the CLI helpers
------------------------------
Three tests deliberately set these values through `mock.patch.dict(os.environ, …)`
and depend on propagation to the subprocess. At call time a patched variable and
an inherited one are indistinguishable, so a helper-level strip would break
exactly those. Early is the only placement that satisfies both constraints.

Why the list is derived and not remembered
------------------------------------------
It was wrong twice. The first attempt held 6 names because it grepped only
`os.environ.get("M8SHIFT_…")` literals; the second held 13 because it scanned only
`m8shift.py` and `m8shift-runtime.py`. The real figure is below, taken from every
file that reads the environment — including `m8shift-top.py`, both installers, the
shell runners and the git hooks. `test_ambient_isolation_covers_every_engine_env_var`
re-derives it from those files and fails when a name escapes.
"""

import os

# Sources scanned by the coverage guard. Adding a file here is how a new surface
# joins the contract; the guard reads this tuple, so the two cannot drift apart.
ENV_READING_SOURCES = (
    "m8shift.py",
    "m8shift-runtime.py",
    "m8shift-top.py",
    "install.sh",
    "install.ps1",
    "scripts/watch-status.sh",
    "hooks/pre-commit",
    "hooks/pre-push",
)

AMBIENT_ENV_VARS = (
    "M8SHIFT_AGENT",
    "M8SHIFT_AGENT_EFFORT",
    "M8SHIFT_AGENT_MODEL",
    "M8SHIFT_BIN",
    "M8SHIFT_DENYLIST",
    "M8SHIFT_ENGINE",
    "M8SHIFT_HEADROOM_MODEL",
    "M8SHIFT_HEADROOM_RUNTIME_PACKAGES",
    "M8SHIFT_HYGIENE_ALLOWED_ROOTS",
    "M8SHIFT_INSTALL_BASE_URL",
    "M8SHIFT_INSTALL_CHECKSUMS_URL",
    "M8SHIFT_INSTALL_DIR",
    "M8SHIFT_INSTALL_HEADROOM",
    "M8SHIFT_INSTALL_REF",
    "M8SHIFT_INSTALL_RTK",
    "M8SHIFT_INSTALL_RTK_BASE_URL",
    "M8SHIFT_INSTALL_RTK_VERSION",
    "M8SHIFT_INSTALL_SOURCE_DIR",
    "M8SHIFT_INSTALL_VERIFY",
    "M8SHIFT_LANG",
    "M8SHIFT_LISTENER_BACKEND_PROBE",
    "M8SHIFT_LISTENER_DETACHED",
    "M8SHIFT_LISTENER_GENERATION",
    "M8SHIFT_LISTENER_LOG_MAX_BYTES",
    "M8SHIFT_NO_ALT_SCREEN",
    "M8SHIFT_PROMPT",
    "M8SHIFT_ROOT",
    "M8SHIFT_RTK",
    "M8SHIFT_RTK_ADOPTION_THRESHOLD",
    "M8SHIFT_RUNNER_VERSION",
    "M8SHIFT_RUN_ID",
    "M8SHIFT_SCRUB_ENFORCE",
)


def purge():
    """Remove every ambient M8SHIFT_* variable. Idempotent, safe to call twice."""
    for name in AMBIENT_ENV_VARS:
        os.environ.pop(name, None)


purge()
