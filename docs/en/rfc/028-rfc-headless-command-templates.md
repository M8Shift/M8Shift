# RFC — Headless command templates

**Status:** draft · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md)

## Scope

Define safe command templates for headless agent runs such as `codex exec`, `claude -p`, and other
cooperative CLIs.

Templates should produce explicit argv arrays, stable cwd, prompt hash, agent identity, run id, and
post-run relay validation. They may build on provider rendering but must keep secrets and shell
expansion out of M8Shift.

## Open design question

How much can M8Shift standardize headless templates without becoming a provider launcher or assuming
vendor-specific behavior?

Subquestions:

- Which fields are mandatory in a run plan?
- Should templates live in `.m8shift/providers.json`, workflows, or a separate companion file?
- How should platform differences be represented without shell strings?
- What is the minimum post-run validation required before reporting success?

## Non-goal

No provider SDK, API key management, or model routing in the core.
