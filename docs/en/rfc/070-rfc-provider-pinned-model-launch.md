# RFC 070 — Provider-pinned model launch

- **Status:** implemented (#86, 2026-07-15)
- **Scope:** additive provider-registry fields, fail-closed managed launch argv,
  and model provenance propagation through the listener and reference runner.
- **Builds on:** [RFC 014](014-rfc-provider-management.md),
  [RFC 028](028-rfc-headless-command-templates.md),
  [RFC 047](047-rfc-headless-liveness-runner-listener.md), and
  [RFC 056](056-rfc-self-declared-agent-model-provenance.md).
- **Prepares:** the adapter/control-plane work in
  [RFC 067](067-rfc-detached-vendor-neutral-cli-orchestration.md).

## Problem

A provider row previously selected a CLI but not a model. Consequently two agent
identities using the same CLI could silently run the CLI's global/default model,
making model-specific lanes and later capability/cost routing ineffective.

## Registry contract

`m8shift.providers.v1` remains additive. An agent row may contain:

```json
{
  "name": "codex",
  "provider": "openai-codex",
  "model": "operator-selected-model-id",
  "profile": "optional-safe-profile",
  "effort": "optional-safe-effort",
  "argv": ["codex", "exec", "$M8SHIFT_PROMPT"]
}
```

`model` uses the same 1–128-character `MODEL_ID_RE` as RFC 056: an ASCII
alphanumeric first, then ASCII alphanumerics or `_.:@/+~-`. Optional `profile`
and `effort` are bounded by the same safe-token character class. Scaffolds and
examples write `"model": "UNSET"`; this is a visible migration sentinel, not a
valid model id.

For managed `openai-codex` and `anthropic-claude` rows, any selected non-empty
argv is launchable and therefore requires a valid model pin. `providers check`,
`providers render`, and `listener start --provider` fail closed when the pin is
missing, invalid, or `UNSET`. A managed interactive/local legacy row with no argv
remains readable and receives a warning. Custom providers retain explicit argv
authority and are not assigned guessed model flags.

## Single-source argv compilation

Both `providers render` and `listener start --provider` use the same pure argv
compiler. Managed templates must contain exactly one literal
`$M8SHIFT_PROMPT` item. The compiler inserts options immediately before that
item and then performs literal item substitution; subprocess launch remains
`shell=False`.

- `openai-codex`: optional `--profile PROFILE`, mandatory `--model MODEL`, then
  optional `--config model_reasoning_effort="EFFORT"`.
- `anthropic-claude`: mandatory `--model MODEL`, then optional
  `--effort EFFORT`.

Even when a Codex profile is present, `--model` is emitted so a stale profile
cannot override the provider-row pin. Base and platform argv arrays may not
embed managed model/profile/effort selectors; validation directs the operator
to move those values into their provider fields. Platform selection occurs
before the same compilation step.

Gemini and Vibe flag spellings are intentionally deferred until their adapter
contracts and supported CLI versions are proven. No guessed vendor flag enters
the generic runtime.

## RFC 056 reconciliation

The listener normalizes the validated row model into its plan and invokes the
reference runner with `--agent-model MODEL`. The runner revalidates the value,
records it additively as `agent_model` in the immutable run plan, and sets
`M8SHIFT_AGENT_MODEL=MODEL` directly in the child environment. This direct value
wins over any conflicting ambient allowlisted declaration.

The two facts have deliberately different authority:

- RFC 070 selects the model requested for this provider launch.
- RFC 056 records what the launched process declares as self-declared,
  unverified provenance.

Neither mechanism attests the provider's actual execution, grants permission,
changes the relay identity, decides RFC 039 routing, or establishes billing
truth. Manual `--cmd-file` launches remain compatible and may still self-declare
through their explicitly allowed environment.

## Acceptance criteria

1. Scaffold/list/show expose `model`; launchable managed `UNSET` rows fail with
   an actionable diagnostic.
2. Boundary-valid model ids pass; missing, null, whitespace/control, and
   overlength values fail before process work.
3. Codex and Claude render exact shell-free argv for plain/profile/effort and
   platform-selected templates, with one literal prompt item.
4. Embedded competing selectors and malformed prompt markers are rejected.
5. Listener dry-run shows compiled argv plus `--agent-model`; missing pins write
   no listener state.
6. The immutable runner plan records the pin and a hermetic child observes it
   overriding a conflicting ambient value.
7. Custom providers, non-launchable legacy rows, and manual cmd-file profiles
   preserve their prior authority and compatibility.
