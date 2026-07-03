# RFC 046 — Interactive/headless modes and runner install

- Status: draft
- Date: 2026-07-03
- Origin: operator feedback after dogfooding showed that `wait` correctly blocks a shell process but does not wake a pure interactive chat UI; a fresh adopted project also lacks the shipped headless runner and `watch-status.sh`
- Builds on: [RFC 020 Headless runner hardening](020-rfc-headless-runner-hardening.md), [RFC 021 Pause resume](021-rfc-pause-resume.md), [RFC 027 Notifications](027-rfc-notifications.md), [RFC 044 Complete initialization and companion install](044-rfc-complete-init-companion-install.md), [RFC 045 Module reference and examples](045-rfc-module-reference-examples.md)
- Related: [RFC 035 Interactive listener gap](035-rfc-interactive-listener-gap.md), [RFC 040 AI session usage monitoring](040-rfc-ai-session-usage-monitoring.md)

## Summary

M8Shift's `wait` command works: it blocks a shell process until the requested agent's
turn. The failure seen during dogfooding is one layer above the protocol: some agent
surfaces re-invoke the agent when a background process completes, while pure chat UIs
do not. Therefore a shell wait can be a real autonomous listener in a headless
runner, but only a protocol marker in an interactive UI.

This RFC makes that distinction explicit:

- two execution modes are named and surfaced: `interactive` and `headless`;
- status/watch and generated anchors tell the agent which mode it is expected to
  operate in, defaulting honestly to `interactive` when unknown;
- agents get a hard status-guard rule: never announce baton state from memory;
- interactive agents emit an honesty message instead of claiming autonomous listening;
- `init` / companion install can copy the shipped headless runner and `watch-status.sh`
  into adopted projects;
- `doctor` can detect when a headless loop is expected but the runner scripts are absent;
- `status` / `watch` headers include project name and cwd so multiple terminal tabs are
  distinguishable.

## Problem

The current documentation says agents should keep `wait <agent>` armed when the relay is
not `DONE`. That is correct only if something re-enters the agent after the wait process
returns.

Observed surfaces differ:

| Surface | What `wait` does | Does the model wake automatically? | Operational mode |
|---------|------------------|------------------------------------|------------------|
| `examples/headless_runner.py` launching `claude -p`, `codex exec`, cron, CI | blocks a process and then invokes the agent command | yes, by the runner | `headless` |
| Claude Code UI with background-task completion behavior | blocks a managed process and the harness re-enters the UI when it completes | yes, harness-dependent | `headless` behavior |
| Pure chat / VS Code chat UI without re-entry | blocks a shell process only | no | `interactive` |

If an interactive agent says "I will keep listening" and then the chat turn ends, that is
false. At the next human resume it can re-check status, but it cannot continue the loop
autonomously.

There is also a packaging gap. M8Shift ships:

```text
examples/headless_runner.py
scripts/watch-status.sh
```

but `init` and RFC 044 companion install do not copy them into a newly adopted project.
The operator therefore sees "use the headless runner" but the project has no runner.

## Terminology

### Interactive mode

`interactive` means the LLM turn ends when the UI response ends. A background shell
process may keep running, but the model will not be re-invoked unless a human or host UI
resumes it.

An interactive agent may:

- run `status --for <agent>`;
- run `wait <agent> --once` or `status` when a human resumes the session;
- tell the operator what to run next.

It must not claim it is autonomously listening after the chat response ends.

### Headless mode

`headless` means an external process owns the loop and invokes the agent command when
the relay is ready. Examples: `examples/headless_runner.py`, cron, CI, or a UI harness
that re-enters the agent after a background wait completes.

A headless runner may:

- run `wait <agent>` in a real loop;
- invoke one model turn when the wait completes;
- refresh the lock before TTL expiry during long turns;
- emit runtime run events and post-run verification.

The mode describes the host harness, not the model vendor. Claude, Codex, Gemini, Vibe,
or any cooperative agent can run in either mode if the surrounding harness supports it.

## Hard status-guard rule

Agents must never announce baton state from memory.

Before any response that mentions one of these facts:

- holder;
- state;
- `AWAITING_*`;
- `WORKING_*`;
- whose turn it is;
- whether the agent is waiting/listening;
- whether a lock is stale;

the agent must immediately run one of:

```bash
python3 m8shift.py status --for <agent>
python3 m8shift.py status --for <agent> --json
```

or re-read the current `M8SHIFT.md` LOCK block from disk. Stale conversation context is
not evidence.

This rule belongs in:

- `docs/en/agents-guide.md`;
- generated `CLAUDE.md` / `AGENTS.md` stanzas;
- `M8SHIFT.protocol.md` operational core;
- `M8SHIFT.protocol-reference.md`;
- module docs for `core-relay.md` and `runtime.md`.

## Interactive honesty message

When an interactive agent reaches the end of a response and the relay is not `DONE`, it
should say a short truth-preserving message:

```text
M8Shift is not DONE. I am running in interactive mode: I do not stay autonomously
listening after this chat turn ends. On the next human resume I will re-run
`python3 m8shift.py status --for <agent>` before acting. For hands-off operation,
run the headless runner.
```

The message should include the current status only if it was read immediately before the
message. It should not say "Claude has the pen" or "Codex is waiting" from memory.

## Status/watch mode surfacing

Add a display-only run-mode hint to `status` and `watch`.

CLI:

```bash
python3 m8shift.py status --for codex --mode interactive
python3 m8shift.py status --for claude --mode headless
python3 m8shift.py watch --for codex --mode interactive
```

Environment fallback:

```text
M8SHIFT_AGENT_MODE=interactive|headless
```

Precedence:

```text
--mode > $M8SHIFT_AGENT_MODE > .m8shift/agent-modes.json > unknown
```

`unknown` must be treated like `interactive` for honesty: do not claim autonomous
listening.

Human status output adds:

```text
  mode     interactive
```

JSON status output adds:

```json
{
  "agent_mode": "interactive",
  "agent_mode_source": "cli"
}
```

This is advisory display data. It does not affect claimability or routing.

## Agent mode config

Optional local config:

```text
.m8shift/agent-modes.json
```

Schema:

```json
{
  "schema": "m8shift.agent_modes.v1",
  "agents": {
    "claude": {
      "mode": "headless",
      "runner": "examples/headless_runner.py"
    },
    "codex": {
      "mode": "interactive"
    }
  }
}
```

The file is local state under `.m8shift/`, ignored by the existing `.gitignore` block.
It should be optional. Missing file = `unknown`.

`m8shift-runtime.py watch` may also write equivalent presence data later, but core
`status` should not depend on runtime sidecars for this feature.

## Project/cwd in status and watch headers

Feedback A: current `watch` headers show only the timestamp, which is not enough when
several terminals are open. `status` and `watch` should surface the project identity.

Human output:

```text
m8shift.py v3.44.0
project  Example Project
cwd      ~/code/example-project
```

`watch` header:

```text
── watch 2026-07-03T14:20:00Z · Example Project · /Users/.../Example Project ──
```

JSON status output:

```json
{
  "project": "Example Project",
  "cwd": "~/code/example-project",
  "root": "~/code/example-project"
}
```

Project name resolution:

1. latest `M8SHIFT.sessions.jsonl` start event `project`;
2. title/seed project name if available;
3. `basename(HERE)`.

`cwd` is the process current working directory. `root` is the resolved relay root (`HERE`
or `$M8SHIFT_ROOT` rebased root).

## Runner install gap

Extend RFC 044 companion install with a multi-file selector.

Selectors:

| Selector | Copies | Version rule |
|----------|--------|--------------|
| `runner` / `--with-runner` | `examples/headless_runner.py`, `scripts/watch-status.sh` | Python runner: `VERSION == m8shift.py VERSION`; shell wrapper: sha256 provenance only |

`--full` should include `runner` because it is operational glue for hands-off use.
`e2e` remains explicit-only.

Destination should preserve relative paths by default:

```text
examples/headless_runner.py
scripts/watch-status.sh
```

Rationale: documentation already points to those paths, and operators expect to run
the same commands in adopted projects. Because `examples/` and `scripts/` may be
project-owned, the RFC 044 no-clobber rules apply strictly:

- absent destination => copy atomically;
- byte-identical destination => up to date;
- edited destination => refuse unless `--force-companions`;
- destination newer Python `VERSION` => never downgrade;
- shell wrapper has no `VERSION`, so use recorded sha256 and refuse edited copies unless
  forced;
- directory/symlink/non-regular destination => hard error before mutation.

Manifest extension:

```json
{
  "schema": "m8shift.kit.v1",
  "companions": [
    {
      "name": "runner",
      "script": "examples/headless_runner.py",
      "version": "3.44.0",
      "sha256": "…",
      "copied_at": "2026-07-03T14:20:00Z",
      "source": "/release/examples/headless_runner.py"
    },
    {
      "name": "runner",
      "script": "scripts/watch-status.sh",
      "version": null,
      "sha256": "…",
      "copied_at": "2026-07-03T14:20:00Z",
      "source": "/release/scripts/watch-status.sh"
    }
  ]
}
```

Implementation note: if manifest entries are keyed only by `name`, extend the key to
`(name, script)` before adding multi-file companions.

## Runner doctor checks

Core `doctor` should warn when a headless loop is expected but helper files are missing
or skewed.

Signals that a headless loop is expected:

- `.m8shift/agent-modes.json` marks any agent `mode=headless`;
- `.m8shift/kit.json` lists `runner`;
- runtime presence reports `mode=headless` in a future runtime integration.

Findings:

| Check | Severity | Condition | Fix |
|-------|----------|-----------|-----|
| `kit.runner_missing` | warning | headless expected, `examples/headless_runner.py` missing | `m8shift.py init --with-runner --companion-source <release>` |
| `kit.watch_status_missing` | warning | headless expected, `scripts/watch-status.sh` missing | same |
| `kit.runner_version_skew` | warning | runner `VERSION` differs from core | copy matching release runner |
| `kit.watch_status_hash_drift` | info | shell wrapper hash differs from manifest | inspect local edit or force-copy |

The checks remain advisory. Missing runner does not make the core relay invalid; it only
means autonomous headless listening is not actually available.

## Generated agent instructions / anchors

The generated stanza should include:

```text
Execution mode:
- If your host is headless or re-invokes you after wait completes, set
  M8SHIFT_AGENT_MODE=headless and keep the runner/wait loop armed.
- If your host is an interactive chat UI, set or assume
  M8SHIFT_AGENT_MODE=interactive. Do not claim autonomous listening after your
  response ends; on human resume, re-run `m8shift.py status --for <you>`.

Status guard:
Never report holder/state/turn ownership from memory. Re-read status immediately
before mentioning the baton.
```

The protocol core should keep this compact; the protocol reference can include the
longer explanation and examples.

## Implementation phases

### Phase A — status honesty and project identity

- Add `--mode` to `status` and `watch`.
- Add `$M8SHIFT_AGENT_MODE` fallback.
- Add project/cwd/root display to status and watch.
- Add JSON fields.
- Add tests for project fallback and mode precedence.

### Phase B — generated instructions

- Update `PROTOCOL["en"]`, `PROTOCOL_REFERENCE["en"]`, `STANZA`, and generated anchors.
- Update `docs/en/agents-guide.md`.
- Add tests that the status-guard sentence and interactive honesty rule appear in the generated
  protocol/stanza.

### Phase C — runner companion install

- Add `runner` selector and `--with-runner`.
- Include `runner` in `--full`.
- Copy `examples/headless_runner.py` and `scripts/watch-status.sh`.
- Extend `.m8shift/kit.json` to support multi-file companions keyed by `(name, script)`.
- Add no-clobber/version/sha tests.

### Phase D — doctor integration

- Add runner expected/missing/skew/hash findings.
- Add JSON doctor fields.
- Add tests for headless expected + missing runner.

## Tests

Minimum regression tests:

1. `status --for codex --mode interactive` prints `mode interactive` and JSON `agent_mode`.
2. `$M8SHIFT_AGENT_MODE=headless status --for claude` is surfaced when `--mode` is absent.
3. invalid mode is refused.
4. `watch --once --for codex --mode interactive` header includes project name and cwd.
5. status JSON includes `project`, `cwd`, and `root`.
6. generated `CLAUDE.md` / `AGENTS.md` include the hard status-guard rule.
7. generated anchors include the interactive honesty message.
8. `init --with-runner --companion-source <release>` copies both runner files.
9. `init --full` includes runner but still excludes `e2e`.
10. shell wrapper is tracked by sha256 in `.m8shift/kit.json`.
11. edited `scripts/watch-status.sh` is not clobbered without `--force-companions`.
12. destination symlink/directory for either runner file is refused before mutation.
13. `doctor --json` warns when `agent-modes.json` expects headless but runner files are absent.

## Non-goals

- No daemon.
- No IDE extension.
- No guarantee that a proprietary UI can be woken by M8Shift.
- No change to the one-pen relay.
- No automatic force recovery.
- No model/provider-specific runner logic in core.

## Definition of done

- A human can tell from `status`/`watch` which project/cwd a terminal belongs to.
- An agent cannot honestly claim autonomous listening in interactive mode.
- Headless operation has a copied, version-aligned runner in a fresh adopted project.
- `doctor` reports when a configured headless mode lacks its runner.
- The generated instructions make the distinction without requiring extra human explanation.
