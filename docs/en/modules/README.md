# Module reference

M8Shift ships a small toolkit, not only `m8shift.py`. This section gives **one reference
page per shipped script**: what it owns, its command surface, the files it reads and
writes, safe examples, and failure modes. Load the single page for the module you need
instead of rereading the full RFC set (see [RFC 045](../rfc/045-rfc-module-reference-examples.md)
and [RFC 023](../rfc/023-rfc-agent-token-footprint.md) on token economy).

The **core relay is degree-1** (one pen). Everything else is optional and advisory: it
reads state M8Shift already stores, never writes the `LOCK`, and never routes work.

## Modules

| Page | Script | Primary authority |
|------|--------|-------------------|
| [Core relay](./core-relay.md) | `m8shift.py` | one-pen relay, `LOCK`, turn ledger, session reports, task board, shared memory, core `doctor`, companion install (RFC 044) |
| [Runtime companion](./runtime.md) | `m8shift-runtime.py` | runtime presence, operator inbox, progress, notifications, provider registry, model/task routing, retention, local reports, headless listener lifecycle (RFC 047) |
| [Context companion](./context.md) | `m8shift-context.py` | context packs, redacted compression/retrieval records, adapter execution (builtin digest + RTK filter + optional Headroom/Kompress) |
| [Worktree toolbox](./worktree.md) | `m8shift-worktree.py` | isolated degree-2 feature lanes and serialized integration |
| [Headroom adapter launcher](./headroom.md) | `m8shift-headroom.py` | optional offline Headroom/Kompress launcher (`m8shift-transform`) |
| [I18n builder](./i18n.md) | `m8shift-i18n.py` | language-pack build and script generation |
| [E2E harness](./e2e.md) | `m8shift-e2e.py` | local smoke scenarios and regression harness |

## Diagram legend

Each page uses a color Mermaid ownership diagram with this convention:

| Color | Meaning |
|-------|---------|
| Blue | executable module |
| Green | generated local state (`M8SHIFT.*`, `.m8shift/`) |
| Red | relay `LOCK` authority |
| Amber | human or agent actor |

## What is honest, and what is not

- **RTK** is a **mode-specific lossy semantic *filter*** (`rtk err`/`test`/`git-log`), **not a
  compressor** — it has no standalone compression percentage.
- **Headroom / Kompress** is real compression, **~45–55% on prose only** (it errors on shell
  content).
- The `compress` command's **stored** compact is a bounded head/tail **excerpt + digest**, not
  the backend's compression, and is labeled *operational orientation, not evidence*.

Verify against originals, logs, tests, and diffs — those remain the source of truth.
