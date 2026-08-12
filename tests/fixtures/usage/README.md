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
