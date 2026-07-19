# RFC 077 model-line evidence adapter example

This external example package contains the fixture-safe implementation boundary
for RFC 077 Slices A through C. It is not imported by the passive relay core or
the runtime companion.

`base.py` owns the normalized evidence dataclasses and strict serialization.
`vendors.py` adds Anthropic, OpenAI, Google, and Mistral subclasses that accept a
bounded, injected response retriever. The checked-in response fixtures exercise
success, throttle, malformed, and absent-authentication shapes for every vendor.
`policy.py` consumes those normalized facts in a pure eight-rule state machine.
It validates an explicit ordered set of RFC 070 model pins, emits a dry-run plan
that always has `replay=False`, and can persist its schema-shaped audit record
with create-exclusive atomic semantics. Its reconstruction helper verifies the
attempt-plan and closed relay-turn hashes from the named durable checkpoint.

All entries in `VENDOR_ADAPTER_REGISTRY` are `enabled=False` and
`retrieval="fixture_only"`. There is no provider SDK, credential lookup, socket,
subprocess, CLI entry point, live switch, listener integration, or relay mutation
in this package. The policy never invokes an adapter: a valid or corrupt usage
hold stops evaluation before evidence is inspected. Supplying live retrieval or
enabling an entry for provider traffic belongs to RFC 077 Slice E and requires
separate operator authorization.

The vendor mappings deliberately preserve uncertainty:

- Anthropic documented model groups may have a null provider bucket id.
- OpenAI shared groups require both a documented mapping and a provider-derived
  bucket id; subscription-product windows remain unknown.
- Google model-dimensioned cloud quota can be exact, while console-only data is
  diagnostic and unknown.
- Mistral configured per-model limits plus Admin history populate only
  `estimate`; provider-reported remaining capacity stays null.

Malformed data, missing authentication, retrieval failure, or a refusal without
the vendor's bounded applicability fields emits valid `unknown` evidence with no
invented headroom.
