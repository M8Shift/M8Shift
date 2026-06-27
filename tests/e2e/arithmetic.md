# Deterministic arithmetic handoff

```m8shift-e2e
name: arithmetic
artifact: result.txt
expression: 19 + 23
expected: 42
```

## Tiers

The same case runs under two tiers via `m8shift-e2e.py`:

- **Tier A (default):** hermetic and deterministic. A local arithmetic stub computes the
  artifact; no model, no network. `python3 m8shift-e2e.py tests/e2e/arithmetic.md`.
- **Tier B (`--live`, opt-in):** the *same* case is produced by a real agent CLI instead
  of the stub. It is **gated** and only runs when both hold, otherwise it **skips cleanly**
  (clear message, exit 0):
  - `M8SHIFT_LIVE_E2E` is truthy (`1`/`true`/`yes`/`on`), **and**
  - `M8SHIFT_E2E_AGENT_CMD` is a resolvable argv template (shlex-split, never shell-evaluated);
    the literal token `{prompt}` is substituted with the prompt, which is also exported as
    `M8SHIFT_PROMPT`.

  Example: `M8SHIFT_LIVE_E2E=1 M8SHIFT_E2E_AGENT_CMD='codex exec {prompt}' python3 m8shift-e2e.py tests/e2e/arithmetic.md --live`.
  Network access is permitted **only** on this gated Tier B path.
