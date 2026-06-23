# Contributing to M8Shift

M8Shift is a single self-contained file (`m8shift.py`), stdlib-only, with no build step
for normal use — clone, copy `m8shift.py` into a repo, run it. Keep it that way.

## Ground rules

- **Stdlib only.** No third-party dependencies, ever. The tool must run on a bare Python 3.8+.
- **One file.** `m8shift.py` stays self-contained and runnable as-is.
- **English is the source of truth.** The committed `m8shift.py` is **English-only**: it is the
  canonical source for every message key and every template. Other languages live as *packs*
  under `i18n/<lang>/` and are spliced in on demand (see below) — they never live in the core.
- **Tests must stay green.** `python3 -m unittest discover -s tests`.

## Internationalisation (i18n)

The runtime selects a language via `--lang <code>` or `$M8SHIFT_LANG` (fallback: English).
A build only carries the languages bundled into it; `KNOWN_LANGS` lists every recognised code
so a file written by a richer build stays loadable (an unbundled language downgrades to English).

### A language pack — `i18n/<lang>/`

| file | what it is |
|------|------------|
| `messages.json` | runtime strings — **same keys as English**, values translated |
| `protocol.md`   | the protocol reference doc (also published as `docs/<lang>/`) |
| `stanza.txt`    | the per-agent stanza template (uses `{begin} {end} {me} {ME} {other} {OTHER}`) |
| `seed.txt`      | the initial `M8SHIFT.md` template (uses `__PROJECT__ __NOW__ __LANG__ __AGENTS__ __A__ __B__` and literal `M8SHIFT:` markers) |
| `bridge.txt`    | the short `AGENTS.md → CLAUDE.md` bridge note |
| `meta.json`     | `{ "code", "name", "provenance" }` |

**Preserve verbatim** in every template/value: `{placeholders}`, `__SEED_TOKENS__`, structural
`M8SHIFT:` markers, protocol state constants (`IDLE`, `WORKING_<AGENT>`, `AWAITING_<AGENT>`,
`DONE`), and all CLI commands/flags/filenames. Never introduce a triple-quote sequence.

> The non-English packs shipped here are **machine-translated, pending human review**
> (`provenance` says so). Improvements to any pack are very welcome.

### Validate and build

```bash
python3 m8shift-i18n.py --check fr                       # validate one pack
python3 m8shift-i18n.py --langs fr,es,de --into ./dist   # build EN + those languages
python3 m8shift-i18n.py --langs fr,es,it,de,pt,ja,ru,zh-cn --into ./dist   # EN + all packs
```

The builder is AST-targeted, idempotent and byte-reproducible: it compiles the result under
*warnings-as-error* and round-trips every injected constant against its pack before writing.

After editing the English protocol template **or** a pack, regenerate the docs so
`test_protocol_docs_in_sync` stays green:

```bash
python3 scripts/gen_docs.py
```

## Commits

Branch per change; keep `main` green. Don't commit relay artefacts (`M8SHIFT.md`,
`.m8shift.lock`, `CLAUDE.md`, `AGENTS.md`, …) — they are gitignored.
