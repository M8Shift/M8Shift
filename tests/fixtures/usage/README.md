# Usage fixtures

`tokscale-v4.13.0-quota-redacted.json` pins the JSON structure observed from a
real `tokscale 4.13.0 usage --json` invocation on 2026-08-12 for issue #316.

The raw response is intentionally not stored. Provider and metric labels,
container shapes, value types, and observed percentage values are preserved.
Account ids, email addresses, plan/credit text, remaining-label prose, and other
identity-bearing strings are replaced. Reset timestamps use synthetic
timezone-valid examples with the same ISO-8601 shape.

The capture command was non-interactive and did not invoke `submit`,
`autosubmit`, or `login`.

`antigravity-v2.6.0-quota-summary-redacted.json` pins the object/array shape,
field names, explicit `window` discriminator, and two-group layout observed from
Antigravity 2.6.0 on 2026-08-15 for issue #335.  Its source is the local Connect
RPC method
`exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary`; the
method is recorded here alongside the fixture, and the client version is also
recorded in the fixture's `capture` object. Keeping the long method identifier
out of the JSON preserves a literal zero-result 32+-character token-shape scan.

The captured response was checked for email addresses, token-shaped strings of
32 or more characters, and user paths before freezing.  Descriptive prose is
redacted.  Reset timestamps are synthetic future-within-window examples: the
live `gemini-5h` sample reported a full remaining fraction with a reset already
in the past, and a follow-up probe was blocked by process-inspection sandboxing.
The fixture therefore does not encode that unexplained past timestamp as normal.
Quota fractions remain sample data only; tests pin their field/type/range and
derive expectations from the fixture rather than asserting a changing value.

`antigravity-expired-window-redacted.json` is the paired freshness control. Its
synthetic observation time is 2026-08-15 14:00 UTC: the weekly reset is already
past while the five-hour reset is still future. It exists so the adapter tests
prove that an expired provider window is discarded while a fresh sibling still
maps, without depending on the machine's wall clock.
