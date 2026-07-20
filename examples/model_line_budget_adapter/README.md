# RFC 077 model-line evidence adapter example

This external example package contains the fixture-safe implementation boundary
for RFC 077 Slices A through D. It is never imported by the passive relay core;
the runtime companion imports only the Slice D boundary controller immediately
before a managed provider launch.

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
adapter subprocess, live vendor switch, or relay mutation in this package.
`listener.py` accepts only an explicit disabled, fixture-only policy; writes the
attempt/evidence/decision checkpoint; and returns a next-invocation plan to the
runtime. Without that opt-in document the boundary is a true no-op and writes no
sidecars. The policy never invokes an adapter: a valid or corrupt usage hold
stops evaluation before evidence is inspected. A policy whose active provider
disagrees with the managed provider clean-halts before provider launch.
Supplying live retrieval or enabling an entry for provider traffic belongs to
RFC 077 Slice E and requires separate operator authorization.

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
