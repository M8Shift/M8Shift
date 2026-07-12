---
name: ci-triage
description: Diagnose continuous-integration failures from exact failing jobs and test names before proposing a fix. Use to distinguish environment leakage, platform divergence, stale generated artifacts, and infrastructure flakes through focused local simulation.
license: Apache-2.0
metadata:
  m8shift-lane: advisory-read-only
  m8shift-report: required
---

# CI triage

Do not form a hypothesis until you have collected every failing job and the exact
failing test, check, or command name. Preserve the relevant raw error excerpt.

Classify only when evidence supports it. Useful hypotheses include inherited
environment leakage (`CI`, `HOME`, `TERM`), platform or interpreter divergence,
a stale generated artifact such as a checksum manifest, and an infrastructure
flake. This taxonomy is advisory; do not force an unfamiliar failure into it.

Reproduce the smallest named failure locally under the relevant conditions, for
example `CI=1 pytest -k '<exact test>'`. Vary one suspected condition at a time.
Report the observations, reproduction, and remaining uncertainty before proposing
a fix. Never patch an unnamed failure or broaden scope merely to make CI green.
