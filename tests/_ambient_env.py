"""Ambient-environment isolation for the whole suite (#288).

Every test module imports this **before** it imports anything from the product, and
`conftest.py` imports it too. Two guards in `tests/test_m8shift.py` keep it honest:
one proves the import really precedes the product import in every module, the other
re-derives the variable list from the tracked sources.

Why a shared module rather than a block in the largest test file
---------------------------------------------------------------
The first version purged inside `tests/test_m8shift.py`, which works only when that
file is collected. Measured with `M8SHIFT_ROOT` exported: `tests/test_worktree.py`
alone gave 0 passed / 67 failed against 68 co-collected, and
`tests/test_m8shift_context.py` 1 passed / 43 failed against 45. A green full suite
was hiding per-file runs that were catastrophically red, and `python3 -m unittest` —
the runner CONTRIBUTING documents — never loads a conftest.

Why before the product import
-----------------------------
`m8shift.py` reads `M8SHIFT_ROOT` at module scope and calls `configure_root()`,
rebasing eleven module-level paths; `m8shift-runtime.py` resolves ~20 more the same
way. Popping the variable afterwards removes the variable and leaves every path
rebased for the rest of the run.

Why not inside the CLI helpers
------------------------------
Three tests deliberately set these values through `mock.patch.dict(os.environ, …)`
and depend on propagation to the subprocess. At call time a patched variable and an
inherited one are indistinguishable, so a helper-level strip would break exactly
those.

Why the list is discovered by NAME and not by detecting reads
-------------------------------------------------------------
This enumeration was wrong four times, and every time the instrument was narrower
than the thing it measured:

     6 of 40   grepped only os.environ.get("M8SHIFT_…") literals
    13 of 40   scanned only m8shift.py and m8shift-runtime.py
    32 of 40   scanned eight hand-listed files
    37 of 40   swept tracked sources but still classified "is this a read",
               missing env.get("M8SHIFT_CLAUDE_CREDENTIALS") — a read through a
               mapping passed in as a parameter

The lesson is not to write a better read-detector. It is that classifying reads is
the wrong burden to carry: **any `M8SHIFT_*` name appearing in a tracked non-test
source is purged**, whether or not this file can tell how it is consumed.
Over-purging costs nothing here — these are all opt-in knobs, and a test that wants
one sets it explicitly — while under-purging is the defect. A name-detector is
total; a read-detector never was.
"""

import os

AMBIENT_ENV_VARS = (
    "M8SHIFT_ADAPTER_MODE",
    "M8SHIFT_ADAPTER_MODE_ARGS",
    "M8SHIFT_AGENT",
    "M8SHIFT_AGENT_EFFORT",
    "M8SHIFT_AGENT_MODEL",
    "M8SHIFT_BIN",
    "M8SHIFT_CLAUDE_CREDENTIALS",
    "M8SHIFT_DENYLIST",
    "M8SHIFT_E2E_AGENT_CMD",
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
    "M8SHIFT_LIVE_E2E",
    "M8SHIFT_META_KEYS",
    "M8SHIFT_NO_ALT_SCREEN",
    "M8SHIFT_PROMPT",
    "M8SHIFT_PUBLISH_ATTESTATION",
    "M8SHIFT_RESUME_WORKING",
    "M8SHIFT_ROOT",
    "M8SHIFT_RTK",
    "M8SHIFT_RTK_ADOPTION_THRESHOLD",
    "M8SHIFT_RUNNER_VERSION",
    "M8SHIFT_RUN_ID",
    "M8SHIFT_SCRUB_ENFORCE",
    "M8SHIFT_TURN",
)


def purge():
    """Remove every ambient M8SHIFT_* variable. Idempotent, safe to call twice."""
    for name in AMBIENT_ENV_VARS:
        os.environ.pop(name, None)


purge()
