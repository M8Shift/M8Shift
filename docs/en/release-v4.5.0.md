# v4.5.0 integration candidate

## Status and version

**4.5.0 is an unreleased Revision candidate**, based on the public v4.2.0 lineage.
The integration branch is `release/4.5.0-integration`; [PR #18](https://github.com/M8Shift/M8Shift/pull/18)
tracks its review. A version constant in source is not a published tag, successful
final CI run, or authorization to merge to `main`.

The relay format, LOCK states and one-pen authority remain compatible. Existing
commands retain their behavior and aliases. The maintained development and CI
interpreter becomes CPython **3.15.x**, while the technical Python 3.12 execution
floor remains unchanged. Older minors are not maintained or tested; they are
not newly rejected solely because this candidate centralizes its CI interpreter.
Those choices retain a Revision increment rather than introduce a Generation
compatibility break. No separate 4.3 or 4.4 release is implied by this integration
target.

## Included changes

| Source change | Result in this candidate |
| --- | --- |
| PR #6 / Forge #560 | Optional deterministic decision policy and native-routing bridge. Model tier, capability, context and effort evidence produce resolved, blocked or review-required advice; `launch=false` remains unconditional. |
| PR #7 / Forge #548 | TOP accepts `--version` without opening its dashboard. |
| PR #8 / Forge #555 | `append --body-file` aliases the compatible existing `--body` path input, with explicit help. |
| PR #9 / Forge #540 | The lease-keeper test synchronizes the child lifetime and verifies the final-beat/exit order. |
| PR #10 / Forge #552 | Turn lookup is session-aware and refuses ambiguous historical matches. |
| PR #11 / Forge #556 | The headless runner diagnoses a quoted shell command and preserves explicit shell-free argv. |
| PR #12 / Forge #529 | Fleet fixtures register and clean their own subprocesses, avoiding detached test listeners after the suite. |
| PR #13 / Forge #561 | The stale-lock test synchronizes actual reads and witnesses the intended replacement/unlink collision. |
| Python support consolidation | All Python CI jobs select the same 3.15.x line; one complete test job replaces the 3.12/3.14 matrix. Assertions and test coverage are retained. |
| Test collection deduplication | Remove a redundant TestCase alias so the four original installer-upgrade scenarios run once each; a class-binding guard prevents recurrence without duplicating fixture tests. |
| Static-analysis clarification | The decision CLI makes its error exit explicit; child-exit cleanup in the bridge explains its harmless process-disappearance race. |

The eight source PRs were consolidated by content before their aggregate merge
into this branch. Do not merge those patches again solely to reproduce their
original individual histories.

## Decision-engine limits

The engine and bridge are command-line companions outside the core. Their local
catalog checks do not probe provider availability, exercise live provider effort
mappings, or establish recommendation quality. A resolved plan does not grant
execution, write, reviewer or merge authority. Critical or otherwise constrained
plans continue to require the relevant review or operator decision.

The separate local backlog contains additional Advisor/JEV, review-evidence,
quota, lifecycle, publication-gate and onboarding work. That entire backlog is
**not** included in this candidate. Private Forge branches and historical data
also require their own content comparison and publication review; this release
does not import their history implicitly.

## Validation gates

Record the final candidate commit and tree in PR #18 together with the completed
single-interpreter test result, skips, platform limitations, checksum verification
and review findings. A successful earlier 3.12/3.14 run establishes the earlier
commit only; it is not evidence for a later version or interpreter migration.

The CodeQL analysis job finishing successfully is distinct from the CodeQL
findings check passing. Both the full CI result and outstanding review findings
must be assessed before release. The final candidate still requires explicit
maintainer approval for the exact PR and head before merging to `main`.

## Upgrade and operator impact

Use Python 3.15 for maintained installations and development environments. Keep
the core, selected companions and runners from one verified source checkout;
their `VERSION` values and checksum manifest advance together to 4.5.0. Recreate
a development virtual environment when changing Python minor versions rather
than reusing a previous interpreter's environment.

An operator updating an adopted relay should keep the existing explicit pause,
verified kit-update and resume procedure. A source version change does not
upgrade resident processes by itself; restart selected listeners and dashboards
through the existing governed lifecycle commands after their kit update. No
relay reset, history rewrite, new LOCK state or Generation override is introduced
by this candidate.

Protocol impact: **no** for this release-identity and interpreter-policy update.
The included fixes restore existing session lookup and argv contracts; the new
decision tools remain advisory and leave relay authority unchanged.
