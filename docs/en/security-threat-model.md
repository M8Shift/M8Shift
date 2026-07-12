# Security threat model

M8Shift coordinates agents but contains no model and serves no web application.
Relay text, skill files, adapter output, and repository contents are attacker-
controlled inputs; the pen, local secrets, integrity, and bounded execution are
the protected assets.

| Framework | Surface and control | Status | Executable evidence |
|---|---|---|---|
| LLM01 Prompt Injection; ATLAS AML.T0051/T0054 | Relay ask/body is untrusted data and cannot grant the degree-1 pen or bypass claim/write/append. | control+test | `test_LLM01_prompt_injection_relay_text_cannot_grant_pen` |
| LLM02 Insecure Output Handling | Doctor sanitizes untrusted skill and adapter text before terminal rendering. | control+test | `test_LLM02_insecure_output_ansi_is_stripped` |
| LLM05 Supply Chain | Runtime is stdlib-only; actions are SHA-pinned and tracked release files are checksummed. | control+test | `test_LLM05_supply_chain_runtime_is_stdlib_only` plus CI `sha256sum -c` |
| LLM06 Sensitive Information Disclosure; ATLAS AML.T0057 | JSON underscore keys are filtered recursively; hygiene labels are hashed and scrub-check redacts terms. | control+test | `test_LLM06_sensitive_information_denylist_label_is_hashed` |
| LLM07 Insecure Plugin Design | Foreign skills are inert-by-default and parsed with bounded, whole-file fail-open validation. | control+test | `test_LLM07_insecure_plugin_parser_is_bounded` |
| LLM08 Excessive Agency | Companions are advisory and cannot acquire relay write authority; the mutex has degree one. | by-construction | `test_LLM08_excessive_agency_mutex_has_one_holder` |
| LLM10 Unbounded Consumption | Adapter reads have a cap+1 memory ceiling, kill on overflow, and timeouts. | control+test | `test_LLM10_unbounded_consumption_caps_skill_input` |

## Explicitly out of scope

- The OWASP Web Top 10 is not the governing model because M8Shift has no HTTP
  server, authentication, sessions, or database. Injection, components, and
  integrity concerns that do apply are covered by the controls above and CI.
- ATLAS model poisoning, training-data manipulation, and inference evasion are
  out of scope because M8Shift neither trains nor hosts a model.
