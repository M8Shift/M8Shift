# RFC — Provider management

- **Status:** implemented v1 in v3.16.0 via `m8shift-runtime.py providers`
- **Scope:** optional adapter registry for agent tools and execution surfaces
- **Core invariant:** M8Shift coordinates agents; it does not become a model provider

## 1. Problem

M8Shift is intentionally provider-neutral. The roster may contain `claude`,
`codex`, `gemini`, `vibe`, or any other cooperative agent identity, but the core
does not know how to launch those tools, what permissions they need, what command
line is safe, or how their sessions should be resumed.

That neutrality is good, but an unattended or semi-automated runtime needs a
standard way to describe:

- how to run an agent once;
- what capabilities the agent is expected to have;
- which project anchor it reads;
- whether the surface is interactive or headless;
- what environment variables or credentials the host must provide;
- what safety policy applies before running it.

## 2. Decision

Provider management belongs in an optional companion layer. The core stores roster
names and enforces the pen. A provider manager maps those roster names to host
commands, capabilities, and policies.

## 3. Goals

- Keep a declarative registry of provider adapters.
- Support Claude, Codex, Gemini, Vibe, local models, browser/IDE surfaces, and
  future tools without changing `m8shift.py`.
- Describe command templates without shell interpolation.
- Declare capabilities such as `read_repo`, `write_repo`, `run_tests`,
  `network`, `image_generation`, or `legal_review`.
- Keep authentication outside the repository journal.
- Allow a runtime companion to choose the right invocation for one M8Shift turn.
- Make provider differences visible to humans before a run starts.

## 4. Non-goals

- No provider SDK inside `m8shift.py`.
- No API keys, OAuth tokens, or account metadata in `M8SHIFT.md`.
- No hosted model broker.
- No automatic provider selection by hidden scoring.
- No guarantee that a provider's output is safe or correct.
- No bypass of `claim → work → append`.

## 5. Provider registry model

The shipped companion uses a stdlib-friendly JSON registry at
`.m8shift/providers.json`:

```json
{
  "schema": "m8shift.providers.v1",
  "agents": [
    {
      "name": "codex",
      "provider": "openai-codex",
      "mode": "headless",
      "anchor": "AGENTS.md",
      "argv": ["codex", "exec", "$M8SHIFT_PROMPT"],
      "capabilities": ["read_repo", "write_repo", "run_tests"],
      "requires_env": [],
      "permissions": "workspace-write"
    }
  ]
}
```

This file is not a core protocol file. It is host/runtime configuration.

## 6. Adapter contract

Each adapter should answer:

| Question | Example |
|----------|---------|
| How is one turn started? | `["codex", "exec", "$M8SHIFT_PROMPT"]` |
| Does the surface support headless operation? | `headless`, `interactive`, `hybrid` |
| Which anchor is loaded? | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` |
| Can it run shell commands? | yes/no |
| Can it edit files? | yes/no |
| Can it be resumed automatically? | yes/no |
| How are credentials supplied? | host environment only |

The adapter starts one turn. It does not own the relay.

## 7. Prompt contract

The provider manager may build a prompt from:

- current `status --json`;
- last `peek`;
- protocol summary;
- pending operator messages;
- safety constraints;
- the exact command the agent must run first, usually `next <agent>`.

The prompt must not instruct the agent to bypass the relay. Provider-specific
prompt details belong in adapter templates, not in `M8SHIFT.md`.

## 8. Credentials and secrets

Secrets stay in the host:

- environment variables;
- provider CLI auth stores;
- OS keychains;
- CI secret stores;
- user-approved interactive sessions.

M8Shift files must remain safe to commit. If a provider manager writes runtime
state containing credentials or session ids, it must live outside tracked files
or be gitignored by default.

## 9. Capability declarations

Capabilities are advisory but useful:

```text
read_repo
write_repo
run_tests
network
browser
image_generation
legal_review
long_context
fast_review
```

A runtime may warn when a requested task needs `run_tests` but the chosen provider
does not declare it. The core must never gate `claim` or `append` on capability
metadata.

## 10. Safety rules

- Use argv arrays, not shell strings.
- Show the effective command before first run.
- Do not pass secrets through prompts.
- Do not auto-approve destructive commands.
- Require explicit human approval for publishing, deployment, payments, or
  external messages.
- Log which adapter ran which turn.

## 11. Acceptance criteria

A first implementation is acceptable when:

- a roster identity can be mapped to a provider command without editing
  `m8shift.py`;
- unsupported providers can be added by configuration;
- missing credentials fail with a clear host-side error;
- core relay files stay secret-free;
- headless and interactive providers are distinguished;
- adapter execution still performs one M8Shift turn;
- tests cover command rendering without shell injection.

## 12. Relationship to the core

The core only knows names:

```text
agents: claude,codex,gemini,vibe
```

Provider management explains what those names mean to the host. It never changes
the lock semantics.

## 13. Shipped command surface

```bash
python3 m8shift-runtime.py providers init [--agents claude,codex] [--force]
python3 m8shift-runtime.py providers list [--json]
python3 m8shift-runtime.py providers show <agent>
python3 m8shift-runtime.py providers check [agent] [--json]
python3 m8shift-runtime.py providers render <agent> --prompt "..." [--run RUN] [--json]
```

`render` substitutes only explicit placeholders such as `$M8SHIFT_PROMPT` inside
argv elements. It never evaluates a shell string.

## 14. Open questions

- Should there be a built-in registry of known anchors for common tools?
- Should adapter templates be versioned independently from the core?
- Should provider management live in the runtime control plane package rather
  than in this repository?
