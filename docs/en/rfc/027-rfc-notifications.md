# RFC — Local notification mechanisms

**Status:** proposed (design specified; implementation deferred) · **Source:** deferred from [010-rfc-runtime-patterns.md](010-rfc-runtime-patterns.md) · **Answers:** the notification open question in [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md) (§watch, open question 2)

## Scope

Specify how the runtime companion tells an operator that something needs attention — a
turn is ready, a turn went stale, or a runtime is blocked — without turning M8Shift into
a resident gateway or coupling it to a network service. Notifications are a companion
concern; the core `m8shift.py` never notifies.

## Goal

Close the gap named in [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md):
`wait <agent>` blocks a process but cannot wake an interactive VS Code / desktop chat
UI, and `status` shows relay state, not whether a human needs to act. The companion
already computes "who is awaited and what should resume"; this RFC defines how that fact
is surfaced.

A notification **prepares a human to act**. It never claims to reliably wake a closed or
suspended proprietary UI, and it never resumes a turn by itself.

## Charter constraints

Inherits the companion charter from
[009-rfc-runtime-companion.md](009-rfc-runtime-companion.md) §Charter constraints.
Specifically:

1. **No core notifications.** Only the opt-in companion notifies; `m8shift.py` stays a
   passive single file.
2. **No daemon.** Notifications fire as one-shot side effects of the existing poll /
   `watch` loop or an explicit `notify` call — never a new resident process.
3. **No network in M8Shift.** Tiers shipped by M8Shift are local-only. Any external
   channel (Slack, email, …) is reached through an operator-owned hook command, not
   bundled code.
4. **Advisory only.** A missed, failed, or duplicate notification never blocks the relay
   and never makes a forbidden core transition legal.
5. **Removable.** All notification state lives under `.m8shift/runtime/notify/` and is
   gitignored; deleting it loses only notifications.
6. **Stdlib-only.** Local tiers use the standard library. Tiers that invoke an external
   program use `subprocess` with an argv list (never `shell=True`).

## Notification tiers

Mechanisms are layered from always-safe to explicitly opt-in. Each tier is independently
enabled in config; a tier that is unavailable degrades to the tier below it, never to an
error.

| Tier | Mechanism | Availability | Charter note |
|------|-----------|--------------|--------------|
| 0 | **stdout/stderr line + exit code** | always | pure stdlib; CI-safe; the baseline |
| 1 | **prompt artifact file** | always | writes the exact resume prompt to `.m8shift/runtime/notify/<agent>.prompt`; an editor/script can watch it |
| 2 | **terminal bell** (`\a` to a TTY) | TTY only | pure stdlib; auto-suppressed on non-TTY/CI |
| 3 | **OS notification preset** | opt-in | one-shot `subprocess` to a native notifier (`osascript`, `notify-send`, PowerShell toast); off by default; warns-and-degrades if the binary is absent |
| 4 | **operator hook command** | opt-in | one-shot `subprocess` of an operator-configured argv template; the escape hatch for external channels without M8Shift shipping a connector |

Tiers 0 and 1 are the floor: even with everything else off, the companion always prints
the event and writes the resume prompt.

## Events

The companion emits a notification on a state transition it computes from
`m8shift.py status --json` (plus presence):

| Event | Trigger |
|-------|---------|
| `turn-ready` | the relay became `AWAITING_<agent>` for a watched agent that has no live runtime |
| `stale` | a `WORKING_<agent>` lock passed its TTL, or presence for the holder went `stale` |
| `blocked` | the companion marked a runtime `blocked` (needs human action) |
| `done` | the relay reached `DONE` |

Each event carries the agent, the relay state, a one-line summary, and — for
`turn-ready` — the exact resume prompt.

## File layout

```text
.m8shift/
  runtime/
    notify.config.json        # enabled tiers + os preset + hook template (gitignored)
    notify/
      <agent>.prompt          # latest exact resume prompt (overwritten)
      <agent>.event.json      # latest event payload (overwritten)
      log.jsonl               # append-only notification audit (what fired, when, which tier)
```

`notify.config.json` example:

```json
{
  "tiers": ["stdout", "file", "bell"],
  "os_preset": "auto",
  "hook": null,
  "dedup_window_seconds": 300
}
```

- `tiers`: which mechanisms are enabled (subset of `stdout`, `file`, `bell`, `os`,
  `hook`).
- `os_preset`: `auto` (detect platform notifier), an explicit name, or omitted / `off`.
- `hook`: an argv list template for tier 4, or `null`. Placeholders (`{agent}`,
  `{event}`, `{state}`) are substituted as **literal argv items** — never concatenated
  into a shell string.
- `dedup_window_seconds`: suppress identical `(agent, event)` notifications within this
  window (reuses the companion idempotency convention from
  [009-rfc-runtime-companion.md](009-rfc-runtime-companion.md) §Idempotency).

## Command surface

```bash
# fire a one-shot notification for an event (used by watch and by hooks/headless runner)
python3 m8shift-runtime.py notify <agent> --event turn-ready --message "..." [--prompt-file PATH]

# inspect / set enabled tiers
python3 m8shift-runtime.py notify config --enable file,bell --os-preset auto
python3 m8shift-runtime.py notify config --show
```

`watch <agent>` (RFC 009) calls the same `notify` path internally on each transition, so
interactive and headless flows share one notification code path.

## Defaults

- **Headless / CI** (`not isatty()` or `CI` set): tiers 0 + 1 only. Bell, OS, and hook
  are auto-suppressed unless explicitly forced, because there is no human terminal to
  receive them.
- **Interactive TTY**: tiers 0 + 1 + 2 (bell). Tiers 3 (OS) and 4 (hook) stay off until
  the operator enables them.

## Doctor checks

`m8shift-runtime.py doctor` adds read-only checks (it never sends a test notification
that could spam an operator):

- `notify.config.json` parses and lists only known tiers;
- if `os` is enabled, the configured / detected notifier binary resolves on `PATH`
  (warn, not error, if absent);
- if `hook` is set, it is an argv list (warn if it looks like a single shell string with
  metacharacters);
- `notify/` sidecars are gitignored.

## Failure handling

| Failure | Response |
|---------|----------|
| OS notifier binary missing | warn once, fall back to tiers 0–1, continue |
| hook command exits non-zero | record in `log.jsonl`, fall back to tiers 0–1, never block the relay |
| non-TTY but bell enabled | silently skip the bell |
| duplicate event within dedup window | suppress; record the suppression |
| `notify/` directory unwritable | degrade to stdout only; surface once in `doctor` |

## Non-goals

- No bundled Slack / Discord / email / mobile / webhook connector in core or companion —
  external channels are reached only through the operator-owned hook (tier 4), which must
  never become routing authority.
- No resident daemon or background watcher added as a requirement.
- No claim that a closed or suspended proprietary UI is reliably awakened; tier 0/1
  prepare a human, they do not resume the turn.
- No notification field interpreted as core routing; notifications read core state, they
  never write it.

## Acceptance criteria

- With only `stdout` enabled, `notify` prints the event and writes nothing else; the
  relay is unchanged.
- On a non-TTY / CI runtime, `bell`, `os`, and `hook` are auto-suppressed.
- An `os` preset whose binary is absent produces a single warning and a tier 0–1
  fallback, never a non-zero relay-affecting error.
- A configured hook that exits non-zero is logged and does not block or alter the turn.
- Deleting `.m8shift/runtime/notify/` loses only notifications; the relay log and `LOCK`
  are intact.
- Two identical `(agent, event)` notifications inside `dedup_window_seconds` produce one
  delivered notification.
- No notification path calls a core mutating command or makes a forbidden transition
  legal.

## Open questions (flagged for review — designed solo, pending Codex)

1. **OS tier vs hook-only.** Should M8Shift ship the tier-3 OS presets (`osascript` /
   `notify-send` / PowerShell), or ship only tiers 0–2 + the generic hook (tier 4) and
   document the OS commands as example hooks? Shipping presets is friendlier; hook-only
   keeps M8Shift's invoked-binary surface at zero. *Recommendation:* ship tiers 0–2 by
   default, implement tier 4 (hook), and treat tier-3 presets as thin, opt-in,
   fully-degrading convenience over the hook.
2. **`notify` standalone vs watch-only.** Keep `notify` as a standalone command (so the
   headless runner and operator hooks can fire it) in addition to `watch` calling it
   internally. *Recommendation:* both, sharing one path.
3. **Dedup window default.** Is 300 s a sane default for stale re-notification, or should
   it scale with the lock TTL?
4. **Placeholder safety.** Confirm that hook placeholder substitution as discrete argv
   items (never a joined shell string) is sufficient to keep tier 4 free of injection,
   consistent with the argv-only direction of
   [028-rfc-headless-command-templates.md](028-rfc-headless-command-templates.md).
