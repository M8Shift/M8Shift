# RFC 056 — Self-declared agent model provenance

- **Status:** implemented (#43, 2026-07-13)
- **Scope:** additive, advisory model attribution in the relay snapshot, turn journal,
  activity history, and `m8shift-top` display.
- **Builds on:** [RFC 022](022-rfc-session-reports.md),
  [RFC 025](025-rfc-status-runtime.md), and
  [RFC 039](039-rfc-model-task-routing.md).

## Summary

Record the model id that an agent process declares through `M8SHIFT_AGENT_MODEL` and
surface it beside the stable roster identity. The declaration improves review and
cost/effectiveness analysis without pretending that a local environment variable is
attestation. Every human display marks model values with `* model self-declared
(unverified)` and every JSON value carries `model_source: "self_declared"`.

## Contract

The declaration is optional and bounded by `MODEL_ID_RE`: 1–128 characters, beginning
with an ASCII alphanumeric and thereafter limited to ASCII alphanumerics plus
`_.:@/+~-`. Whitespace, controls, line breaks, and marker-capable text are rejected.
Invalid or absent declarations do not fail a claim or append and are never persisted.

Valid declarations are captured on `claim` and `append` in the LOCK's compact
`models: agent=model,...` map. The map is roster-scoped, duplicate-free, validated on
load, and ordered by roster. A valid new declaration replaces only that agent's last
value; an unset declaration preserves the last safe value for the active session.

Each newly appended turn also receives an optional immutable `model` field. Historical
activity and the last-turn snapshot read that field, while current roster rows read the
LOCK map. Thus a later declaration does not rewrite historical attribution.

## Boundaries

- Agent id remains the routing and authority identity; model id is advisory provenance.
- A declaration never selects a provider, changes RFC 039 routing, grants capability,
  establishes billing truth, or proves which binary/model actually ran.
- `model` is engine-reserved so arbitrary `--field` input cannot shadow it.
- Old relays and turns without the field remain valid and render an em dash.

## Acceptance criteria

1. Valid declarations persist on claim, stamp subsequent turns, and appear on current
   agent, last-turn, and activity JSON objects with `model_source`.
2. Invalid declarations are omitted without breaking the relay.
3. Historical turn attribution is immutable and missing values remain compatible.
4. Narrow and wide dashboard layouts show the declaration with the unverified legend.
5. Model provenance never feeds mutex, routing, permissions, or capability decisions.
